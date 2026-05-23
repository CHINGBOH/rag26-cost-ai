"""Backfill text_chunks.path / depth.

Three jobs:
  1. DELETE empty OCR placeholder rows ("[第N页：扫描图未OCR，原始文本为空]")
     left over from a failed second ingest of 2026年1月.pdf.
  2. UPDATE rows where path IS NULL using path_utils.compute_chunk_path,
     reading metadata for breadcrumb when present.
  3. NORMALIZE existing price-info paths from filename-stem to YYYY-MM,
     so 'path LIKE \\'2025-1%\\'' / cross-period range queries are consistent.

Idempotent. Safe to re-run.
"""

from __future__ import annotations

import os
import re
import sys

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.path_utils import compute_chunk_path  # noqa: E402

DB_DSN = os.getenv(
    "DATABASE_URL",
    "postgresql://rag_user:rag_password@localhost:5432/rag_db",
)

PRICE_INFO_RE = re.compile(r"价格信息|信息价")
PERIOD_FROM_FILENAME_RE = re.compile(r"(20\d{2})[年\-_](\d{1,2})月?")


def delete_empty_ocr_placeholders(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("""
            DELETE FROM text_chunks
            WHERE content LIKE '%扫描图未OCR%原始文本为空%'
        """)
        n = cur.rowcount
    conn.commit()
    return n


def backfill_null_paths(conn) -> tuple[int, int]:
    """Populate path/depth for rows where path IS NULL. Returns (scanned, updated)."""
    scanned = 0
    updated = 0
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, file_name, metadata
            FROM text_chunks
            WHERE path IS NULL
        """)
        rows = cur.fetchall()
        scanned = len(rows)
        for chunk_id, file_name, metadata in rows:
            path, depth = compute_chunk_path(file_name, metadata)
            if path is None:
                continue
            cur.execute(
                "UPDATE text_chunks SET path = %s, depth = %s WHERE id = %s",
                (path, depth, chunk_id),
            )
            updated += 1
    conn.commit()
    return scanned, updated


def normalize_price_info_paths(conn) -> int:
    """Rewrite filename-stem paths for price-info docs to YYYY-MM style."""
    updated = 0
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT file_name, path
            FROM text_chunks
            WHERE depth = 1
              AND path IS NOT NULL
              AND file_name IS NOT NULL
        """)
        candidates = cur.fetchall()
        for file_name, current_path in candidates:
            if not (PRICE_INFO_RE.search(file_name) or "价格信息" in file_name):
                continue
            m = PERIOD_FROM_FILENAME_RE.search(file_name)
            if not m:
                continue
            target = f"{m.group(1)}-{int(m.group(2)):02d}"
            if current_path == target:
                continue
            cur.execute(
                "UPDATE text_chunks SET path = %s, depth = 1 "
                "WHERE file_name = %s AND path = %s",
                (target, file_name, current_path),
            )
            updated += cur.rowcount
    conn.commit()
    return updated


def main() -> int:
    conn = psycopg2.connect(DB_DSN)
    try:
        deleted = delete_empty_ocr_placeholders(conn)
        print(f"[1/3] deleted {deleted} empty OCR placeholder rows")

        scanned, updated_null = backfill_null_paths(conn)
        print(f"[2/3] backfilled {updated_null}/{scanned} rows with NULL path")

        normalized = normalize_price_info_paths(conn)
        print(f"[3/3] normalized {normalized} price-info paths to YYYY-MM")

        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(path) AS with_path,
                    ROUND(100.0 * COUNT(path) / NULLIF(COUNT(*),0), 2) AS pct
                FROM text_chunks
            """)
            total, with_path, pct = cur.fetchone()
        print(f"final: {with_path}/{total} rows have path ({pct}%)")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
