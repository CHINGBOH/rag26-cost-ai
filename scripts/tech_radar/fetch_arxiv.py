#!/usr/bin/env python3
"""
fetch_arxiv.py — 拉 arxiv cs.IR + cs.CL 最近 N 天的论文进 tech_radar 表（#94 I5）

用法：
  python scripts/tech_radar/fetch_arxiv.py --days 7
  python scripts/tech_radar/fetch_arxiv.py --days 30 --max 100
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Iterable
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

import httpx
import psycopg2

DSN = os.getenv(
    "DATABASE_URL",
    "postgresql://rag_user:rag_password@localhost:5432/rag_db",
)

ATOM = "{http://www.w3.org/2005/Atom}"

# 命中关键词 → 加分；命中越多越值得审阅
KEYWORDS = [
    "rag", "retrieval-augmented", "retrieval augmented",
    "agentic", "agent", "tool use", "tool-use",
    "query rewriting", "query reformulation", "hybrid search", "rerank",
    "graph rag", "graphrag", "self-rag", "corrective rag",
    "long context", "knowledge graph", "evidence",
    "multi-hop", "reasoning", "embedding", "vector search",
    "sparse retrieval", "bm25", "splade", "colbert",
]


def score_text(text: str) -> tuple[int, list[str]]:
    text_l = text.lower()
    matched = [k for k in KEYWORDS if k in text_l]
    return len(matched) * 5, matched


def fetch_arxiv(days: int, max_results: int) -> Iterable[dict]:
    """走 export.arxiv.org search API，按提交日期倒序。"""
    cats = "cat:cs.IR+OR+cat:cs.CL"
    url = (
        "https://export.arxiv.org/api/query"
        f"?search_query={quote_plus(cats, safe='+:')}"
        f"&sortBy=submittedDate&sortOrder=descending"
        f"&max_results={max_results}"
    )
    proxies = None  # 显式无代理；某些环境的 ALL_PROXY 会破坏
    with httpx.Client(timeout=30.0, proxy=proxies, trust_env=False) as cli:
        r = cli.get(url)
        r.raise_for_status()
    root = ET.fromstring(r.text)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    for entry in root.findall(f"{ATOM}entry"):
        eid = entry.findtext(f"{ATOM}id", "").strip()
        title = (entry.findtext(f"{ATOM}title", "") or "").strip()
        title = re.sub(r"\s+", " ", title)
        summary = (entry.findtext(f"{ATOM}summary", "") or "").strip()
        summary = re.sub(r"\s+", " ", summary)[:1000]
        pub = entry.findtext(f"{ATOM}published", "").strip()
        try:
            pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
        except Exception:
            pub_dt = None
        if pub_dt and pub_dt < cutoff:
            continue
        link = ""
        for ln in entry.findall(f"{ATOM}link"):
            if ln.attrib.get("rel") == "alternate":
                link = ln.attrib.get("href", "")
                break
        score, matched = score_text(title + " " + summary)
        yield {
            "external_id": eid.rsplit("/", 1)[-1],
            "title": title,
            "summary": summary,
            "url": link or eid,
            "published_at": pub_dt,
            "score": score,
            "tags": matched[:8],
        }


def upsert(rows: list[dict]) -> tuple[int, int]:
    inserted = 0
    skipped = 0
    if not rows:
        return 0, 0
    with psycopg2.connect(DSN) as cn, cn.cursor() as c:
        for row in rows:
            c.execute(
                """
                INSERT INTO tech_radar
                  (source, external_id, title, summary, url,
                   published_at, score, tags, status)
                VALUES ('arxiv', %s, %s, %s, %s, %s, %s, %s, 'new')
                ON CONFLICT (source, external_id) DO NOTHING
                """,
                (
                    row["external_id"], row["title"], row["summary"], row["url"],
                    row["published_at"], row["score"], row["tags"],
                ),
            )
            if c.rowcount == 1:
                inserted += 1
            else:
                skipped += 1
    return inserted, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--max", type=int, default=100)
    args = ap.parse_args()

    t0 = time.time()
    try:
        rows = list(fetch_arxiv(args.days, args.max))
    except Exception as e:
        print(f"[fetch_arxiv] FAIL fetching: {e}", file=sys.stderr)
        sys.exit(1)

    # 仅落入有 RAG 相关关键词命中（score>0）的论文，避免噪音
    relevant = [r for r in rows if r["score"] > 0]
    inserted, skipped = upsert(relevant)
    elapsed = time.time() - t0
    print(
        f"[fetch_arxiv] fetched={len(rows)} relevant={len(relevant)} "
        f"inserted={inserted} skipped={skipped} elapsed={elapsed:.1f}s"
    )


if __name__ == "__main__":
    main()
