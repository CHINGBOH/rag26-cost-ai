#!/usr/bin/env python3
"""
index_system_kb.py — 将 docs/rag-system-internals/ 下的所有 .md 文件
切分为语义段落，通过 TEI 服务嵌入，批量 upsert 到 Qdrant rag_system_kb 集合。

运行方式：
    python scripts/index_system_kb.py

依赖：requests, qdrant-client（或直接用 requests 调 REST API）
"""

import os
import re
import sys
import uuid
import json
import time
import hashlib
import requests
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent.parent
DOCS_DIR = REPO_ROOT / "docs" / "rag-system-internals"
TEI_URL = os.environ.get("TEI_URL", "http://localhost:8003")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION = "rag_system_kb"
BATCH_SIZE = 16   # TEI 每批处理数量
MIN_CONTENT_LEN = 30  # 字符数低于此的段落跳过


# ── 1. 解析 markdown 文件 → 段落列表 ────────────────────────────────────────
def parse_md_file(path: Path) -> list[dict]:
    """
    将一个 .md 文件按 ## 标题切分成段落。
    返回 [{section_id, title, content, source_file}, ...]
    """
    text = path.read_text(encoding="utf-8")
    source_file = path.name

    # 文件第一行 # 是文件标题，不作为独立段落
    lines = text.splitlines()
    file_title = ""
    start = 0
    if lines and lines[0].startswith("# "):
        file_title = lines[0][2:].strip()
        start = 1

    segments: list[dict] = []
    current_title = file_title
    current_lines: list[str] = []

    def flush(title: str, body: list[str]) -> None:
        content = "\n".join(body).strip()
        if len(content) < MIN_CONTENT_LEN:
            return
        # section_id = 文件名 + 标题 hash（短截取）
        h = hashlib.md5(f"{source_file}:{title}".encode()).hexdigest()[:8]
        slug = re.sub(r"[^\w\u4e00-\u9fff]+", "-", title.lower()).strip("-")[:40]
        section_id = f"{slug}-{h}"
        segments.append(
            {
                "section_id": section_id,
                "title": title,
                "content": content,
                "source_file": source_file,
                "tags": _extract_tags(source_file, title),
            }
        )

    for line in lines[start:]:
        if line.startswith("## "):
            flush(current_title, current_lines)
            current_title = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    flush(current_title, current_lines)
    return segments


def _extract_tags(source_file: str, title: str) -> list[str]:
    """根据文件名和标题提取简单 tag 列表。"""
    tag_map = {
        "01-architecture": ["架构", "系统", "服务", "端口"],
        "02-four-databases": ["数据库", "四库", "Qdrant", "PostgreSQL", "Neo4j", "ES"],
        "03-search-tools": ["工具", "检索", "搜索", "hybrid_search"],
        "04-graph-tools": ["图谱", "工具", "概念", "关系", "Neo4j"],
        "05-price-tools": ["价格", "信息价", "price_query", "工具"],
        "06-compute-tools": ["计算", "沙盒", "calculator", "python_eval", "工具"],
        "07-database-tools": ["SQL", "数据库", "工具", "查询"],
        "08-analysis-tools": ["分析", "统计", "工具", "预测"],
        "09-retrieval-pipeline": ["流水线", "检索", "流程", "RRF", "rerank"],
        "10-anti-hallucination": ["防幻觉", "置信度", "可靠性", "机制"],
        "11-indexing-mechanism": ["索引", "上传", "文档", "嵌入", "OCR"],
        "12-agent-runtime": ["Agent", "ReAct", "XState", "状态机", "迭代"],
        "13-usage-guide": ["使用", "指南", "提问", "技巧", "FAQ"],
        "14-system-config": ["配置", "参数", "top_k", "阈值", "设置"],
        "15-faq": ["FAQ", "常见问题", "解答"],
    }
    base = source_file.replace(".md", "")
    tags = tag_map.get(base, [])
    # 从标题提取额外 tag
    for word in ["工具", "检索", "价格", "计算", "配置", "架构", "数据库", "Agent", "FAQ"]:
        if word in title and word not in tags:
            tags.append(word)
    return tags[:6]


# ── 2. 嵌入 ─────────────────────────────────────────────────────────────────
def embed_batch(texts: list[str]) -> list[list[float]]:
    """调用 TEI /embed 接口批量向量化。"""
    resp = requests.post(
        f"{TEI_URL}/embed",
        json={"inputs": texts},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    # TEI 返回 [[float, ...], ...]
    return data


# ── 3. Upsert 到 Qdrant ───────────────────────────────────────────────────
def upsert_points(points: list[dict]) -> None:
    """把 [{id, vector, payload}, ...] 写入 Qdrant。"""
    resp = requests.put(
        f"{QDRANT_URL}/collections/{COLLECTION}/points",
        json={"points": points},
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()
    status = result.get("result", {}).get("status", "?")
    if status != "ok":
        print(f"  ⚠ Qdrant upsert returned status={status}: {result}")


# ── 主流程 ────────────────────────────────────────────────────────────────
def main() -> None:
    # 收集所有段落
    all_segments: list[dict] = []
    md_files = sorted(DOCS_DIR.glob("*.md"))
    if not md_files:
        print(f"❌ 没有找到 .md 文件：{DOCS_DIR}")
        sys.exit(1)

    print(f"📚 读取 {len(md_files)} 个 .md 文件 …")
    for f in md_files:
        segs = parse_md_file(f)
        print(f"  {f.name}: {len(segs)} 段落")
        all_segments.extend(segs)
    print(f"共 {len(all_segments)} 个段落待索引\n")

    # 分批嵌入 + upsert
    total = len(all_segments)
    indexed = 0
    for i in range(0, total, BATCH_SIZE):
        batch = all_segments[i : i + BATCH_SIZE]
        texts = [f"{s['title']}\n\n{s['content']}" for s in batch]

        print(f"  嵌入第 {i+1}-{min(i+BATCH_SIZE, total)}/{total} …", end="", flush=True)
        t0 = time.perf_counter()
        vectors = embed_batch(texts)
        elapsed = time.perf_counter() - t0
        print(f" {elapsed:.1f}s  (dim={len(vectors[0])})")

        # 构造 Qdrant points，用 section_id 的 int hash 做 point id
        points = []
        for seg, vec in zip(batch, vectors):
            # Qdrant point id 必须是 uint64 或 UUID
            pid = str(uuid.uuid5(uuid.NAMESPACE_DNS, seg["section_id"]))
            points.append(
                {
                    "id": pid,
                    "vector": vec,
                    "payload": {
                        "section_id": seg["section_id"],
                        "title": seg["title"],
                        "content": seg["content"],
                        "tags": seg["tags"],
                        "source_file": seg["source_file"],
                    },
                }
            )
        upsert_points(points)
        indexed += len(batch)

    # 验证
    print(f"\n✅ 已 upsert {indexed} 个向量到 {COLLECTION}")
    resp = requests.get(f"{QDRANT_URL}/collections/{COLLECTION}", timeout=10)
    info = resp.json()
    vectors_count = info["result"]["vectors_count"]
    print(f"📊 Qdrant 集合向量数: {vectors_count}")
    if vectors_count < 40:
        print(f"⚠  向量数 {vectors_count} < 40，请检查文档内容是否足够")
    else:
        print(f"🎉 索引完成，{vectors_count} 个向量已就绪")


if __name__ == "__main__":
    main()
