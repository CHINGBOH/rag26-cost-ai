"""
Agent 工具集 — PG + pgvector 唯一数据库
保留工具名兼容旧代码，内部全部改为 PostgreSQL 实现
"""

import os
import logging
import json
import re
from typing import List

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# ── PG 连接（优先环境变量）───────────────────────────────────────────────────
PG_CONFIG = {
    "host": os.environ.get("PG_HOST", "localhost"),
    "port": int(os.environ.get("PG_PORT", "5432")),
    "database": os.environ.get("PG_DB", "rag_db"),
    "user": os.environ.get("PG_USER", "rag_user"),
    "password": os.environ.get("PG_PASSWORD", "rag_password"),
}


def _get_pg_conn():
    import psycopg2
    cfg = {**PG_CONFIG, "connect_timeout": 5}
    return psycopg2.connect(**cfg)


def _get_embedding(text: str) -> List[float]:
    """独立 embedding 实例（避免全局 mock）"""
    from infrastructure.embedding_service import EmbeddingService
    try:
        svc = EmbeddingService(device='cpu', use_mock=False)
        return svc.encode_single(text)
    except Exception as e:
        logger.warning(f"Embedding failed, fallback to mock: {e}")
        svc = EmbeddingService(use_mock=True)
        return svc.encode_single(text)


def _chunk_from_pg_row(row: tuple, source_db: str, score: float = 0.0) -> dict:
    """统一 PG 查询结果 → chunk dict"""
    return {
        "chunk_id": f"{source_db}_{row[0]}",
        "doc_id": row[1] or "",
        "page_number": row[2] or 1,
        "source_db": source_db,
        "content": row[3] or "",
        "score": round(score, 4),
        "metadata": row[4] if isinstance(row[4], dict) else {},
    }


def _row_to_chunk(row, source_db: str) -> dict:
    """通用行转 chunk，兼容不同列数"""
    return {
        "chunk_id": f"{source_db}_{row[0]}",
        "doc_id": row[1] or "",
        "page_number": row[2] or 1,
        "source_db": source_db,
        "content": row[3] or "",
        "score": round(row[-1], 4) if len(row) > 5 and isinstance(row[-1], (int, float)) else 0.0,
        "metadata": row[4] if len(row) > 4 and isinstance(row[4], dict) else {},
    }


def _query_structured_tables(query: str, top_k: int = 10) -> list[dict]:
    """
    查询结构化表（fee_rates 等）并返回 chunk list。
    分数固定为 0.90，不受 SCORE_THRESHOLD 影响。
    供 text_search / keyword_search / category_search / rag_pipeline 复用。

    匹配策略：先整串 ILIKE，若无结果则对 2~8 字中文片段逐一匹配（支持长查询句）。
    """
    results: list[dict] = []
    if not query.strip():
        return results
    q = query.strip()

    # 提取候选匹配词：全串 + 滑动窗口（避免贪婪匹配漏掉关键词）
    import re as _re
    fragments: list[str] = [q]
    for _run in _re.findall(r'[\u4e00-\u9fff]+', q):
        for _len in range(2, 8):
            for _s in range(len(_run) - _len + 1):
                fragments.append(_run[_s:_s + _len])
    seen_fragments: set[str] = set()
    unique_fragments = []
    for f in fragments:
        if f not in seen_fragments:
            seen_fragments.add(f)
            unique_fragments.append(f)

    try:
        conn = _get_pg_conn()
        seen_ids: set[str] = set()
        with conn.cursor() as cur:
            for frag in unique_fragments:
                if len(results) >= top_k:
                    break
                cur.execute("""
                    SELECT id, document_id, fee_name, fee_category,
                           rate_min, rate_max, rate_recommended,
                           applicable_scope, base_formula, source_text, standard_year
                    FROM fee_rates
                    WHERE fee_name ILIKE %s OR fee_category ILIKE %s
                       OR source_text ILIKE %s
                    LIMIT %s
                """, (f"%{frag}%", f"%{frag}%", f"%{frag}%", top_k))
                for fr in cur.fetchall():
                    fid, fdoc_id, fname, fcat, rmin, rmax, rrec, scope, formula, src, yr = fr
                    cid = f"fr_{fid}"
                    if cid in seen_ids:
                        continue
                    seen_ids.add(cid)
                    rmin_s = f"{float(rmin):.4g}" if rmin is not None else "—"
                    rmax_s = f"{float(rmax):.4g}" if rmax is not None else "—"
                    rrec_s = f"{float(rrec):.4g}" if rrec is not None else "—"
                    content_text = (
                        f"【{yr}版费率标准】{fname}（{fcat}）\n"
                        f"参考范围：{rmin_s}～{rmax_s}，推荐系数：{rrec_s}\n"
                        f"适用范围：{scope or ''}\n"
                        f"计算公式：{formula or ''}"
                    ).strip()
                    results.append({
                        "chunk_id": cid,
                        "doc_id": str(fdoc_id or ""),
                        "page_number": 1,
                        "source_db": "fee_rates",
                        "content": content_text[:500],
                        "score": 0.90,
                        "metadata": {},
                    })
        conn.close()
    except Exception as e:
        logger.error(f"[_query_structured_tables] fee_rates error: {e}")
    return results


