#!/usr/bin/env python3
"""
Backfill searchable chart-page summaries and recover chart-material prices from existing text_chunks.

Goal:
1. Find monthly price document pages that are chart/trend pages.
2. Extract visible material labels from those pages.
3. Recover current-month prices for those materials from same-document text_chunks.
4. Insert/update price_records when structured rows are missing or malformed.
5. Insert one chart_summary text_chunk per chart page so these pages become directly searchable.
"""

from __future__ import annotations

import json
import os
import re
import argparse
from pathlib import Path

import psycopg2


ROOT = Path(__file__).resolve().parents[3]


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    env_path = ROOT / ".env"
    if not env_path.exists():
        return env
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

MATERIAL_SKIP = {
    "造价信息",
    "深圳建设工程价格信息",
    "部分材料价格变化趋势图",
    "部分材料价格变化趋势图（2023-2026年）",
    "单位：",
}


def extract_year_month(file_name: str) -> str:
    match = re.search(r"(20\d{2})[^\d]?(\d{1,2})月", file_name)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}"
    match = re.search(r"(20\d{2})-(\d{2})", file_name)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return ""


def normalize_material_unit(material_name: str, unit: str) -> str:
    normalized = (unit or "").strip().replace("㎡", "m²").replace("?", "")
    if normalized in {"m", "m²"} and material_name in {"中砂", "碎石", "碎石5~25", "碎石5～25", "石粉渣"}:
        return "m³"
    return normalized


def infer_category(material_name: str) -> str:
    mapping = {
        "水泥": "水泥",
        "砂": "砂石",
        "碎石": "砂石",
        "石粉渣": "砂石",
        "柴油": "燃油",
    }
    for key, value in mapping.items():
        if key in material_name:
            return value
    return "其他"


def normalize_material_name(material_name: str) -> str:
    normalized = re.sub(r"\s+", "", (material_name or "")).replace("～", "~")
    normalized = normalized.replace("（", "(").replace("）", ")")
    if normalized in {"柴油", "柴油0#", "柴油0号", "柴油(0号)", "柴油（0号）"}:
        return "柴油0号"
    return normalized


def material_search_aliases(material_name: str) -> list[str]:
    normalized = normalize_material_name(material_name)
    aliases = [material_name, normalized]
    if normalized == "柴油0号":
        aliases.extend(["柴油 0号", "柴油0#", "柴油(0号)", "柴油（0号）", "柴油"])

    deduped: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        if not alias or alias in seen:
            continue
        seen.add(alias)
        deduped.append(alias)
    return deduped


def extract_chart_materials(content: str) -> list[str]:
    materials: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip().strip("()（）")
        if not line or line in MATERIAL_SKIP:
            continue
        if "趋势图" in line or "价格信息" in line:
            continue
        if "单位" in line:
            continue
        if re.fullmatch(r"[\d.\-~～]+", line):
            continue
        if re.search(r"20\d{2}", line):
            continue
        if len(line) < 2 or len(line) > 40:
            continue
        if not re.search(r"[\u4e00-\u9fff]", line):
            continue
        if line not in materials:
            materials.append(line)
    return materials


def is_chart_page_content(content: str) -> bool:
    if "部分材料价格变化趋势图" not in content and "价格变化趋势图" not in content and "价格走势图" not in content:
        return False
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if len(lines) > 18:
        return False
    return any("单位" in line for line in lines)


