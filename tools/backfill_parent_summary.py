"""Backfill parent_summary into text_chunks.metadata for depth>=3 chunks (#46).

Strategy:
  For each depth=3 chunk with path=`book/10.1/10.1.7`:
    1. parent_path = `book/10.1`
    2. Try a depth=2 text_chunk with path=parent_path → take first 300 chars of content
       (preferring the lowest chunk_index = section header).
    3. Fallback: catalog_index entry with path=parent_path → use its title
       (gives at least a textual chapter label).
  Write metadata.parent_summary + metadata.parent_section.

Idempotent: re-running re-derives everything; only touches rows whose computed
parent_summary differs from the stored one.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_batch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DSN = os.environ.get("DATABASE_URL", "postgresql://rag_user:rag_password@localhost:5432/rag_db")
PARENT_SUMMARY_LEN = 300


def _parent_path(path: str) -> str | None:
    if not path or "/" not in path:
        return None
    parts = path.rsplit("/", 1)
    return parts[0] if len(parts[0]) >= 2 else None


def _parent_section(path: str) -> str:
    if not path:
        return ""
    parts = path.rsplit("/", 1)
    return parts[0].rsplit("/", 1)[-1] if "/" in parts[0] else parts[0]


def main() -> int:
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    cur = conn.cursor()

    # 1. Build parent_path → summary_text map from depth=2 chunks
    cur.execute(
        """
        SELECT DISTINCT ON (path) path, content
        FROM text_chunks
        WHERE depth = 2 AND path IS NOT NULL AND content IS NOT NULL
        ORDER BY path, chunk_index NULLS LAST
        """
    )
    parent_map: dict[str, str] = {p: (c or "")[:PARENT_SUMMARY_LEN].strip() for p, c in cur.fetchall()}
    print(f"[parent] depth=2 chunks providing summaries: {len(parent_map)}")

    # 2. Catalog fallback: parent_path → title
    cur.execute("SELECT path, title FROM catalog_index WHERE depth = 2 AND path IS NOT NULL")
    catalog_map: dict[str, str] = {p: (t or "").strip() for p, t in cur.fetchall() if t}
    print(f"[parent] catalog_index depth=2 entries (fallback): {len(catalog_map)}")

    # 3. Pull all candidate child chunks
    cur.execute(
        """
        SELECT id, path, COALESCE(metadata, '{}'::jsonb)
        FROM text_chunks
        WHERE depth >= 3 AND path IS NOT NULL
        """
    )
    rows = cur.fetchall()
    print(f"[parent] candidate child chunks: {len(rows)}")

    updates: list[tuple[str, int]] = []
    skipped_no_parent = 0
    skipped_unchanged = 0
    used_chunk = 0
    used_catalog = 0
    for cid, path, meta in rows:
        pp = _parent_path(path)
        if not pp:
            skipped_no_parent += 1
            continue

        summary = parent_map.get(pp)
        if summary:
            used_chunk += 1
        else:
            summary = catalog_map.get(pp)
            if summary:
                used_catalog += 1
        if not summary:
            skipped_no_parent += 1
            continue

        section = _parent_section(path)
        meta = dict(meta or {})
        if meta.get("parent_summary") == summary and meta.get("parent_section") == section:
            skipped_unchanged += 1
            continue
        meta["parent_summary"] = summary
        meta["parent_section"] = section
        updates.append((json.dumps(meta, ensure_ascii=False), cid))

    print(f"[parent] used_chunk={used_chunk} used_catalog={used_catalog} "
          f"no_parent={skipped_no_parent} unchanged={skipped_unchanged} "
          f"to_update={len(updates)}")

    if updates:
        execute_batch(
            cur,
            "UPDATE text_chunks SET metadata = %s::jsonb WHERE id = %s",
            updates,
            page_size=200,
        )
    conn.commit()

    cur.execute(
        "SELECT COUNT(*) FROM text_chunks WHERE depth>=3 AND metadata ? 'parent_summary'"
    )
    final = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM text_chunks WHERE depth>=3")
    total = cur.fetchone()[0]
    print(f"[parent] final coverage: {final}/{total} depth>=3 chunks have parent_summary")

    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
