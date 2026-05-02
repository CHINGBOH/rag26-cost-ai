#!/usr/bin/env python3
"""
Backfill text_chunks rows into the Elasticsearch chunks index.

Usage:
    python scripts/backfill_elasticsearch.py            # incremental: skip already-indexed ids
    python scripts/backfill_elasticsearch.py --rebuild  # drop + recreate + full reindex

Env:
    DATABASE_URL    PostgreSQL DSN (default: postgresql://rag_user:rag_password@localhost:5432/rag_db)
    ES_URL          Elasticsearch URL (default: http://localhost:9200)
    ES_INDEX_NAME   target index (default: rag_chunks_v1)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone

# Make retrieval-service infrastructure importable
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "backend", "retrieval-service"))

from infrastructure import elasticsearch_store as es  # noqa: E402

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://rag_user:rag_password@localhost:5432/rag_db",
)
BATCH = int(os.getenv("BACKFILL_BATCH_SIZE", "200"))


def fetch_chunks(conn, last_id: int = 0):
    """Yield text_chunks rows in id order."""
    with conn.cursor(name="es_backfill_cursor", cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.itersize = BATCH
        cur.execute(
            """
            SELECT id, doc_id, page_number, content, section
            FROM text_chunks
            WHERE id > %s
            ORDER BY id ASC
            """,
            (last_id,),
        )
        for row in cur:
            yield dict(row)


def to_es_doc(row) -> dict:
    return {
        "chunk_id": f"tc_{row['id']}",
        "doc_id": str(row.get("doc_id") or ""),
        "content": row.get("content") or "",
        "section": row.get("section") or "",
        "page_number": int(row.get("page_number") or 1),
        "path": [],
        "depth": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true", help="drop and recreate the index")
    ap.add_argument("--limit", type=int, default=0, help="optional cap for testing")
    args = ap.parse_args()

    h = es.health()
    if not h.get("available"):
        print(f"[FATAL] Elasticsearch not reachable: {h.get('reason')}", file=sys.stderr)
        sys.exit(2)
    print(f"[info] ES cluster status: {h.get('cluster_status')}, index exists: {h.get('index_exists')}")

    if args.rebuild:
        print("[info] --rebuild: dropping index")
        es.delete_index()

    if not es.ensure_index():
        print("[FATAL] could not create/ensure index", file=sys.stderr)
        sys.exit(2)

    conn = psycopg2.connect(DB_URL)
    try:
        total = 0
        batch: list = []
        t0 = time.time()
        for row in fetch_chunks(conn):
            batch.append(to_es_doc(row))
            if len(batch) >= BATCH:
                indexed = es.bulk_index(batch)
                total += indexed
                print(f"[info] indexed {total} docs (last batch {indexed}/{len(batch)})")
                batch.clear()
                if args.limit and total >= args.limit:
                    break
        if batch:
            indexed = es.bulk_index(batch)
            total += indexed
            print(f"[info] indexed {total} docs (final batch {indexed}/{len(batch)})")
        elapsed = time.time() - t0
        print(f"[done] total indexed = {total} in {elapsed:.1f}s")
    finally:
        conn.close()

    final = es.health()
    print(f"[verify] index doc_count = {final.get('doc_count')}")


if __name__ == "__main__":
    main()