def extract_material_price(content: str, material_name: str) -> tuple[str, str] | None:
    compact_content = re.sub(r"\s+", "", content).replace("～", "~").replace("㎡", "m²")
    for alias in material_search_aliases(material_name):
        if alias not in content:
            compact_material = re.sub(r"\s+", "", alias).replace("～", "~").replace("㎡", "m²")
            start = compact_content.find(compact_material)
            if start < 0:
                continue
            remainder = compact_content[start + len(compact_material): start + len(compact_material) + 80]
            match = re.search(r"(?P<unit>m³|m²|m|t|kg|个|套|组|台|块|片)(?P<price>\d+\.\d{2})", remainder)
            if match:
                price = match.group("price")
                if float(price) > 5000 and len(price) > 4:
                    trimmed = price[1:]
                    if re.fullmatch(r"\d+\.\d{2}", trimmed):
                        price = trimmed
                return normalize_material_unit(material_name, match.group("unit")), price
            continue

        escaped = re.escape(alias)
        patterns = [
            rf"{escaped}\s*\n(?P<unit>m³|m²|㎡|m|t|kg|个|套|组|台|块|片)\s*\n(?P<price>\d+\.\d{{2}})",
            rf"{escaped}(?:\s*\n[^\n]{{1,40}})?\s*\n(?P<unit>m³|m²|㎡|m|t|kg|个|套|组|台|块|片)\s*\n(?P<price>\d+\.\d{{2}})",
            rf"{escaped}\s+(?P<unit>m³|m²|㎡|m|t|kg|个|套|组|台|块|片)\s+(?P<price>\d+\.\d{{2}})",
        ]
        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                return normalize_material_unit(material_name, match.group("unit")), match.group("price")
    return None


