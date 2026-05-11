"""Mirror pgvector `text_chunks` embeddings into Milvus via REST API v2.

Why: 切换主力向量后端到 Milvus。使用 REST API（避免 Python 3.13 + gRPC 兼容性问题）。

Usage (from repo root):
    PYTHONPATH=src/backend/retrieval-service \
        python -m scripts.mirror_pgvector_to_milvus \
        --milvus http://localhost:19530 \
        --collection document_chunks \
        --batch 256
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from typing import Any

import psycopg2
import requests


def str_id_to_int64(s: str) -> int:
    h = hashlib.sha256(s.encode()).digest()[:8]
    return int.from_bytes(h, "big", signed=True)


def fetch_pg_batch(
    conn, offset: int, limit: int
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, doc_id, file_name, content, page_number, section,
                   metadata, embedding
            FROM text_chunks
            WHERE embedding IS NOT NULL
            ORDER BY id
            OFFSET %s LIMIT %s
            """,
            (offset, limit),
        )
        columns = [desc[0] for desc in cur.description]
        rows = []
        for row in cur.fetchall():
            record = dict(zip(columns, row))
            record_id = int(record["id"])
            embedding = _parse_pgvector(record.get("embedding"))
            meta = record.get("metadata") or {}
            rows.append({
                "id": str_id_to_int64(str(record_id)),
                "vector": embedding,
                "content": str(record.get("content") or "")[:8192],
                "doc_id": str(record.get("doc_id") or "")[:256],
                "title": str(meta.get("title") or record.get("file_name") or "")[:512],
                "page": int(record.get("page_number") or 0),
                "section": str(record.get("section") or "")[:256],
                "chunk_type": str(meta.get("chunk_type") or meta.get("type") or "paragraph")[:64],
            })
        return rows


def _parse_pgvector(value: Any) -> list[float]:
    if isinstance(value, list):
        return [float(v) for v in value]
    if isinstance(value, str):
        value = value.strip("[]")
        return [float(v) for v in value.split(",") if v.strip()]
    if hasattr(value, "tolist"):
        return value.tolist()
    return []


def setup_milvus_collection(base: str, name: str, dim: int, metric: str) -> None:
    # drop if exists
    r = requests.post(
        f"{base}/v2/vectordb/collections/has",
        json={"collectionName": name},
        timeout=10,
    )
    if r.status_code == 200 and r.json().get("data", {}).get("has", True):
        print(f"[milvus] dropping existing collection '{name}'")
        requests.post(
            f"{base}/v2/vectordb/collections/drop",
            json={"collectionName": name},
            timeout=10,
        )
        time.sleep(1)

    # create
    r = requests.post(
        f"{base}/v2/vectordb/collections/create",
        json={
            "collectionName": name,
            "dimension": dim,
            "metricType": metric,
            "autoId": False,
            "enableDynamicField": True,
        },
        timeout=15,
    )
    body = r.json()
    if body.get("code") != 0:
        raise RuntimeError(f"Failed to create collection: {body}")
    print(f"[milvus] created collection '{name}' (dim={dim}, {metric})")

    # index
    r = requests.post(
        f"{base}/v2/vectordb/indexes/create",
        json={
            "collectionName": name,
            "indexParams": [{
                "fieldName": "vector",
                "indexType": "AUTOINDEX",
                "metricType": metric,
            }],
        },
        timeout=15,
    )
    print(f"[milvus] index: {r.json()}")

    # load
    r = requests.post(
        f"{base}/v2/vectordb/collections/load",
        json={"collectionName": name},
        timeout=15,
    )
    print(f"[milvus] load: {r.json()}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--milvus", default="http://localhost:19530")
    ap.add_argument("--collection", default="document_chunks")
    ap.add_argument("--metric", default="COSINE")
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--limit", type=int, default=0, help="0 = mirror everything")
    ap.add_argument("--pg-host", default="localhost")
    ap.add_argument("--pg-port", type=int, default=5432)
    ap.add_argument("--pg-db", default="rag_db")
    ap.add_argument("--pg-user", default="rag_user")
    ap.add_argument("--pg-password", default="rag_password")
    ap.add_argument("--no-setup", action="store_true", help="skip collection create/index/load")
    args = ap.parse_args()

    conn = psycopg2.connect(
        host=args.pg_host,
        port=args.pg_port,
        dbname=args.pg_db,
        user=args.pg_user,
        password=args.pg_password,
    )

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM text_chunks WHERE embedding IS NOT NULL")
        total = cur.fetchone()[0]
    print(f"[pgvector] text_chunks with embeddings: {total} rows")
    if total == 0:
        print("[pgvector] no embeddings found")
        conn.close()
        return 1

    if not args.no_setup:
        setup_milvus_collection(args.milvus, args.collection, 1024, args.metric)

    offset = 0
    inserted = 0
    t0 = time.monotonic()
    limit = args.limit or total

    while offset < limit:
        batch_size = min(args.batch, limit - offset)
        records = fetch_pg_batch(conn, offset, batch_size)
        if not records:
            break

        r = requests.post(
            f"{args.milvus}/v2/vectordb/entities/upsert",
            json={
                "collectionName": args.collection,
                "data": records,
            },
            timeout=60,
        )
        body = r.json()
        if body.get("code") != 0:
            print(f"[mirror] batch error at offset={offset}: {body}")
            break

        inserted += len(records)
        rate = inserted / max(time.monotonic() - t0, 1e-3)
        pct = inserted / total * 100
        print(
            f"[mirror] {inserted}/{total} ({pct:.1f}%)  "
            f"{rate:.1f} rows/s  offset={offset}"
        )

        offset += batch_size

    conn.close()
    elapsed = time.monotonic() - t0
    print(f"[done] mirrored {inserted} points in {elapsed:.1f}s")

    # flush
    r = requests.post(
        f"{args.milvus}/v2/vectordb/collections/get_stats",
        json={"collectionName": args.collection},
        timeout=10,
    )
    print(f"[milvus] stats: {r.json()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())