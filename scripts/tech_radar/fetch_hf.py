#!/usr/bin/env python3
"""fetch_hf.py — HuggingFace trending models with feature-extraction filter (#94 I5)."""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Iterable

import httpx
import psycopg2

DSN = os.getenv("DATABASE_URL", "postgresql://rag_user:rag_password@localhost:5432/rag_db")

KEYWORDS = [
    "rag", "retrieval", "embedding", "rerank", "reranker", "bge",
    "splade", "colbert", "e5", "instructor", "gte", "nomic",
    "agent", "tool", "chat", "instruct",
]


def score_text(text: str) -> tuple[int, list[str]]:
    tl = text.lower()
    matched = [k for k in KEYWORDS if k in tl]
    return len(matched) * 4, matched


def fetch_hf(limit: int) -> Iterable[dict]:
    url = (
        "https://huggingface.co/api/models"
        "?sort=likes7d&direction=-1"
        "&filter=feature-extraction"
        f"&limit={limit}"
    )
    with httpx.Client(timeout=60.0, trust_env=False) as cli:
        r = cli.get(url, headers={"Accept": "application/json"})
        r.raise_for_status()
    for m in r.json():
        mid = m.get("id") or m.get("modelId")
        if not mid:
            continue
        title = mid
        tags = m.get("tags") or []
        summary = (
            f"likes7d={m.get('likes7d', 0)} likes={m.get('likes', 0)} "
            f"downloads={m.get('downloads', 0)} pipeline={m.get('pipeline_tag', '')}"
        )
        score, matched = score_text(mid + " " + " ".join(tags))
        yield {
            "external_id": mid,
            "title": title,
            "summary": summary,
            "url": f"https://huggingface.co/{mid}",
            "published_at": None,
            "score": score + min(int(m.get("likes7d", 0) or 0), 50),
            "tags": (matched + [t for t in tags if isinstance(t, str)])[:10],
        }


def upsert(rows: list[dict]) -> tuple[int, int]:
    if not rows:
        return 0, 0
    inserted = skipped = 0
    with psycopg2.connect(DSN) as cn, cn.cursor() as c:
        for row in rows:
            c.execute(
                """INSERT INTO tech_radar
                   (source, external_id, title, summary, url,
                    published_at, score, tags, status)
                   VALUES ('huggingface', %s, %s, %s, %s, %s, %s, %s, 'new')
                   ON CONFLICT (source, external_id) DO UPDATE SET
                     score = EXCLUDED.score, summary = EXCLUDED.summary,
                     fetched_at = NOW()""",
                (row["external_id"], row["title"], row["summary"], row["url"],
                 row["published_at"], row["score"], row["tags"]),
            )
            if c.rowcount == 1:
                inserted += 1
            else:
                skipped += 1
    return inserted, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()
    t0 = time.time()
    try:
        rows = list(fetch_hf(args.limit))
    except Exception as e:
        print(f"[fetch_hf] FAIL: {e}", file=sys.stderr)
        sys.exit(1)
    relevant = [r for r in rows if r["score"] > 0]
    inserted, skipped = upsert(relevant)
    print(f"[fetch_hf] fetched={len(rows)} relevant={len(relevant)} "
          f"inserted={inserted} updated={skipped} elapsed={time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
