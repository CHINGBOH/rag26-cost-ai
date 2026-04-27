#!/usr/bin/env python3
"""
数据库健康检查与冒烟测试
验证：连接 / 扩展 / 表存在 / 数据量 / embedding 覆盖率 / fee_rates 查询 / pgvector / OCR 覆盖率
"""
import json
import os
import re
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql as pgsql
from psycopg2.extras import RealDictCursor


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.database.scripts.ocr_output_reconciliation import (  # noqa: E402
    build_ocr_source_candidate_score,
    list_missing_scan_state_outputs,
)

OCR_OUTPUT_DIR = Path(os.environ.get("OCR_OUTPUT_DIR", ROOT / "data" / "ocr_outputs"))
_PERIOD_RE = re.compile(r"(20\d{2})[-年](\d{1,2})")
_SKIP_OCR_FILENAMES = {
    "processing_summary.json",
    "processed_documents.log",
    "_scan_state.json",
}

PG_CONFIG = {
    "host":     os.environ.get("PG_HOST", "localhost"),
    "port":     int(os.environ.get("PG_PORT", "5432")),
    "database": os.environ.get("PG_DB", "rag_db"),
    "user":     os.environ.get("PG_USER", "rag_user"),
    "password": os.environ.get("PG_PASSWORD") or "",
}

REQUIRED_TABLES     = [
    "document_registry",
    "text_chunks",
    "price_records",
    "fee_rates",
    "canonical_concepts",
    "concept_relations",
    "concept_evidence_links",
    "chunk_vector_views",
]
REQUIRED_EXTENSIONS = ["vector", "pg_trgm"]
VECTOR_TABLES = ["text_chunks", "price_records", "fee_rates", "canonical_concepts", "chunk_vector_views"]

PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = PASS if ok else FAIL
    print(f"  {status}  {label}" + (f"  — {detail}" if detail else ""))
    return ok


def extract_period(name: str) -> str | None:
    match = _PERIOD_RE.search(name)
    if not match:
        return None
    return f"{match.group(1)}-{int(match.group(2)):02d}"


def normalize_document_label(value: str) -> str:
    return re.sub(r"\s+", "", (value or "")).strip()


def score_ocr_source_candidate(path: Path, data: dict[str, object]) -> tuple[int, int, int, int, int, str]:
    return build_ocr_source_candidate_score(path, data, OCR_OUTPUT_DIR)


