#!/usr/bin/env python3
"""Sync architecture section in AGENTS.md / README from runtime reflection.

Pulls /api/v1/architecture/live and writes a markdown table between
<!-- AUTO:ARCHITECTURE:START --> and <!-- AUTO:ARCHITECTURE:END --> markers.

Single source of truth = the running system. Docs become codegen output.

Usage:
    python scripts/sync_arch_docs.py              # uses http://localhost:8002
    RAG_API=http://host:8002 python scripts/sync_arch_docs.py
    python scripts/sync_arch_docs.py --check      # exit 1 if drift detected
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGETS = [REPO_ROOT / "AGENTS.md"]
START = "<!-- AUTO:ARCHITECTURE:START -->"
END = "<!-- AUTO:ARCHITECTURE:END -->"

ROLE_LABELS = {
    "postgresql": "结构化数据 + 中文全文兜底 (zhparser)",
    "qdrant": "向量库 (生产)",
    "elasticsearch": "全文 BM25 + IK 中文分词",
    "neo4j": "知识图谱",
    "redis": "缓存 + 会话",
    "milvus": "向量库 (备选, 可热切)",
}


def fetch_live(api_base: str) -> dict:
    url = f"{api_base.rstrip('/')}/api/v1/architecture/live"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def render(payload: dict, include_timestamp: bool = True) -> str:
    stores = payload.get("stores", {})
    summary = payload.get("summary", {})
    generated = payload.get("generated_at", datetime.now(timezone.utc).isoformat())

    lines: list[str] = []
    if include_timestamp:
        lines.append(f"_最后同步: `{generated}` · 健康度: "
                     f"**{summary.get('available', 0)}/{summary.get('total', 0)}**_")
    else:
        lines.append(f"_健康度: **{summary.get('available', 0)}/{summary.get('total', 0)}**_")
    lines.append("")
    lines.append("| 存储 | 角色 | 状态 | 关键指标 |")
    lines.append("|------|------|------|----------|")

    order = ["postgresql", "qdrant", "elasticsearch", "milvus", "neo4j", "redis"]
    for key in order:
        info = stores.get(key)
        if not info:
            continue
        role = ROLE_LABELS.get(key, info.get("role", "-"))
        avail = info.get("available")
        active = info.get("active")
        if avail and active is False:
            badge = "🟡 待命"
        elif avail:
            badge = "🟢 在线"
        else:
            badge = "🔴 离线"
        metrics = []
        if "version" in info and info["version"]:
            metrics.append(f"v{info['version']}")
        if "chunk_count" in info:
            metrics.append(f"chunks={info['chunk_count']}")
        if "row_count" in info:
            metrics.append(f"rows={info['row_count']}")
        if "doc_count" in info:
            metrics.append(f"docs={info['doc_count']}")
        if "collection_count" in info:
            metrics.append(f"collections={info['collection_count']}")
        if "nodes" in info:
            metrics.append(f"nodes={info['nodes']}")
        if "cluster_status" in info:
            metrics.append(f"cluster={info['cluster_status']}")
        if "extensions" in info and isinstance(info["extensions"], dict):
            ext_on = [k for k, v in info["extensions"].items() if v]
            if ext_on:
                metrics.append("ext=" + ",".join(ext_on))
        metric_str = " · ".join(metrics) if metrics else "-"
        lines.append(f"| **{key}** | {role} | {badge} | {metric_str} |")

    return "\n".join(lines)


def patch_file(path: Path, block: str, structural_block: str, check_only: bool = False) -> bool:
    """Returns True if the *structural* content differs (timestamp ignored)."""
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        re.escape(START) + r"(.*?)" + re.escape(END), re.DOTALL
    )
    m = pattern.search(text)
    if not m:
        print(f"[skip] {path.name}: markers not found", file=sys.stderr)
        return False
    current = m.group(1)
    # Strip the timestamp line from current for structural comparison
    current_struct = re.sub(r"_最后同步: `[^`]*` · ", "_", current).strip()
    if current_struct == structural_block.strip():
        return False
    new_block = f"{START}\n{block}\n{END}"
    if not check_only:
        path.write_text(pattern.sub(new_block, text), encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if any file is out of sync (CI mode)")
    parser.add_argument("--api", default=os.environ.get("RAG_API", "http://localhost:8002"))
    args = parser.parse_args()

    try:
        payload = fetch_live(args.api)
    except Exception as exc:
        print(f"[error] failed to fetch {args.api}/api/v1/architecture/live: {exc}",
              file=sys.stderr)
        return 2

    block = render(payload, include_timestamp=True)
    structural = render(payload, include_timestamp=False)
    drift = False
    for target in TARGETS:
        if not target.exists():
            continue
        changed = patch_file(target, block, structural, check_only=args.check)
        if changed:
            drift = True
            label = "would update" if args.check else "updated"
            print(f"[{label}] {target.relative_to(REPO_ROOT)}")
        else:
            print(f"[ok]      {target.relative_to(REPO_ROOT)} (in sync)")

    if args.check and drift:
        print("\n架构文档与运行时不同步。请运行: python scripts/sync_arch_docs.py",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
