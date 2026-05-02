"""Backfill Qdrant `document_chunks` from PG `text_chunks` (#72).

After legacy ingest, 7887 chunks exist in PG but only 524 points in Qdrant —
hybrid `/api/v1/search` returns 0 for queries the agent answers fine via PG.
PG `text_chunks.embedding` (vector(1024)) is already populated for every row,
so we copy embeddings + payload to Qdrant `document_chunks` with stable id
(idempotent reruns OK).

Usage:
  python scripts/backfill_qdrant_from_pg.py [--limit N] [--batch 64] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import uuid

import httpx
import psycopg2

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_INGEST_COLLECTION", "document_chunks")
PG_DSN = os.getenv(
    "PG_DSN",
    "host=localhost port=5432 dbname=rag_db user=rag_user password=rag_password",
)


def _qdrant_point_id(doc_id: str, chunk_index: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}#{chunk_index}"))


def _parse_pgvector(raw) -> list[float] | None:
    """psycopg2 returns vector as string '[0.1,0.2,...]' unless extension registered."""
    if raw is None:
        return None
    if isinstance(raw, list):
        return [float(x) for x in raw]
    s = str(raw).strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    try:
        return [float(x) for x in s.split(",") if x.strip()]
    except Exception:
        return None


def fetch_chunks(conn, limit: int | None):
    sql = """
        SELECT id, doc_id, COALESCE(chunk_index, 0), content,
               COALESCE(metadata, '{}'::jsonb), file_name, page_number,
               embedding::text
        FROM text_chunks
        WHERE content IS NOT NULL AND length(content) > 0
          AND embedding IS NOT NULL
        ORDER BY id
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with conn.cursor() as cur:
        cur.execute(sql)
        for r in cur:
            yield {
                "id": r[0],
                "doc_id": str(r[1]),
                "chunk_index": int(r[2]) if r[2] is not None else 0,
                "content": r[3],
                "metadata": r[4] or {},
                "file_name": r[5],
                "page": r[6],
                "embedding": _parse_pgvector(r[7]),
            }


def upsert_batch(client: httpx.Client, points: list[dict]) -> None:
    body = {"points": points}
    r = client.put(
        f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points?wait=true",
        json=body,
        timeout=60.0,
    )
    r.raise_for_status()


def ensure_collection(client: httpx.Client, dim: int) -> None:
    r = client.get(f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}")
    if r.status_code == 200:
        return
    payload = {"vectors": {"size": dim, "distance": "Cosine"}}
    client.put(
        f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}", json=payload, timeout=30.0
    ).raise_for_status()
    print(f"[init] created collection {QDRANT_COLLECTION} dim={dim}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    for v in ("http_proxy", "https_proxy", "all_proxy",
              "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        os.environ.pop(v, None)

    print(f"[cfg] qdrant={QDRANT_URL} collection={QDRANT_COLLECTION}")
    conn = psycopg2.connect(PG_DSN)

    transport = httpx.HTTPTransport(proxy=None)
    with httpx.Client(transport=transport) as client:
        first_batch: list[dict] = []
        gen = fetch_chunks(conn, args.limit)
        for c in gen:
            first_batch.append(c)
            if len(first_batch) >= 1:
                break
        if not first_batch or first_batch[0]["embedding"] is None:
            print("[error] no embedded chunks found")
            return 1
        dim = len(first_batch[0]["embedding"])
        ensure_collection(client, dim)
        print(f"[probe] embedding dim={dim}")

        if args.dry_run:
            print("[dry-run] exiting before write")
            return 0

        ok, fail, total, t0 = 0, 0, 0, time.time()
        buf: list[dict] = []

        def flush():
            nonlocal ok, fail, buf
            if not buf:
                return
            try:
                upsert_batch(client, buf)
                ok += len(buf)
            except Exception as e:
                fail += len(buf)
                print(f"[flush] FAIL ({len(buf)}): {e}")
            buf = []

        all_chunks = first_batch + list(gen)
        total = len(all_chunks)
        print(f"[load] {total} embedded chunks fetched")

        for c in all_chunks:
            vec = c["embedding"]
            if vec is None or len(vec) != dim:
                fail += 1
                continue
            md = c["metadata"] if isinstance(c["metadata"], dict) else {}
            pid = _qdrant_point_id(c["doc_id"], c["chunk_index"])
            payload = {
                "doc_id": c["doc_id"],
                "pg_chunk_id": c["id"],
                "chunk_index": c["chunk_index"],
                "text": (c["content"] or "")[:500],
                "file_name": c["file_name"] or md.get("file_name") or md.get("source_file"),
                "page": c["page"] if c["page"] is not None else md.get("page"),
                "source": md.get("source", "backfill_pg"),
            }
            buf.append({"id": pid, "vector": vec, "payload": payload})
            if len(buf) >= args.batch:
                flush()
                if (ok + fail) % (args.batch * 10) == 0:
                    rate = ok / max(time.time() - t0, 1)
                    print(f"[progress] {ok+fail}/{total} ok={ok} fail={fail} {rate:.0f}/s")
        flush()
        elapsed = time.time() - t0
        print(f"[done] ok={ok} fail={fail} total={total} elapsed={elapsed:.1f}s")

    conn.close()
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