# ── 新工具：pg_vector_search（PG pgvector）──────────────────────────────────


@tool
def vector_search(query: str, top_k: int = 10) -> str:
    """向量语义搜索：从 text_chunks 表中使用 pgvector 余弦相似度检索"""
    if not query.strip():
        return json.dumps([])

    try:
        query_embedding = _get_embedding(query.strip())
        if not query_embedding:
            return json.dumps([])

        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, document_id, page_number, content,
                       1 - (embedding <=> %s::vector) AS score
                FROM text_chunks
                WHERE embedding IS NOT NULL
                  AND 1 - (embedding <=> %s::vector) >= 0.40
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """, (query_embedding, query_embedding, query_embedding, top_k))

            rows = cur.fetchall()
            results = []
            for row in rows:
                results.append({
                    "chunk_id": f"tc_{row[0]}",
                    "doc_id": str(row[1] or ""),
                    "page_number": row[2] or 1,
                    "source_db": "pgvector",
                    "content": row[3] or "",
                    "score": round(float(row[4] or 0), 4),
                    "metadata": {},
                })
            return json.dumps(results, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[vector_search] error: {e}")
        return json.dumps([])


# ── 新工具：keyword_search（PG tsvector 全文检索）────────────────────────────


@tool
def keyword_search(query: str, top_k: int = 10) -> str:
    """关键词全文搜索：从 text_chunks 表中使用 PostgreSQL tsvector + ts_rank 检索"""
    if not query.strip():
        return json.dumps([])

    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, document_id, page_number, content,
                       ts_rank(tsv, plainto_tsquery('simple', %s)) AS score
                FROM text_chunks
                WHERE tsv @@ plainto_tsquery('simple', %s)
                ORDER BY score DESC
                LIMIT %s
            """, (query, query, top_k))

            rows = cur.fetchall()
            results = []
            for row in rows:
                results.append({
                    "chunk_id": f"tc_{row[0]}",
                    "doc_id": str(row[1] or ""),
                    "page_number": row[2] or 1,
                    "source_db": "pg_fulltext",
                    "content": row[3] or "",
                    "score": round(float(row[4] or 0), 4),
                    "metadata": {},
                })

            pass  # structured tables queried below

        # also query fee_rates and other structured tables
        results.extend(_query_structured_tables(query, top_k))

        return json.dumps(results, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[keyword_search] error: {e}")
        return json.dumps([])


# ── category_search（目录索引检索）──────────────────────────────────────────


@tool
def category_search(query: str, top_k: int = 5) -> str:
    """目录索引检索：在文档章节目录中搜索材料/工艺所在的章节编号和标题。
    适用场景：当不确定某材料在哪个章节时，先用此工具定位章节，再用 text_search 检索具体数据。
    返回：章节编号、章节标题、页码。
    """
    if not query.strip():
        return json.dumps([])

    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            q = query.strip()

            # 策略1：ILIKE 精确字面匹配（中文复合词可靠），限制 < 600 chars，优先带章节号的短块
            cur.execute("""
                SELECT id, document_id, page_number, content,
                       length(content) AS char_len
                FROM text_chunks
                WHERE content ILIKE %s
                  AND length(content) < 600
                ORDER BY
                    CASE WHEN content ~ '[0-9]+\\.[0-9]+(\\.[0-9]+)*'
                              OR content ~ '（[一二三四五六七八九十0-9]+）'
                         THEN 0 ELSE 1 END,
                    length(content)
                LIMIT %s
            """, (f"%{q}%", top_k))
            rows = cur.fetchall()

            # 策略2：放宽至 length<1200 的任意 ILIKE 命中
            if not rows:
                cur.execute("""
                    SELECT id, document_id, page_number, content,
                           length(content) AS char_len
                    FROM text_chunks
                    WHERE content ILIKE %s
                      AND length(content) < 1200
                    ORDER BY length(content)
                    LIMIT %s
                """, (f"%{q}%", top_k))
                rows = cur.fetchall()

        conn.close()

        results = []
        sec_re = re.compile(r'(\d+\.\d+(?:\.\d+)*)')
        for row in rows:
            content = row[3] or ""
            # 从内容中提取章节编号
            sec_match = sec_re.search(content)
            section_number = sec_match.group(1) if sec_match else ""
            results.append({
                "chunk_id": f"cat_{row[0]}",
                "doc_id": str(row[1] or ""),
                "page_number": row[2] or 1,
                "section": section_number,
                "content": content[:300],
                "score": 1.0,
            })

        # 额外查询 fee_rates 等结构化表
        for chunk in _query_structured_tables(query, top_k):
            results.append({
                "chunk_id": chunk["chunk_id"],
                "doc_id": chunk["doc_id"],
                "page_number": chunk["page_number"],
                "section": chunk.get("metadata", {}).get("fee_name", ""),
                "content": chunk["content"],
                "score": chunk["score"],
            })

        logger.info(f"[category_search] query='{query}' hits={len(results)}")
        return json.dumps(results, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[category_search] error: {e}")
        return json.dumps([])


# ── graph_search（已废弃，Neo4j 移除）────────────────────────────────────────


@tool
def graph_search(query: str, top_k: int = 10) -> str:
    """知识图谱搜索：已废弃（Neo4j 已移除），返回空结果"""
    logger.warning("[graph_search] Neo4j removed, returning empty")
    return json.dumps([])


# ── hybrid_search（PG 双路融合）─────────────────────────────────────────────


@tool
def hybrid_search(query: str, top_k: int = 10) -> str:
    """混合检索（pgvector + tsvector）：综合召回，适合复杂问题"""
    if not query.strip():
        return json.dumps([])

    try:
        query_embedding = _get_embedding(query.strip())
        conn = _get_pg_conn()
        results = []
        seen_ids = set()

        with conn.cursor() as cur:
            # 向量路
            if query_embedding:
                cur.execute("""
                    SELECT id, document_id, page_number, content,
                           1 - (embedding <=> %s::vector) AS score
                    FROM text_chunks
                    WHERE embedding IS NOT NULL
                      AND 1 - (embedding <=> %s::vector) >= 0.40
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """, (query_embedding, query_embedding, query_embedding, top_k))
                for row in cur.fetchall():
                    cid = row[0]
                    if cid not in seen_ids:
                        seen_ids.add(cid)
                        results.append({
                            "chunk_id": f"tc_{cid}",
                            "doc_id": str(row[1] or ""),
                            "page_number": row[2] or 1,
                            "source_db": "hybrid_vector",
                            "content": row[3] or "",
                            "score": round(float(row[4] or 0), 4),
                            "metadata": {},
                        })

            # 全文路
            cur.execute("""
                SELECT id, document_id, page_number, content,
                       ts_rank(tsv, plainto_tsquery('simple', %s)) AS score
                FROM text_chunks
                WHERE tsv @@ plainto_tsquery('simple', %s)
                ORDER BY score DESC
                LIMIT %s
            """, (query, query, top_k))
            for row in cur.fetchall():
                cid = row[0]
                if cid not in seen_ids:
                    seen_ids.add(cid)
                    results.append({
                        "chunk_id": f"tc_{cid}",
                        "doc_id": str(row[1] or ""),
                        "page_number": row[2] or 1,
                        "source_db": "hybrid_text",
                        "content": row[3] or "",
                        "score": round(float(row[4] or 0), 4),
                        "metadata": {},
                    })

        # 按分数重排
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return json.dumps(results[:top_k], ensure_ascii=False)
    except Exception as e:
        logger.error(f"[hybrid_search] error: {e}")
        return json.dumps([])


# ── text_search（PG 语义搜索，保留原名兼容）───────────────────────────────────


@tool
def text_search(query: str, top_k: int = 8) -> str:
    """语义向量搜索+全文检索：从 text_chunks 表中检索"""
    if not query.strip():
        return json.dumps([])

    results = []
    seen_ids = set()
    conn = _get_pg_conn()

    # 1. Full-text search (tsv)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, document_id, page_number, content,
                       ts_rank(tsv, plainto_tsquery('simple', %s)) AS score
                FROM text_chunks
                WHERE tsv @@ plainto_tsquery('simple', %s)
                ORDER BY score DESC
                LIMIT %s
            """, (query, query, top_k))
            for row in cur.fetchall():
                if row[0] not in seen_ids:
                    seen_ids.add(row[0])
                    results.append({
                        "chunk_id": f"tc_{row[0]}",
                        "doc_id": str(row[1] or ""),
                        "page_number": row[2] or 1,
                        "source_db": "pg_fulltext",
                        "content": row[3] or "",
                        "score": round(float(row[4] or 0), 4),
                        "metadata": {},
                    })
    except Exception as e:
        logger.error(f"[text_search] fulltext error: {e}")

    # 2. Vector search if embedding available
    try:
        query_embedding = _get_embedding(query.strip())
        if query_embedding:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, document_id, page_number, content,
                           1 - (embedding <=> %s::vector) AS score
                    FROM text_chunks
                    WHERE embedding IS NOT NULL
                      AND 1 - (embedding <=> %s::vector) >= 0.40
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """, (query_embedding, query_embedding, query_embedding, top_k))
                for row in cur.fetchall():
                    if row[0] not in seen_ids:
                        seen_ids.add(row[0])
                        results.append({
                            "chunk_id": f"tc_{row[0]}",
                            "doc_id": str(row[1] or ""),
                            "page_number": row[2] or 1,
                            "source_db": "pgvector",
                            "content": row[3] or "",
                            "score": round(float(row[4] or 0), 4),
                            "metadata": {},
                        })
    except Exception as e:
        logger.error(f"[text_search] vector error: {e}")

    # 3. fee_rates and other structured tables lookup — score 0.9, always passes filter
    for chunk in _query_structured_tables(query, top_k):
        if chunk["chunk_id"] not in seen_ids:
            seen_ids.add(chunk["chunk_id"])
            results.append(chunk)

    conn.close()
    results.sort(key=lambda x: x["score"], reverse=True)
    return json.dumps(results[:top_k], ensure_ascii=False)


# ── price_query（PG SQL 精确查询，保留）──────────────────────────────────────


@tool
def price_query(material_name: str = "", specification: str = "", year_month: str = "", top_k: int = 5) -> str:
    """价格精确查询：从 price_records 表中查询建材价格信息。
    year_month 支持多种格式：'2025-12'、'202512'、'2025年12月'。
    若指定期间无数据，自动回退到最近有数据的期间。
    """
    try:
        # ── 日期格式标准化 ──────────────────────────────────────────────────
        normalized_period = ""
        if year_month:
            ym = year_month.strip()
            # 中文格式：2025年12月 → 2025-12
            m = re.match(r'(\d{4})[年\-/](\d{1,2})月?$', ym)
            if m:
                normalized_period = f"{m.group(1)}-{int(m.group(2)):02d}"
            # 纯数字 202512 → 2025-12
            elif re.match(r'^\d{6}$', ym):
                normalized_period = f"{ym[:4]}-{ym[4:]}"
            # 已是 YYYY-MM 格式
            elif re.match(r'^\d{4}-\d{2}$', ym):
                normalized_period = ym
            else:
                normalized_period = ym  # 原样传入，交给 DB 处理

        conn = _get_pg_conn()
        with conn.cursor() as cur:

            def _build_and_run(period_filter: str | None) -> list:
                where_clauses = []
                params: list = []
                if material_name:
                    where_clauses.append(
                        "(material_name ILIKE %s OR spec ILIKE %s OR to_tsvector('simple', material_name) @@ plainto_tsquery('simple', %s))"
                    )
                    params.extend([f"%{material_name}%", f"%{material_name}%", material_name])
                if specification:
                    # 兼容乘号变体：× x * X
                    spec_normalized = re.sub(r'[×xX*]', '%', specification)
                    # 提取截面部分（如 "5×120" 从 "0.6/1KV YJV 5×120"）作为更宽松的模糊键
                    _xs_m = re.search(r'(\d+)\s*[×xX*]\s*(\d+)', specification)
                    _xs_key = f"%{_xs_m.group(1)}%{_xs_m.group(2)}%" if _xs_m else f"%{spec_normalized}%"
                    where_clauses.append("(spec ILIKE %s OR spec ILIKE %s OR spec ILIKE %s)")
                    params.extend([f"%{specification}%", f"%{spec_normalized}%", _xs_key])
                if period_filter:
                    where_clauses.append("period = %s")
                    params.append(period_filter)

                where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
                sql = f"""
                    SELECT id, document_id, page_number,
                           material_name || ' ' || COALESCE(spec, '') ||
                           ' 单位:' || COALESCE(unit, '') ||
                           ' 价格:' || COALESCE(price::text, 'N/A') || '元' ||
                           ' 期间:' || COALESCE(period, '') ||
                           ' 类别:' || COALESCE(category, '') AS content,
                           source_row AS metadata,
                           0.0 AS dist
                    FROM price_records
                    {where_sql}
                    ORDER BY period DESC, id
                    LIMIT %s
                """
                params.append(top_k * 3)
                cur.execute(sql, params)
                return cur.fetchall()

            rows = _build_and_run(normalized_period if normalized_period else None)

            # 若 material_name 过滤导致无结果，尝试仅用 spec 过滤
            if not rows and material_name and specification:
                _saved_mn = material_name
                material_name = ""
                rows = _build_and_run(normalized_period if normalized_period else None)
                material_name = _saved_mn
                if rows:
                    logger.info(f"[price_query] material_name filter yielded 0; retried with spec-only, got {len(rows)} rows")

            # 若指定了期间但无结果，查询最近有数据的期间并附注
            fallback_note = ""
            if normalized_period and not rows:
                cur.execute(
                    "SELECT DISTINCT period FROM price_records ORDER BY period DESC LIMIT 30"
                )
                available = [r[0] for r in cur.fetchall()]
                # 优先找 ≤ 目标期间的最近期间
                candidates_before = [p for p in sorted(available, reverse=True) if p <= normalized_period]
                fallback_period = candidates_before[0] if candidates_before else None
                if fallback_period:
                    rows = _build_and_run(fallback_period)
                # 若往前找也空（该规格当时不存在），再找最近有该规格的期间（任意方向）
                if not rows:
                    # 该规格在目标期间之前不存在，找最早（升序）有该规格的期间
                    where_clauses2: list = []
                    params2: list = []
                    if material_name:
                        where_clauses2.append("(material_name ILIKE %s OR to_tsvector('simple', material_name) @@ plainto_tsquery('simple', %s))")
                        params2.extend([f"%{material_name}%", material_name])
                    if specification:
                        spec_norm2 = re.sub(r'[×xX*]', '%', specification)
                        _xs_m2 = re.search(r'(\d+)\s*[×xX*]\s*(\d+)', specification)
                        _xs_key2 = f"%{_xs_m2.group(1)}%{_xs_m2.group(2)}%" if _xs_m2 else f"%{spec_norm2}%"
                        where_clauses2.append("(spec ILIKE %s OR spec ILIKE %s OR spec ILIKE %s)")
                        params2.extend([f"%{specification}%", f"%{spec_norm2}%", _xs_key2])
                    if normalized_period:
                        where_clauses2.append("period > %s")
                        params2.append(normalized_period)
                    where_sql2 = ("WHERE " + " AND ".join(where_clauses2)) if where_clauses2 else ""
                    sql2 = f"""
                        SELECT id, document_id, page_number,
                               material_name || ' ' || COALESCE(spec, '') ||
                               ' 单位:' || COALESCE(unit, '') ||
                               ' 价格:' || COALESCE(price::text, 'N/A') || '元' ||
                               ' 期间:' || COALESCE(period, '') ||
                               ' 类别:' || COALESCE(category, '') AS content,
                               source_row AS metadata,
                               0.0 AS dist
                        FROM price_records
                        {where_sql2}
                        ORDER BY period ASC, id
                        LIMIT %s
                    """
                    params2.append(top_k * 3)
                    cur.execute(sql2, params2)
                    rows = cur.fetchall()
                    if rows:
                        # 提取最早有效期间
                        first_period_in_content = rows[0][3].strip() if rows[0][3] else "未知期间"
                        # content field is index 3 (the big concat), period is actually embedded there
                        # let's just note the time direction
                        fallback_note = (
                            f"[注：{normalized_period} 及之前无该规格数据（该规格在该期间尚未收录），"
                            f"已返回最早有记录的数据供参考]"
                        )
                    else:
                        fallback_note = f"[注：{normalized_period} 及前后期间均无此规格数据]"
                else:
                    fallback_note = f"[注：{normalized_period} 无数据，已回退至最近期间 {fallback_period}]"
                logger.info(f"[price_query] period fallback {normalized_period} → note: {fallback_note[:60]}")

        results = []
        for row in rows:
            chunk = _chunk_from_pg_row(row, "price_records", 0.85)
            if fallback_note:
                chunk["content"] = fallback_note + " " + chunk["content"]
            results.append(chunk)

        logger.info(f"[price_query] material='{material_name}' spec='{specification}' period='{normalized_period}' hits={len(results[:top_k])}")
        return json.dumps(results[:top_k], ensure_ascii=False)
    except Exception as e:
        logger.error(f"[price_query] error: {e}")
        return json.dumps([])


# ── calculator（精度强化版）─────────────────────────────────────────────────


@tool
def calculator(expression: str) -> str:
    """计算器：执行数学表达式，支持基础运算和常见函数"""
    try:
        import sympy
        result = sympy.sympify(expression)
        return str(result.evalf())
    except Exception:
        allowed_names = {"abs": abs, "round": round, "max": max, "min": min, "sum": sum}
        try:
            result = eval(expression, {"__builtins__": {}}, allowed_names)
            return str(result)
        except Exception as e:
            return f"[计算错误: {e}]"


# ── python_eval（沙箱计算，带数值注入）───────────────────────────────────────


def _extract_numbers_from_chunks(chunks: list[dict]) -> dict:
    """从 chunk 内容提取数值实体，作为计算基数注入沙箱"""
    numbers = {}
    # 匹配：名称 + 数值 + 单位（常见工程造价单位）
    pattern = r"([\u4e00-\u9fa5\w]+)\s*[:：]\s*(\d+\.?\d*)\s*(元|%|万|工日|kg|t|m³|m²|m|个|套|组|台|块|片|支|根|卷|桶|箱|件|立方米|平方米|吨|千克|公斤|mm|cm|dm)"
    for chunk in chunks:
        content = chunk.get("content", "")
        for m in re.finditer(pattern, content):
            name = m.group(1).strip()
            value = float(m.group(2))
            numbers[name] = value
    return numbers


@tool
def python_eval(code: str, chunks_json: str = "") -> str:
    """Python 代码执行器：在安全沙箱中运行 Python 代码，适合复杂造价计算。

    支持功能：
    - 四则运算、百分比计算、条件判断、循环汇总
    - Decimal 精确计算（已内置，不需要 import）
    - 中文变量名（如 人工费 = 5000000）
    - 多步计算和中间变量

    使用规则：
    - 用 result = ... 返回最终结果，或用 print() 输出
    - 不能 import 任何模块（Decimal 等常用功能已内置）
    - 不能访问文件、网络

    示例：
    - 简单费率: result = 5000000 * 0.035
    - 精确计算: result = Decimal('5000000') * Decimal('0.035')
    - 条件取费:
        if amount > 5000000:
            rate = Decimal('0.035')
        else:
            rate = Decimal('0.04')
        result = amount * rate
    - 多项汇总:
        items = {'企业管理费': 175000, '利润': 200000, '规费': 85000}
        result = f"合计: {sum(items.values())}元"
    """
    try:
        from infrastructure.sandbox import execute_python

        # Phase E: 如果提供了 chunks，注入提取的数值变量
        injected_prefix = ""
        if chunks_json:
            try:
                chunks = json.loads(chunks_json)
                if isinstance(chunks, list) and chunks:
                    extracted = _extract_numbers_from_chunks(chunks)
                    if extracted:
                        injected_lines = [f"{k} = {v}" for k, v in extracted.items()]
                        injected_prefix = "# 从检索结果提取的数值\n" + "\n".join(injected_lines) + "\n\n"
            except Exception:
                pass

        full_code = injected_prefix + code if injected_prefix else code
        output = execute_python(full_code)

        if output["status"] == "success":
            result_text = output.get("result", "")
            printed = output.get("output", "").strip()
            if printed:
                return f"计算结果: {result_text}\n输出:\n{printed}"
            return f"计算结果: {result_text}"
        else:
            error = output.get("error", "未知错误")
            return f"[代码执行失败: {error}]"

    except Exception as e:
        logger.error(f"[python_eval] error: {e}")
        return f"[沙箱调用失败: {e}]"