def has_column(cur, table_name: str, column_name: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
        LIMIT 1
        """,
        (table_name, column_name),
    )
    return cur.fetchone() is not None


def get_registry_key_column(cur) -> str | None:
    for candidate in ("doc_id", "doc_code"):
        if has_column(cur, "document_registry", candidate):
            return candidate
    return None


def collect_ocr_source_docs() -> list[dict[str, object]]:
    if not OCR_OUTPUT_DIR.exists():
        return []

    docs: dict[str, tuple[tuple[int, int, int, int, str], dict[str, object]]] = {}
    for path in sorted(OCR_OUTPUT_DIR.rglob("*.json")):
        if path.name in _SKIP_OCR_FILENAMES or "chunk" in path.name.lower():
            continue

        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            continue

        pages = data.get("pages")
        if not isinstance(pages, list):
            continue

        doc_id = str(data.get("document_id") or path.stem)
        file_name = str(data.get("file_name") or path.name)
        normalized_file_name = normalize_document_label(file_name) or normalize_document_label(path.stem) or str(path)
        candidate = (
            score_ocr_source_candidate(path, data),
            {
                "doc_id": doc_id,
                "file_name": file_name,
                "normalized_file_name": normalized_file_name,
                "source_path": str(path),
                "is_price_doc": bool(extract_period(file_name)),
            },
        )
        current = docs.get(normalized_file_name)
        if current is None or candidate[0] > current[0]:
            docs[normalized_file_name] = candidate

    return sorted((item[1] for item in docs.values()), key=lambda item: str(item["file_name"]))


def load_grouped_counts(cur, table_name: str) -> dict[str, int]:
    cur.execute(
        pgsql.SQL(
            "SELECT doc_id, COUNT(*) AS n FROM {} WHERE doc_id IS NOT NULL GROUP BY doc_id"
        ).format(pgsql.Identifier(table_name))
    )
    return {str(row["doc_id"]): int(row["n"]) for row in cur.fetchall()}


def load_normalized_file_name_counts(cur, table_name: str) -> dict[str, int]:
    if not has_column(cur, table_name, "file_name"):
        return {}

    cur.execute(
        pgsql.SQL(
            """
            SELECT regexp_replace(COALESCE(file_name, ''), '\\s+', '', 'g') AS normalized_file_name,
                   COUNT(*) AS n
            FROM {}
            WHERE COALESCE(file_name, '') <> ''
            GROUP BY normalized_file_name
            """
        ).format(pgsql.Identifier(table_name))
    )
    return {
        str(row["normalized_file_name"]): int(row["n"])
        for row in cur.fetchall()
        if row["normalized_file_name"]
    }


def print_missing_docs(label: str, docs: list[dict[str, object]]) -> None:
    print(f"       {label}: {len(docs)}")
    for doc in docs[:10]:
        print(f"         - {doc['file_name']} | {doc['source_path']}")


def print_missing_outputs(label: str, outputs: list[dict[str, str]]) -> None:
    print(f"       {label}: {len(outputs)}")
    for item in outputs[:10]:
        print(f"         - {item['output']} | source_pdf={item['source_pdf']}")


def run():
    errors = 0
    print("=" * 64)
    print("RAG Database Verify")
    print("=" * 64)

    # ── 1. 连接 ─────────────────────────────────────────────────
    print("\n[1] Connection")
    try:
        conn = psycopg2.connect(**PG_CONFIG)
        check("PostgreSQL connected", True,
              f"db={PG_CONFIG['database']} host={PG_CONFIG['host']}")
    except Exception as e:
        check("PostgreSQL connected", False, str(e))
        sys.exit(1)

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # ── 2. 扩展 ─────────────────────────────────────────────────
        print("\n[2] Extensions")
        cur.execute("SELECT extname FROM pg_extension")
        installed = {r["extname"] for r in cur.fetchall()}
        for ext in REQUIRED_EXTENSIONS:
            if not check(f"extension {ext}", ext in installed):
                errors += 1

        # ── 3. 表 ───────────────────────────────────────────────────
        print("\n[3] Tables")
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        existing = {r["tablename"] for r in cur.fetchall()}
        for tbl in REQUIRED_TABLES:
            if not check(f"table: {tbl}", tbl in existing):
                errors += 1

        # ── 4. 行数 ─────────────────────────────────────────────────
        print("\n[4] Row counts")
        for tbl in REQUIRED_TABLES:
            if tbl not in existing:
                print(f"  {WARN} {tbl}: skipped (missing)")
                continue
            cur.execute(pgsql.SQL("SELECT COUNT(*) AS n FROM {}").format(pgsql.Identifier(tbl)))
            n = cur.fetchone()["n"]
            if not check(f"{tbl}", n > 0, f"{n:,} rows"):
                errors += 1

        # ── 5. Embedding 覆盖率 ──────────────────────────────────────
        print("\n[5] Embedding coverage")
        for tbl, min_pct in [
            ("text_chunks", 90),
            ("price_records", 90),
            ("fee_rates", 90),
            ("canonical_concepts", 90),
            ("chunk_vector_views", 90),
        ]:
            if tbl not in existing:
                continue
            cur.execute(
                pgsql.SQL(
                    "SELECT COUNT(*) AS total, "
                    "SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END) AS with_emb "
                    "FROM {}"
                ).format(pgsql.Identifier(tbl))
            )
            row = cur.fetchone()
            total, with_emb = row["total"], row["with_emb"] or 0
            pct = (with_emb / total * 100) if total else 0
            ok = pct >= min_pct
            if not ok:
                errors += 1
            check(f"{tbl} embedding coverage", ok,
                  f"{with_emb:,}/{total:,} = {pct:.1f}%")

        # ── 6. Hybrid retrieval infra checks ──────────────────────────────
        print("\n[6] Hybrid infra checks")
        required_indexes = [
            ("index: idx_tc_embedding", {"idx_tc_embedding"}),
            ("index: idx_tc_content", {"idx_tc_content"}),
            ("index: idx_pr_embedding", {"idx_pr_embedding"}),
            ("index: idx_pr_name_trgm", {"idx_pr_name_trgm"}),
            ("index: idx_fr_embedding", {"idx_fr_embedding"}),
            ("index: idx_fr_name_trgm", {"idx_fr_name_trgm"}),
        ]
        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'text_chunks'
              AND column_name = 'tsv'
            """
        )
        has_text_chunks_tsv = cur.fetchone() is not None
        if has_text_chunks_tsv:
            required_indexes.append(
                ("index: idx_tc_tsv", {"idx_tc_tsv", "idx_text_chunks_tsv_chinese"})
            )
        cur.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
            """
        )
        existing_indexes = {r["indexname"] for r in cur.fetchall()}
        for label, acceptable_names in required_indexes:
            if not check(label, any(name in existing_indexes for name in acceptable_names)):
                errors += 1
        if not has_text_chunks_tsv:
            print(f"  {WARN} index: idx_tc_tsv  — skipped (text_chunks.tsv missing)")

        # ── 7. Vector column dimensions ─────────────────────────────────
        print("\n[7] Vector column dimensions")
        dims = {}
        for tbl in VECTOR_TABLES:
            if tbl not in existing:
                continue
            cur.execute(
                """
                SELECT a.atttypmod
                FROM pg_attribute a
                WHERE a.attrelid = %s::regclass
                  AND a.attname = 'embedding'
                  AND NOT a.attisdropped
                LIMIT 1
                """,
                (f"public.{tbl}",),
            )
            row = cur.fetchone()
            if not row:
                check(f"{tbl}.embedding column exists", False)
                errors += 1
                continue
            dim = int(row["atttypmod"] or 0)
            dims[tbl] = dim
            if not check(f"{tbl}.embedding dimension", dim > 0, f"{dim if dim > 0 else 'unknown'}"):
                errors += 1

        if dims:
            unique_dims = sorted(set(dims.values()))
            if not check("embedding dimensions consistent", len(unique_dims) == 1, str(dims)):
                errors += 1
            expected_dim = int(os.environ.get("EMBEDDING_VECTOR_DIM", "0") or "0")
            if expected_dim > 0:
                if not check(
                    "embedding dimension matches EMBEDDING_VECTOR_DIM",
                    len(unique_dims) == 1 and unique_dims[0] == expected_dim,
                    f"expected={expected_dim}, actual={unique_dims}",
                ):
                    errors += 1

        # ── 8. Concept graph coverage ───────────────────────────────────
        print("\n[8] Concept graph coverage")
        cur.execute("SELECT COUNT(*) AS n FROM canonical_concepts")
        concept_count = int(cur.fetchone()["n"] or 0)
        if not check("canonical_concepts has data", concept_count > 0, f"{concept_count} rows"):
            errors += 1

        cur.execute("SELECT COUNT(*) AS n FROM concept_evidence_links")
        link_count = int(cur.fetchone()["n"] or 0)
        if not check("concept_evidence_links has data", link_count > 0, f"{link_count} rows"):
            errors += 1

        cur.execute("SELECT COUNT(*) AS n FROM concept_relations")
        relation_count = int(cur.fetchone()["n"] or 0)
        if not check("concept_relations has data", relation_count > 0, f"{relation_count} rows"):
            errors += 1

        cur.execute(
            """
            SELECT evidence_kind, COUNT(*) AS n
            FROM concept_evidence_links
            GROUP BY evidence_kind
            ORDER BY n DESC
            """
        )
        kinds = {row["evidence_kind"]: int(row["n"]) for row in cur.fetchall()}
        for kind in ("structured_row", "ocr_row", "pdf_page", "embedding_chunk"):
            if not check(f"concept_evidence kind={kind}", kinds.get(kind, 0) > 0, str(kinds.get(kind, 0))):
                errors += 1

        # ── 9. Parent/multi-vector coverage ─────────────────────────────
        print("\n[9] Parent/Multi-vector coverage")
        cur.execute(
            """
            SELECT view_type, COUNT(*) AS n
            FROM chunk_vector_views
            GROUP BY view_type
            ORDER BY view_type
            """
        )
        view_counts = {row["view_type"]: int(row["n"]) for row in cur.fetchall()}
        for view_type in ("raw_chunk", "parent_page_summary", "semantic_terms"):
            if not check(f"chunk_vector_views view_type={view_type}", view_counts.get(view_type, 0) > 0, str(view_counts.get(view_type, 0))):
                errors += 1

        # ── 10. fee_rates 功能测试（模拟 tools.py 查询） ───────────────
        print("\n[10] fee_rates functional test  (mirrors tools.py _query_structured_tables)")
        if "fee_rates" in existing:
            cur.execute("SELECT standard_year, COUNT(*) AS n FROM fee_rates GROUP BY standard_year")
            rows = cur.fetchall()
            if rows:
                for r in rows:
                    check(f"  year={r['standard_year']}", r["n"] > 0, f"{r['n']} rows")
            else:
                check("fee_rates has data", False, "0 rows — 请运行 import_fee_rates.py")
                errors += 1

            cur.execute(
                """SELECT id, doc_id, fee_name, fee_category,
                          rate_min, rate_max, rate_recommended,
                          applicable_scope, base_formula, source_text, standard_year, calc_base
                   FROM fee_rates
                   WHERE fee_name ILIKE '%安全文明%' OR fee_category ILIKE '%安全文明%'
                   LIMIT 5"""
            )
            hits = cur.fetchall()
            if not check("query: 安全文明施工费", len(hits) > 0, f"{len(hits)} hits"):
                errors += 1
            else:
                for h in hits[:2]:
                    rmin = h["rate_min"]
                    rmax = h["rate_max"]
                    rrec = h["rate_recommended"]
                    print(f"       {h['standard_year']} | {h['fee_name'][:30]} | "
                          f"{rmin}%～{rmax}% 推荐{rrec}%")

        # ── 11. pgvector 余弦搜索冒烟测试 ─────────────────────────────
        print("\n[11] pgvector smoke test")
        if "text_chunks" in existing:
            cur.execute(
                "SELECT id FROM text_chunks WHERE embedding IS NOT NULL LIMIT 1"
            )
            sample = cur.fetchone()
            if sample:
                cur.execute(
                    """SELECT id, doc_id,
                              1 - (embedding <=> (SELECT embedding FROM text_chunks WHERE id = %s))
                              AS score
                       FROM text_chunks
                       WHERE embedding IS NOT NULL
                       ORDER BY embedding <=> (SELECT embedding FROM text_chunks WHERE id = %s)
                       LIMIT 3""",
                    (sample["id"], sample["id"]),
                )
                results = cur.fetchall()
                check("cosine search returns results", len(results) > 0,
                      f"top score={results[0]['score']:.4f}" if results else "")
            else:
                print(f"  {WARN} text_chunks 无 embedding，跳过向量测试")

        # ── 12. 文档覆盖明细 ──────────────────────────────────────────
        print("\n[12] Document coverage (text_chunks by file_name)")
        if "text_chunks" in existing:
            cur.execute(
                "SELECT COALESCE(file_name, doc_id) AS src, COUNT(*) AS n "
                "FROM text_chunks GROUP BY src ORDER BY n DESC LIMIT 12"
            )
            for r in cur.fetchall():
                src = (r["src"] or "NULL")[:55]
                print(f"       {r['n']:>7,}  {src}")

        # ── 13. OCR 源文档覆盖审计 ─────────────────────────────────────
        print("\n[13] OCR source coverage audit")
        if not OCR_OUTPUT_DIR.exists():
            print(f"  {WARN} OCR output dir missing: {OCR_OUTPUT_DIR}")
        else:
            missing_scan_state_outputs = list_missing_scan_state_outputs(OCR_OUTPUT_DIR)
            if not check(
                "scan_state live OCR outputs present",
                len(missing_scan_state_outputs) == 0,
                f"missing={len(missing_scan_state_outputs)}",
            ):
                errors += 1
                print_missing_outputs("missing live OCR outputs", missing_scan_state_outputs)

            source_docs = collect_ocr_source_docs()
            if not source_docs:
                print(f"  {WARN} no OCR source documents discovered under {OCR_OUTPUT_DIR}")
            else:
                registry_key_column = get_registry_key_column(cur)
                if not registry_key_column:
                    print(f"  {WARN} document_registry missing doc_id/doc_code, skipping source coverage audit")
                    registry_key_column = None
                if not registry_key_column:
                    pass
                else:
                    cur.execute(
                        pgsql.SQL(
                            "SELECT {} AS doc_key, COALESCE(MAX(file_name), {}::text) AS file_name "
                            "FROM document_registry WHERE {} IS NOT NULL GROUP BY {}"
                        ).format(
                            pgsql.Identifier(registry_key_column),
                            pgsql.Identifier(registry_key_column),
                            pgsql.Identifier(registry_key_column),
                            pgsql.Identifier(registry_key_column),
                        )
                    )
                    registry_rows = cur.fetchall()
                    registry_doc_keys = {str(row["doc_key"]) for row in registry_rows}
                    registry_file_keys = {
                        normalize_document_label(str(row["file_name"]))
                        for row in registry_rows
                        if row["file_name"]
                    }
                    text_counts = load_grouped_counts(cur, "text_chunks")
                    text_file_counts = load_normalized_file_name_counts(cur, "text_chunks")
                    price_counts = load_grouped_counts(cur, "price_records")
                    price_file_counts = load_normalized_file_name_counts(cur, "price_records")

                    missing_registry = [
                        doc
                        for doc in source_docs
                        if str(doc["doc_id"]) not in registry_doc_keys
                        and str(doc["normalized_file_name"]) not in registry_file_keys
                    ]
                    missing_text = [
                        doc
                        for doc in source_docs
                        if text_counts.get(str(doc["doc_id"]), 0) == 0
                        and text_file_counts.get(str(doc["normalized_file_name"]), 0) == 0
                    ]
                    price_docs = [doc for doc in source_docs if bool(doc["is_price_doc"])]
                    missing_price = [
                        doc
                        for doc in price_docs
                        if price_counts.get(str(doc["doc_id"]), 0) == 0
                        and price_file_counts.get(str(doc["normalized_file_name"]), 0) == 0
                    ]

                    if not check(
                        "OCR docs registered in document_registry",
                        len(missing_registry) == 0,
                        f"missing={len(missing_registry)} of {len(source_docs)}",
                    ):
                        errors += 1
                        print_missing_docs("missing registry docs", missing_registry)

                    if not check(
                        "OCR docs imported into text_chunks",
                        len(missing_text) == 0,
                        f"missing={len(missing_text)} of {len(source_docs)}",
                    ):
                        errors += 1
                        print_missing_docs("missing text docs", missing_text)

                    if price_docs:
                        if not check(
                            "Price OCR docs imported into price_records",
                            len(missing_price) == 0,
                            f"missing={len(missing_price)} of {len(price_docs)}",
                        ):
                            errors += 1
                            print_missing_docs("missing price docs", missing_price)

    finally:
        conn.close()

    # ── 结果 ─────────────────────────────────────────────────────
    print("\n" + "=" * 64)
    if errors == 0:
        print(f"{PASS} All checks passed")
    else:
        print(f"{FAIL} {errors} check(s) failed")
        sys.exit(1)


if __name__ == "__main__":
    run()
