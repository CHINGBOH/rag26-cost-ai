"""Rebuild / refresh catalog_index from text_chunks.

Idempotent. Two jobs:
  1. Backfill NULL chapter_id by parsing the leading numeric token of title
     (e.g. '10.2.7 送配电...' → chapter_id='10.2.7').
  2. Insert any new (file_name, path, title) tuples present in text_chunks
     but missing from catalog_index. Catalog is restricted to chapter docs
     (depth >= 2) — price-info docs (depth=1, YYYY-MM) have no catalog
     concept and are skipped.

Run after `tools/backfill_text_chunks_path.py` or new ingest.
"""

from __future__ import annotations

import os
import re
import sys

import psycopg2

DB_DSN = os.getenv(
    "DATABASE_URL",
    "postgresql://rag_user:rag_password@localhost:5432/rag_db",
)

CHAPTER_RE = re.compile(r"^([0-9]+(?:\.[0-9]+){0,3})")


def backfill_null_chapter_ids(conn) -> int:
    updated = 0
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, title FROM catalog_index
            WHERE (chapter_id IS NULL OR chapter_id = '')
              AND title ~ '^[0-9]+\\.[0-9]+'
        """)
        rows = cur.fetchall()
        for row_id, title in rows:
            m = CHAPTER_RE.match((title or "").strip())
            if not m:
                continue
            cur.execute(
                "UPDATE catalog_index SET chapter_id = %s WHERE id = %s",
                (m.group(1), row_id),
            )
            updated += 1
    conn.commit()
    return updated


def upsert_missing_chapters(conn) -> int:
    """Insert (file_name, chapter_id, title, path, depth) tuples missing from catalog.

    Only chapter docs (depth >= 2 in text_chunks) — price-info docs are excluded.
    Source: distinct (file_name, path, section/subsection title) from text_chunks
    where the chunk represents a clause (depth >= 2 indicates structured chapter).
    """
    inserted = 0
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT
                tc.file_name,
                tc.path,
                tc.depth,
                COALESCE(
                    tc.metadata->>'subsection',
                    tc.metadata->>'section',
                    tc.metadata->>'chapter',
                    tc.section
                ) AS title,
                tc.metadata->>'chapter' AS chapter_id
            FROM text_chunks tc
            WHERE tc.depth >= 2
              AND tc.path IS NOT NULL
              AND COALESCE(
                    tc.metadata->>'subsection',
                    tc.metadata->>'section',
                    tc.metadata->>'chapter',
                    tc.section
                  ) IS NOT NULL
        """)
        candidates = cur.fetchall()

        cur.execute("SELECT path, title FROM catalog_index")
        existing = {(p or "", t or "") for p, t in cur.fetchall()}

        for file_name, path, depth, title, chapter_id in candidates:
            key = (path or "", title or "")
            if key in existing:
                continue
            # If chapter_id is missing from metadata, try to derive from title prefix
            if not chapter_id:
                m = CHAPTER_RE.match((title or "").strip())
                chapter_id = m.group(1) if m else None
            cur.execute(
                """
                INSERT INTO catalog_index (file_name, chapter_id, title, path, depth)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (file_name, chapter_id, title, path, depth),
            )
            existing.add(key)
            inserted += 1
    conn.commit()
    return inserted


def main() -> int:
    conn = psycopg2.connect(DB_DSN)
    try:
        n_back = backfill_null_chapter_ids(conn)
        print(f"[1/2] backfilled chapter_id for {n_back} rows")

        n_new = upsert_missing_chapters(conn)
        print(f"[2/2] inserted {n_new} new catalog rows")

        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE chapter_id IS NOT NULL AND chapter_id != '') AS with_chapter,
                    COUNT(DISTINCT path) AS distinct_paths,
                    COUNT(DISTINCT file_name) AS distinct_files
                FROM catalog_index
            """)
            total, with_ch, paths, files = cur.fetchone()
        print(f"final: {total} rows / {with_ch} with chapter_id / "
              f"{paths} distinct paths / {files} distinct files")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