def recover_chart_page_prices(conn) -> tuple[int, int, int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM text_chunks
            WHERE section = 'chart_page'
              AND COALESCE(metadata->>'source', '') = 'chart_page_summary_backfill'
            """
        )
        conn.commit()
        cur.execute(
            """
            SELECT DISTINCT doc_id, file_name, page_number, content
            FROM text_chunks
            WHERE file_name ILIKE '%价格信息%'
              AND (
                  content ILIKE '%部分材料价格变化趋势图%'
                  OR content ILIKE '%价格变化趋势图%'
                  OR content ILIKE '%价格走势图%'
              )
            ORDER BY file_name, page_number
            """
        )
        chart_pages = cur.fetchall()

    summaries_written = 0
    prices_inserted = 0
    prices_updated = 0

    for doc_id, file_name, chart_page, chart_content in chart_pages:
        if not is_chart_page_content(chart_content or ""):
            continue
        year_month = extract_year_month(file_name or "")
        materials = extract_chart_materials(chart_content or "")
        if not materials or not year_month:
            continue

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT page_number, content
                FROM text_chunks
                WHERE doc_id = %s
                ORDER BY page_number, id
                """,
                (doc_id,),
            )
            doc_pages = cur.fetchall()

        page_map: dict[int, list[str]] = {}
        for page_number, content in doc_pages:
            page_map.setdefault(page_number or 0, []).append(content or "")

        resolved: list[dict[str, object]] = []
        missing: list[str] = []

        for material in materials:
            found = None
            for page_number, chunks in page_map.items():
                if page_number == chart_page:
                    continue
                combined = "\n".join(chunks)
                parsed = extract_material_price(combined, material)
                if not parsed:
                    continue
                unit, price = parsed
                found = (page_number, unit, price)
                break

            if not found:
                missing.append(material)
                continue

            table_page, unit, price = found
            resolved.append(
                {
                    "material": material,
                    "unit": unit,
                    "price": price,
                    "table_page": table_page,
                }
            )

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, price_tax_included, metadata
                    FROM price_records
                    WHERE doc_id = %s
                      AND year_month = %s
                      AND material_name = %s
                    ORDER BY
                        CASE
                            WHEN COALESCE(metadata->>'source', '') = 'chart_page_text_backfill' THEN 0
                            WHEN price_tax_included IS NULL THEN 1
                            ELSE 2
                        END,
                        id
                    LIMIT 1
                    """,
                    (doc_id, year_month, material),
                )
                existing = cur.fetchone()

                metadata = json.dumps(
                    {
                        "source": "chart_page_text_backfill",
                        "chart_page": chart_page,
                        "table_page": table_page,
                    },
                    ensure_ascii=False,
                )

                if existing:
                    record_id, current_price, current_metadata = existing
                    current_source = (current_metadata or {}).get("source", "")
                    if current_price is None or current_source == "chart_page_text_backfill":
                        cur.execute(
                            """
                            UPDATE price_records
                            SET unit = %s,
                                price_tax_included = %s,
                                page_number = %s,
                                metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
                            WHERE id = %s
                            """,
                            (unit, price, table_page, metadata, record_id),
                        )
                        prices_updated += cur.rowcount
                else:
                    cur.execute(
                        """
                        INSERT INTO price_records
                        (doc_id, file_name, material_name, specification, unit,
                         price_tax_included, region, year_month, page_number,
                         category, metadata)
                        VALUES (%s, %s, %s, %s, %s, %s, '深圳', %s, %s, %s, %s::jsonb)
                        """,
                        (
                            doc_id,
                            file_name,
                            material,
                            "",
                            unit,
                            price,
                            year_month,
                            table_page,
                            infer_category(material),
                            metadata,
                        ),
                    )
                    prices_inserted += cur.rowcount

        summary_lines = [
            "图表页摘要：部分材料价格变化趋势图",
            f"期间：{year_month}",
            f"图表页：P{chart_page}",
        ]
        if resolved:
            summary_lines.append("当前月可恢复价格：")
            for item in resolved:
                summary_lines.append(
                    f"- {item['material']}：{item['price']} 元/{item['unit']}（价格表 P{item['table_page']}）"
                )
        if missing:
            summary_lines.append("未恢复材料：")
            for material in missing:
                summary_lines.append(f"- {material}")

        summary_content = "\n".join(summary_lines)
        summary_metadata = json.dumps(
            {
                "source": "chart_page_summary_backfill",
                "chart_page": chart_page,
                "year_month": year_month,
                "materials": materials,
                "resolved": resolved,
                "missing": missing,
            },
            ensure_ascii=False,
        )

        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM text_chunks
                WHERE doc_id = %s
                  AND page_number = %s
                  AND section = 'chart_page'
                """,
                (doc_id, chart_page),
            )
            cur.execute(
                """
                SELECT COALESCE(MAX(chunk_index), 0) + 1
                FROM text_chunks
                WHERE doc_id = %s
                """,
                (doc_id,),
            )
            next_chunk_index = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO text_chunks
                (doc_id, file_name, chunk_index, content, page_number, section, metadata)
                VALUES (%s, %s, %s, %s, %s, 'chart_page', %s::jsonb)
                """,
                (doc_id, file_name, next_chunk_index, summary_content, chart_page, summary_metadata),
            )
            summaries_written += cur.rowcount

        conn.commit()

    return summaries_written, prices_inserted, prices_updated


def ensure_trend_tables(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS trend_points (
                id SERIAL PRIMARY KEY,
                series_key TEXT NOT NULL,
                material_name VARCHAR(200) NOT NULL,
                normalized_material VARCHAR(200) NOT NULL,
                year_month VARCHAR(7) NOT NULL,
                unit VARCHAR(20),
                value NUMERIC(12,4) NOT NULL,
                source_doc_id TEXT,
                source_file_name TEXT,
                source_chart_page INTEGER,
                source_table_page INTEGER,
                source_price_record_id INTEGER,
                source_method VARCHAR(50) DEFAULT 'derived_from_price_records',
                metadata JSONB DEFAULT '{}'::jsonb,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE (series_key, year_month)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS trend_relations (
                id SERIAL PRIMARY KEY,
                series_key TEXT NOT NULL,
                from_point_id INTEGER NOT NULL REFERENCES trend_points(id) ON DELETE CASCADE,
                to_point_id INTEGER NOT NULL REFERENCES trend_points(id) ON DELETE CASCADE,
                from_year_month VARCHAR(7) NOT NULL,
                to_year_month VARCHAR(7) NOT NULL,
                unit VARCHAR(20),
                delta_value NUMERIC(12,4) NOT NULL,
                delta_percent NUMERIC(12,4),
                trend_direction VARCHAR(10) NOT NULL,
                months_apart INTEGER NOT NULL DEFAULT 1,
                metadata JSONB DEFAULT '{}'::jsonb,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE (from_point_id, to_point_id)
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tp_series ON trend_points(series_key, year_month)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tp_material ON trend_points(normalized_material, year_month)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tr_series ON trend_relations(series_key, from_year_month, to_year_month)")
    conn.commit()


def backfill_trend_relations(conn) -> tuple[int, int]:
    ensure_trend_tables(conn)

    with conn.cursor() as cur:
        cur.execute("DELETE FROM trend_relations")
        cur.execute("DELETE FROM trend_points")
        cur.execute(
            """
            SELECT id, doc_id, file_name, material_name, unit, price_tax_included, year_month, page_number, metadata
            FROM price_records
            WHERE price_tax_included IS NOT NULL
              AND (
                    COALESCE(metadata->>'source', '') = 'chart_page_text_backfill'
                    OR COALESCE(metadata->>'source', '') = 'ocr_table_normalized'
                  )
            ORDER BY material_name, year_month, id
            """
        )
        rows = cur.fetchall()

    best_points: dict[tuple[str, str], dict] = {}
    for row in rows:
        (
            record_id,
            doc_id,
            file_name,
            material_name,
            unit,
            price_value,
            year_month,
            page_number,
            metadata,
        ) = row
        if not material_name or not year_month or price_value is None:
            continue
        normalized_material = normalize_material_name(material_name)
        series_key = f"{normalized_material}|{unit or ''}"
        key = (series_key, year_month)
        candidate = {
            "record_id": record_id,
            "doc_id": doc_id,
            "file_name": file_name,
            "material_name": material_name,
            "normalized_material": normalized_material,
            "unit": unit or "",
            "value": float(price_value),
            "year_month": year_month,
            "page_number": page_number,
            "metadata": metadata or {},
        }
        existing = best_points.get(key)
        if existing is None:
            best_points[key] = candidate
            continue
        existing_source = (existing["metadata"] or {}).get("source", "")
        candidate_source = (candidate["metadata"] or {}).get("source", "")
        existing_rank = 0 if existing_source == "chart_page_text_backfill" else 1
        candidate_rank = 0 if candidate_source == "chart_page_text_backfill" else 1
        if (candidate_rank, candidate["record_id"]) < (existing_rank, existing["record_id"]):
            best_points[key] = candidate

    inserted_points = 0
    point_ids_by_key: dict[tuple[str, str], int] = {}
    ordered_by_series: dict[str, list[dict]] = {}
    with conn.cursor() as cur:
        for (series_key, year_month), point in sorted(best_points.items(), key=lambda item: (item[0][0], item[0][1])):
            metadata = dict(point["metadata"])
            metadata["backfilled_from_price_record"] = point["record_id"]
            cur.execute(
                """
                INSERT INTO trend_points
                (series_key, material_name, normalized_material, year_month, unit, value,
                 source_doc_id, source_file_name, source_chart_page, source_table_page,
                 source_price_record_id, source_method, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'derived_from_price_records', %s::jsonb)
                RETURNING id
                """,
                (
                    series_key,
                    point["material_name"],
                    point["normalized_material"],
                    year_month,
                    point["unit"],
                    point["value"],
                    point["doc_id"],
                    point["file_name"],
                    metadata.get("chart_page"),
                    metadata.get("table_page") or point["page_number"],
                    point["record_id"],
                    json.dumps(metadata, ensure_ascii=False),
                ),
            )
            point_id = cur.fetchone()[0]
            point_ids_by_key[(series_key, year_month)] = point_id
            ordered_by_series.setdefault(series_key, []).append({**point, "point_id": point_id})
            inserted_points += 1

        inserted_relations = 0
        for series_key, points in ordered_by_series.items():
            points.sort(key=lambda item: item["year_month"])
            for left, right in zip(points, points[1:]):
                left_value = float(left["value"])
                right_value = float(right["value"])
                delta_value = round(right_value - left_value, 4)
                delta_percent = round((delta_value / left_value) * 100, 4) if left_value else None
                if delta_value > 0:
                    direction = "up"
                elif delta_value < 0:
                    direction = "down"
                else:
                    direction = "flat"
                relation_metadata = {
                    "from_source_price_record_id": left["record_id"],
                    "to_source_price_record_id": right["record_id"],
                }
                cur.execute(
                    """
                    INSERT INTO trend_relations
                    (series_key, from_point_id, to_point_id, from_year_month, to_year_month,
                     unit, delta_value, delta_percent, trend_direction, months_apart, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s::jsonb)
                    """,
                    (
                        series_key,
                        left["point_id"],
                        right["point_id"],
                        left["year_month"],
                        right["year_month"],
                        left["unit"] or right["unit"],
                        delta_value,
                        delta_percent,
                        direction,
                        json.dumps(relation_metadata, ensure_ascii=False),
                    ),
                )
                inserted_relations += 1

    conn.commit()
    return inserted_points, inserted_relations


def audit_chart_page_coverage(conn) -> dict[str, object]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT doc_id, file_name, page_number, content
            FROM text_chunks
            WHERE file_name ILIKE '%价格信息%'
              AND (
                  content ILIKE '%部分材料价格变化趋势图%'
                  OR content ILIKE '%价格变化趋势图%'
                  OR content ILIKE '%价格走势图%'
              )
            ORDER BY file_name, page_number
            """
        )
        rows = cur.fetchall()

    page_summaries: list[dict[str, object]] = []
    resolved_materials_total = 0
    missing_materials_total = 0

    for doc_id, file_name, chart_page, content in rows:
        if not is_chart_page_content(content or ""):
            continue

        materials = extract_chart_materials(content or "")
        year_month = extract_year_month(file_name or "")
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT material_name
                FROM price_records
                WHERE doc_id = %s
                  AND year_month = %s
                  AND price_tax_included IS NOT NULL
                """,
                (doc_id, year_month),
            )
            recovered = {normalize_material_name(row[0]) for row in cur.fetchall() if row[0]}

        normalized_materials = [normalize_material_name(material) for material in materials]
        resolved_materials = [material for material, normalized in zip(materials, normalized_materials) if normalized in recovered]
        missing_materials = [material for material, normalized in zip(materials, normalized_materials) if normalized not in recovered]
        resolved_materials_total += len(resolved_materials)
        missing_materials_total += len(missing_materials)

        page_summaries.append(
            {
                "file_name": file_name,
                "year_month": year_month,
                "chart_page": chart_page,
                "materials_visible": len(materials),
                "materials_resolved": len(resolved_materials),
                "materials_missing": len(missing_materials),
                "missing_examples": missing_materials[:5],
            }
        )

    fully_covered_pages = sum(1 for item in page_summaries if item["materials_missing"] == 0)
    return {
        "chart_pages_total": len(page_summaries),
        "chart_pages_fully_covered": fully_covered_pages,
        "resolved_materials_total": resolved_materials_total,
        "missing_materials_total": missing_materials_total,
        "pages": page_summaries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill chart page summaries and audit coverage.")
    parser.add_argument("--audit-only", action="store_true", help="Only audit current chart page coverage.")
    args = parser.parse_args()

    conn = psycopg2.connect(**PG_CONFIG)
    try:
        summaries = inserted = updated = trend_points = trend_relations = 0
        if not args.audit_only:
            summaries, inserted, updated = recover_chart_page_prices(conn)
            trend_points, trend_relations = backfill_trend_relations(conn)
        coverage = audit_chart_page_coverage(conn)
        print(
            json.dumps(
                {
                    "chart_summaries_written": summaries,
                    "price_records_inserted": inserted,
                    "price_records_updated": updated,
                    "trend_points_written": trend_points,
                    "trend_relations_written": trend_relations,
                    "chart_page_coverage": coverage,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
