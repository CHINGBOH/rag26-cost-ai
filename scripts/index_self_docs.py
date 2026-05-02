#!/usr/bin/env python3
"""
index_self_docs.py — Index project docs into Qdrant `rag_self_docs` collection.

Why: the guide-agent currently relies on `rag_system_kb` (a hand-curated KB) and
the OCR'd business PDFs.  When users ask about project-specific things ("how
does proxy.go route /api/search?", "where is the Black config?") the curated KB
runs dry.  Indexing the actual repo docs gives the agent a code-truth fallback.

Scope (deliberately tight):
  - Top-level: README.md, AGENTS.md, GEMINI.md, Gemini.md, CLAUDE.md
  - .agent/**/*.md
  - docs/**/*.md
  - .kimi/*.md
Excluded: node_modules, .venv*, archive, qdrant_storage, llama.cpp,
research/*, reports/*, data/*, frontend dist, anything > 200KB.

Each file is split by H2 (or 1500-char fallback) into chunks, embedded via TEI,
upserted to Qdrant.  Run:
    python3 scripts/index_self_docs.py
    python3 scripts/index_self_docs.py --recreate   # drop & rebuild
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Iterable

REPO = Path(__file__).resolve().parents[1]
TEI_URL = os.getenv("TEI_URL", "http://localhost:8003")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION = "rag_self_docs"
MAX_FILE_BYTES = 200_000

INCLUDE_GLOBS = [
    "README.md", "AGENTS.md", "GEMINI.md", "Gemini.md", "CLAUDE.md",
    "docs/**/*.md",
    ".kimi/*.md",
    ".agent/agents/*.md",
    ".agent/workflows/*.md",
    ".agent/rules/*.md",
]
EXCLUDE_PARTS = {
    "node_modules", ".venv-ocr", ".venv", "archive", "qdrant_storage",
    "llama.cpp", "research", "reports", "data", "dist", "build",
    "site-packages", ".git", ".shared", "skills",
}


def collect_files() -> list[Path]:
    seen: set[Path] = set()
    for pattern in INCLUDE_GLOBS:
        for p in REPO.glob(pattern):
            if not p.is_file():
                continue
            if any(part in EXCLUDE_PARTS for part in p.parts):
                continue
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
            seen.add(p)
    return sorted(seen)


def split_chunks(text: str, max_chars: int = 1500) -> list[str]:
    text = text.strip()
    if not text:
        return []
    # Prefer H2 boundaries; fall back to fixed-size windows
    parts = re.split(r"\n## ", text)
    out: list[str] = []
    for i, part in enumerate(parts):
        if i > 0:
            part = "## " + part
        part = part.strip()
        if len(part) <= max_chars:
            if part:
                out.append(part)
            continue
        for j in range(0, len(part), max_chars):
            chunk = part[j : j + max_chars].strip()
            if chunk:
                out.append(chunk)
    return out


def embed(texts: list[str]) -> list[list[float]]:
    req = urllib.request.Request(
        f"{TEI_URL}/embed",
        data=json.dumps({"inputs": texts}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def qdrant(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{QDRANT_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def ensure_collection(dim: int, recreate: bool = False) -> None:
    if recreate:
        try:
            qdrant("DELETE", f"/collections/{COLLECTION}")
            print(f"[qdrant] dropped {COLLECTION}")
        except urllib.error.HTTPError:
            pass
    try:
        qdrant("GET", f"/collections/{COLLECTION}")
        print(f"[qdrant] {COLLECTION} exists")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        qdrant(
            "PUT",
            f"/collections/{COLLECTION}",
            {"vectors": {"size": dim, "distance": "Cosine"}},
        )
        print(f"[qdrant] created {COLLECTION} (dim={dim})")


def upsert(points: list[dict]) -> None:
    qdrant("PUT", f"/collections/{COLLECTION}/points?wait=true", {"points": points})


def chunk_id(rel_path: str, idx: int, body: str) -> int:
    h = hashlib.sha1(f"{rel_path}#{idx}#{body[:64]}".encode()).hexdigest()
    return int(h[:15], 16)


def iter_chunks() -> Iterable[tuple[str, int, str]]:
    for f in collect_files():
        rel = str(f.relative_to(REPO))
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for i, c in enumerate(split_chunks(text)):
            yield rel, i, c


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recreate", action="store_true")
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    chunks = list(iter_chunks())
    if not chunks:
        print("no chunks collected"); return 1
    print(f"collected {len(chunks)} chunks from "
          f"{len({c[0] for c in chunks})} files")

    if args.dry_run:
        for rel, idx, body in chunks[:5]:
            print(f"  {rel} #{idx}: {body[:80].replace(chr(10),' ')}…")
        return 0

    # Probe dim
    probe = embed([chunks[0][2][:300]])
    dim = len(probe[0])
    ensure_collection(dim, recreate=args.recreate)

    total = 0
    for s in range(0, len(chunks), args.batch):
        batch = chunks[s : s + args.batch]
        vecs = embed([b[2] for b in batch])
        points = [
            {
                "id": chunk_id(rel, idx, body),
                "vector": vec,
                "payload": {
                    "path": rel,
                    "chunk_idx": idx,
                    "content": body,
                    "title": Path(rel).stem,
                },
            }
            for (rel, idx, body), vec in zip(batch, vecs)
        ]
        upsert(points)
        total += len(points)
        print(f"  upserted {total}/{len(chunks)}")
    print(f"done: {total} points in {COLLECTION}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
