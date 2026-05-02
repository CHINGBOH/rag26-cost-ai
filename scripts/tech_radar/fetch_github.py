#!/usr/bin/env python3
"""fetch_github.py — GitHub releases on RAG-relevant whitelist (#94 I5).

无 token 也能用（rate limit 60/h，足够白名单 ≈10 项目）。
若有 GITHUB_TOKEN 环境变量则用之，提升到 5000/h。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Iterable

import httpx
import psycopg2

DSN = os.getenv("DATABASE_URL", "postgresql://rag_user:rag_password@localhost:5432/rag_db")

WHITELIST = [
    "langchain-ai/langchain",
    "qdrant/qdrant",
    "milvus-io/milvus",
    "pgvector/pgvector",
    "elastic/elasticsearch",
    "huggingface/transformers",
    "huggingface/text-embeddings-inference",
    "deepset-ai/haystack",
    "run-llama/llama_index",
    "infiniflow/ragflow",
    "stanfordnlp/dspy",
    "langchain-ai/langgraph",
]


def fetch_releases(per_repo: int) -> Iterable[dict]:
    headers = {"Accept": "application/vnd.github+json"}
    tok = os.getenv("GITHUB_TOKEN")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    with httpx.Client(timeout=30.0, headers=headers, trust_env=False) as cli:
        for repo in WHITELIST:
            try:
                r = cli.get(
                    f"https://api.github.com/repos/{repo}/releases",
                    params={"per_page": per_repo},
                )
                if r.status_code == 404:
                    continue
                if r.status_code == 403:
                    print(f"[fetch_github] rate-limited at {repo}", file=sys.stderr)
                    break
                r.raise_for_status()
            except Exception as e:
                print(f"[fetch_github] {repo} skipped: {e}", file=sys.stderr)
                continue
            for rel in r.json() or []:
                tag = rel.get("tag_name") or ""
                name = rel.get("name") or tag or "(release)"
                body = (rel.get("body") or "")[:600]
                yield {
                    "external_id": f"{repo}@{tag}",
                    "title": f"{repo} {name}",
                    "summary": body,
                    "url": rel.get("html_url"),
                    "published_at": rel.get("published_at"),
                    "score": 8 + (5 if rel.get("prerelease") is False else 0),
                    "tags": [repo.split("/")[1], "release"],
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
                   VALUES ('github', %s, %s, %s, %s, %s, %s, %s, 'new')
                   ON CONFLICT (source, external_id) DO NOTHING""",
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
    ap.add_argument("--per-repo", type=int, default=3)
    args = ap.parse_args()
    t0 = time.time()
    rows = list(fetch_releases(args.per_repo))
    inserted, skipped = upsert(rows)
    print(f"[fetch_github] repos={len(WHITELIST)} fetched={len(rows)} "
          f"inserted={inserted} skipped={skipped} elapsed={time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
