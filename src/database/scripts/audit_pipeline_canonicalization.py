#!/usr/bin/env python3
"""
Audit OCR/JSON -> PostgreSQL canonicalization coverage.

Outputs a JSON report that summarizes:
1. suspicious structured labels in price_records
2. null-price / malformed import gaps
3. fee_rates canonical coverage for key fee concepts
4. chart page coverage for searchable chart-derived values
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import psycopg2

from backfill_chart_page_summaries import audit_chart_page_coverage


ROOT = Path(__file__).resolve().parents[3]
SUSPICIOUS_LABEL_RE = re.compile(r"[，,。；;：:]")
CANONICAL_FEE_ITEMS = [
    "企业管理费",
    "利润",
    "安全文明施工费",
    "履约担保手续费",
    "夜间施工增加费",
    "总包管理服务费",
    "发包人供应材料（设备）保管费",
    "暂列金额",
    "优质优价奖励费",
]
CONCEPT_FAMILIES = {
    "fee_rates": [
        "fee item name",
        "rate range",
        "recommended rate",
        "calculation base",
        "applicable scope",
    ],
    "price_records": [
        "year_month",
        "material_name",
        "specification",
        "unit",
        "price_tax_included",
        "price_tax_excluded",
    ],
    "trend_points": [
        "series_key",
        "normalized_material",
        "year_month",
        "unit",
        "value",
    ],
    "text_chunks": [
        "chart_summary",
        "literal rule text",
        "appendix clauses",
        "fill requirement clauses",
    ],
}


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for env_path in [ROOT / ".env", ROOT / "config" / ".env"]:
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


ENV = _load_env()
PG_CONFIG = {
    "host": os.environ.get("PG_HOST") or ENV.get("POSTGRES_HOST", "localhost"),
    "port": int(os.environ.get("PG_PORT") or ENV.get("POSTGRES_PORT", "5432")),
    "dbname": os.environ.get("PG_DB") or ENV.get("POSTGRES_DB", "rag_db"),
    "user": os.environ.get("PG_USER") or ENV.get("POSTGRES_USER", "rag_user"),
    "password": os.environ.get("PG_PASSWORD") or ENV.get("POSTGRES_PASSWORD", ""),
}


def _fetch_value(cur, query: str, params: tuple = ()) -> int:
    cur.execute(query, params)
    value = cur.fetchone()[0]
    return int(value or 0)


def _price_record_audit(cur) -> dict[str, object]:
    total = _fetch_value(cur, "SELECT COUNT(*) FROM price_records")
    null_price = _fetch_value(cur, "SELECT COUNT(*) FROM price_records WHERE price_tax_included IS NULL")
    suspicious = _fetch_value(
        cur,
        """
        SELECT COUNT(*)
        FROM price_records
        WHERE material_name ~ %s
           OR material_name IN ('价格信息', '造价信息', '材料名称')
        """,
        (SUSPICIOUS_LABEL_RE.pattern,),
    )
    cur.execute(
        """
        SELECT COALESCE(metadata->>'source', 'unknown') AS source, COUNT(*)
        FROM price_records
        GROUP BY source
        ORDER BY COUNT(*) DESC, source ASC
        """
    )
    source_breakdown = [
        {"source": source, "count": int(count)}
        for source, count in cur.fetchall()
    ]
    return {
        "total_price_records": total,
        "null_price_records": null_price,
        "suspicious_material_labels": suspicious,
        "source_breakdown": source_breakdown,
    }


def _fee_rate_audit(cur) -> dict[str, object]:
    cur.execute(
        """
        SELECT standard_year, fee_name, COUNT(*)
        FROM fee_rates
        GROUP BY standard_year, fee_name
        ORDER BY standard_year, fee_name
        """
    )
    rows = cur.fetchall()
    by_year: dict[str, dict[str, int]] = {}
    for year, fee_name, count in rows:
        by_year.setdefault(year or "unknown", {})[fee_name] = int(count)

    missing_by_year: dict[str, list[str]] = {}
    for year, items in by_year.items():
        if not re.fullmatch(r"20\d{2}", year):
            continue
        missing = []
        for canonical_item in CANONICAL_FEE_ITEMS:
            if not any(canonical_item in fee_name for fee_name in items):
                missing.append(canonical_item)
        missing_by_year[year] = missing

    return {
        "years": sorted(by_year.keys()),
        "missing_canonical_items_by_year": missing_by_year,
    }


def _text_chunk_audit(cur) -> dict[str, object]:
    chart_summary_chunks = _fetch_value(
        cur,
        """
        SELECT COUNT(*)
        FROM text_chunks
        WHERE section = 'chart_page'
          AND COALESCE(metadata->>'source', '') = 'chart_page_summary_backfill'
        """
    )
    return {
        "chart_summary_chunks": chart_summary_chunks,
    }


def main() -> None:
    conn = psycopg2.connect(**PG_CONFIG)
    try:
        with conn.cursor() as cur:
            price_audit = _price_record_audit(cur)
            fee_audit = _fee_rate_audit(cur)
            chunk_audit = _text_chunk_audit(cur)
            chart_coverage = audit_chart_page_coverage(conn)
            report = {
                "concept_families": CONCEPT_FAMILIES,
                "price_records": price_audit,
                "fee_rates": fee_audit,
                "text_chunks": chunk_audit,
                "chart_page_coverage": chart_coverage,
                "repair_plan": [
                    "continue canonicalizing malformed price_records labels until suspicious_material_labels reaches 0",
                    "expand fee_rates import coverage for missing canonical items reported under missing_canonical_items_by_year",
                    "treat chart_page_coverage as a standing regression check for future monthly PDFs",
                    "keep invalid material labels blocked at import time via is_valid_material_label",
                ],
            }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
