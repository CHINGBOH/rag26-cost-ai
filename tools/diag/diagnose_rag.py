#!/usr/bin/env python3
"""
diagnose_rag.py — RAG 检索诊断工具

用法:
    python tools/diagnose_rag.py "2025版费率标准中，房建工程赶工措施费的推荐系数是多少？"
    python tools/diagnose_rag.py "2025年12月深圳市混凝土C30价格"

输出：逐步显示 ILIKE / ts_rank / vector / fee_rates / filter 结果，帮助定位检索失败原因。
"""

import sys
import os
import json

# 确保路径可以找到 pg 配置
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PG_CONFIG = {
    "host": os.environ.get("PG_HOST", "localhost"),
    "port": int(os.environ.get("PG_PORT", "5432")),
    "database": os.environ.get("PG_DB", "rag_db"),
    "user": os.environ.get("PG_USER", "rag_user"),
    "password": os.environ.get("PG_PASSWORD", "your_password_here"),
    "connect_timeout": 5,
}

SCORE_THRESHOLDS = {
    "pgvector":      0.40,
    "pg_fulltext":   0.01,
    "hybrid_vector": 0.40,
    "hybrid_text":   0.01,
    "fee_rates":     0.00,
    "default":       0.40,
}


def _conn():
    import psycopg2
    return psycopg2.connect(**PG_CONFIG)


def section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print("="*60)


def diagnose(query: str) -> None:
    print(f"\n诊断查询: {query!r}")
    conn = _conn()

    # ── 1. ILIKE 精确命中 ────────────────────────────────────────
    section("1. ILIKE 精确命中 (text_chunks)")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, page_number, length(content), left(content, 120)
            FROM text_chunks
            WHERE content ILIKE %s
            LIMIT 10
        """, (f"%{query[:20]}%",))
        rows = cur.fetchall()
    if rows:
        for r in rows:
            print(f"  chunk_id={r[0]} page={r[1]} len={r[2]}")
            print(f"    {r[3]!r}")
    else:
        print("  [无命中] — 尝试较短关键词片段")
        # 用最短的有意义词片段重试
        short = query[:10]
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, page_number, left(content, 100)
                FROM text_chunks
                WHERE content ILIKE %s
                LIMIT 5
            """, (f"%{short}%",))
            rows2 = cur.fetchall()
        for r in rows2:
            print(f"  chunk_id={r[0]} page={r[1]}  {r[2]!r}")

    # ── 2. ts_rank 全文检索得分 ──────────────────────────────────
    section("2. ts_rank 全文检索 (top 5)")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, page_number,
                   ts_rank(tsv, plainto_tsquery('simple', %s)) AS score,
                   left(content, 120)
            FROM text_chunks
            WHERE tsv @@ plainto_tsquery('simple', %s)
            ORDER BY score DESC
            LIMIT 5
        """, (query, query))
        rows = cur.fetchall()
    threshold_fulltext = SCORE_THRESHOLDS["pg_fulltext"]
    if rows:
        for r in rows:
            status = "✓ PASS" if r[2] >= threshold_fulltext else f"✗ FAIL (需>={threshold_fulltext})"
            print(f"  chunk_id={r[0]} page={r[1]} score={r[2]:.4f}  {status}")
            print(f"    {r[3]!r}")
    else:
        print("  [无全文检索命中]")

    # ── 3. pgvector 向量相似度 ───────────────────────────────────
    section("3. pgvector 向量相似度 (top 5，需 embedding 服务)")
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src/backend/retrieval-service"))
        from app.agent.tools import _get_embedding
        emb = _get_embedding(query)
        threshold_vec = SCORE_THRESHOLDS["pgvector"]
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, page_number,
                       1 - (embedding <=> %s::vector) AS score,
                       left(content, 120)
                FROM text_chunks
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT 5
            """, (emb, emb))
            rows = cur.fetchall()
        for r in rows:
            status = "✓ PASS" if r[2] >= threshold_vec else f"✗ FAIL (需>={threshold_vec})"
            print(f"  chunk_id={r[0]} page={r[1]} score={r[2]:.4f}  {status}")
            print(f"    {r[3]!r}")
    except Exception as e:
        print(f"  [跳过向量检索: {e}]")

    # ── 4. fee_rates 结构化表查询 ────────────────────────────────
    section("4. fee_rates 结构化表查询 (ILIKE)")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, standard_year, fee_name, fee_category,
                   rate_min, rate_max, rate_recommended
            FROM fee_rates
            WHERE fee_name ILIKE %s OR fee_category ILIKE %s
               OR source_text ILIKE %s
            LIMIT 10
        """, (f"%{query[:15]}%", f"%{query[:15]}%", f"%{query[:15]}%"))
        rows = cur.fetchall()
    if rows:
        for r in rows:
            print(f"  id={r[0]} year={r[1]} name={r[2]} cat={r[3]}")
            print(f"    min={r[4]}  max={r[5]}  recommended={r[6]}")
    else:
        print("  [fee_rates 无命中] — 该查询在结构化表中无数据")

    # ── 5. 阈值对比摘要 ─────────────────────────────────────────
    section("5. 阈值对比摘要")
    print("  source_db         | 当前阈值 | 旧阈值(0.60) | 说明")
    print("  ------------------|----------|-------------|------")
    for src, thr in SCORE_THRESHOLDS.items():
        old = 0.60
        flag = "✓ 已修复" if thr != old else ""
        print(f"  {src:<18}| {thr:<8.2f}| {old:<12.2f}| {flag}")

    conn.close()
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"用法: python {sys.argv[0]} <查询文本>")
        sys.exit(1)
    diagnose(" ".join(sys.argv[1:]))
