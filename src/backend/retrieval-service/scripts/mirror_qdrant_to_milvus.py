"""Mirror Qdrant `document_chunks` collection into Milvus.

Why: issue #49 wants Milvus as a switchable vector backend. Embeddings already
live in Qdrant; recomputing them is wasteful and slow. We just stream the
existing vectors + payload into a Milvus collection with the same name and
dimension, so flipping APP_VECTOR_STORE__TYPE=milvus instantly works.

Usage (from repo root):
    PYTHONPATH=src/backend/retrieval-service \
        python -m scripts.mirror_qdrant_to_milvus \
        --qdrant http://localhost:6333 \
        --milvus http://localhost:19530 \
        --collection document_chunks \
        --batch 256
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

import httpx
from pymilvus import DataType, MilvusClient


def fetch_qdrant_batch(
    client: httpx.Client, base: str, collection: str, offset: Any, limit: int
) -> tuple[list[dict], Any]:
    payload = {
        "limit": limit,
        "with_payload": True,
        "with_vector": True,
    }
    if offset is not None:
        payload["offset"] = offset
    r = client.post(f"{base}/collections/{collection}/points/scroll", json=payload)
    r.raise_for_status()
    data = r.json()["result"]
    return data.get("points", []) or [], data.get("next_page_offset")


def ensure_milvus_collection(client: MilvusClient, name: str, dim: int) -> None:
    if client.has_collection(name):
        return
    schema = client.create_schema(auto_id=False, enable_dynamic_field=True)
    schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=128)
    schema.add_field("vector", DataType.FLOAT_VECTOR, dim=dim)
    schema.add_field("doc_id", DataType.VARCHAR, max_length=128)
    schema.add_field("content", DataType.VARCHAR, max_length=8192)
    schema.add_field("title", DataType.VARCHAR, max_length=512)
    schema.add_field("page", DataType.INT64)
    schema.add_field("section", DataType.VARCHAR, max_length=256)
    schema.add_field("chunk_type", DataType.VARCHAR, max_length=64)

    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="vector",
        index_type="HNSW",
        metric_type="COSINE",
        params={"M": 16, "efConstruction": 200},
    )
    client.create_collection(name, schema=schema, index_params=index_params)
    print(f"[milvus] created collection '{name}' (dim={dim}, HNSW/COSINE)")


def normalize_payload(point: dict) -> dict:
    pl = point.get("payload") or {}

    def _s(value: Any, *, max_len: int) -> str:
        if value is None:
            return ""
        text = str(value)
        return text[:max_len]

    return {
        "id": str(point["id"])[:128],
        "vector": point["vector"],
        "doc_id": _s(pl.get("doc_id") or pl.get("document_id"), max_len=128),
        "content": _s(pl.get("content") or pl.get("text"), max_len=8192),
        "title": _s(pl.get("title") or pl.get("doc_title"), max_len=512),
        "page": int(pl.get("page") or pl.get("page_number") or 0),
        "section": _s(pl.get("section"), max_len=256),
        "chunk_type": _s(pl.get("chunk_type"), max_len=64),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qdrant", default="http://localhost:6333")
    ap.add_argument("--milvus", default="http://localhost:19530")
    ap.add_argument("--collection", default="document_chunks")
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--limit", type=int, default=0, help="0 = mirror everything")
    args = ap.parse_args()

    qdrant = httpx.Client(timeout=60.0, trust_env=False)
    info = qdrant.get(f"{args.qdrant}/collections/{args.collection}").json()["result"]
    dim = info["config"]["params"]["vectors"]["size"]
    total = info.get("points_count") or 0
    print(f"[qdrant] {args.collection}: {total} points, dim={dim}")

    milvus = MilvusClient(uri=args.milvus)
    ensure_milvus_collection(milvus, args.collection, dim)

    offset: Any = None
    moved = 0
    t0 = time.monotonic()
    while True:
        points, offset = fetch_qdrant_batch(
            qdrant, args.qdrant, args.collection, offset, args.batch
        )
        if not points:
            break

        rows = [normalize_payload(p) for p in points]
        milvus.upsert(args.collection, data=rows)
        moved += len(rows)

        if moved % (args.batch * 4) == 0 or offset is None:
            rate = moved / max(time.monotonic() - t0, 1e-3)
            print(f"[mirror] {moved}/{total or '?'} points  ({rate:.1f}/s)")

        if args.limit and moved >= args.limit:
            print(f"[mirror] hit --limit {args.limit}, stopping early")
            break
        if offset is None:
            break

    milvus.flush(args.collection)
    final = milvus.get_collection_stats(args.collection).get("row_count")
    print(f"[done] mirrored {moved} points in {time.monotonic() - t0:.1f}s")
    print(f"[milvus] {args.collection} row_count={final}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
