"""
Agent 工具集 — PG + pgvector 唯一数据库
保留工具名兼容旧代码，内部全部改为 PostgreSQL 实现
"""

import os
import logging
import json
import re
import threading as _threading
from typing import List
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# ── PG 连接池（模块级单例，防止每次工具调用新建连接）────────────────────────
import psycopg2
from psycopg2 import pool as _pg_pool_mod

PG_CONFIG = {
    "host": os.environ.get("PG_HOST", "localhost"),
    "port": int(os.environ.get("PG_PORT", "5432")),
    "dbname": os.environ.get("PG_DB", "rag_db"),
    "user": os.environ.get("PG_USER", "rag_user"),
    "password": os.environ.get("POSTGRES_PASSWORD") or os.environ.get("PG_PASSWORD") or "",
    "connect_timeout": 5,
}

_pool_lock = _threading.Lock()
_pg_pool: _pg_pool_mod.ThreadedConnectionPool | None = None


def _get_pool() -> _pg_pool_mod.ThreadedConnectionPool:
    """Lazy-init connection pool (minconn=1, maxconn=10)."""
    global _pg_pool
    if _pg_pool is not None:
        return _pg_pool
    with _pool_lock:
        if _pg_pool is None:
            _pg_pool = _pg_pool_mod.ThreadedConnectionPool(1, 10, **PG_CONFIG)
            logger.info("[pg_pool] initialized (maxconn=10)")
    return _pg_pool


def _get_pg_conn() -> psycopg2.extensions.connection:
    """Borrow a connection from the pool. Caller MUST call _put_pg_conn() in finally."""
    return _get_pool().getconn()


def _put_pg_conn(conn: psycopg2.extensions.connection, error: bool = False) -> None:
    """Return a connection to the pool."""
    try:
        _get_pool().putconn(conn, close=error)
    except Exception as e:
        logger.warning(f"[pg_pool] putconn failed: {e}")


# ── 模块级 embedding 单例（GPU 优先，启动时加载一次）────────────────────────
_embedding_svc = None
_embedding_lock = _threading.Lock()
_ocr_path_cache_lock = _threading.Lock()
_ocr_month_file_cache: dict[str, str | None] = {}


def _get_embedding_svc():
    global _embedding_svc
    if _embedding_svc is not None:
        return _embedding_svc
    with _embedding_lock:
        if _embedding_svc is not None:  # double-checked locking
            return _embedding_svc
        from infrastructure.embedding_service import EmbeddingService
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        try:
            _embedding_svc = EmbeddingService(device=device, use_mock=False)
            logger.info(f"[embedding] singleton loaded on {device}")
        except Exception as e:
            logger.warning(f"[embedding] load failed ({e}), falling back to mock")
            _embedding_svc = EmbeddingService(use_mock=True)
    return _embedding_svc


def _get_embedding(text: str) -> List[float]:
    """向量化单条文本，复用模块级 GPU 单例"""
    try:
        return _get_embedding_svc().encode_single(text)
    except Exception as e:
        logger.warning(f"Embedding failed: {e}")
        return []


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


_STRUCTURED_TABLE_QUERY_HINTS = (
    "费率",
    "推荐费率",
    "推荐系数",
    "费率标准",
    "企业管理费",
    "利润率",
    "安全文明施工费",
    "赶工措施费",
    "总包管理服务费",
    "计算基数",
)

_FEE_FORMULA_HINT_RE = re.compile(r"计算方法|计算公式|计算规则|公式|怎么计算|如何计算")
_FEE_STANDARD_YEAR_RE = re.compile(r"(20\d{2})\s*版?")
_FEE_ITEM_RE = re.compile(
    r"企业管理费|安全文明施工费费率部分|安全文明施工费|履约担保手续费|夜间施工增加费|"
    r"总包管理服务费及发包人供应材料（设备）保管费|总包管理服务费|发包人供应材料（设备）保管费|"
    r"暂列金额|优质优价奖励费|利润"
)


def _should_include_structured_tables(query: str) -> bool:
    normalized = (query or "").strip()
    if not normalized:
        return False
    return any(hint in normalized for hint in _STRUCTURED_TABLE_QUERY_HINTS)


def _extract_requested_standard_year(query: str) -> str:
    match = _FEE_STANDARD_YEAR_RE.search(query or "")
    return match.group(1) if match else ""


def _is_fee_formula_query(query: str) -> bool:
    normalized = (query or "").strip()
    return bool(_should_include_structured_tables(normalized) and _FEE_FORMULA_HINT_RE.search(normalized))


def _extract_fee_formula_item(query: str) -> str:
    match = _FEE_ITEM_RE.search(query or "")
    return match.group(0) if match else ""


def _query_fee_formula_text_chunks(conn, query: str, top_k: int = 10) -> list[dict]:
    if not _is_fee_formula_query(query):
        return []

    year = _extract_requested_standard_year(query)
    item = _extract_fee_formula_item(query)
    file_like = f"%费率标准（{year}）%" if year else "%费率标准%"
    content_terms = ["%计算公式%"]
    if item:
        content_terms.append(f"%{item}%")

    results: list[dict] = []
    seen_ids: set[str] = set()
    with conn.cursor() as cur:
        if len(content_terms) >= 2:
            cur.execute(
                """
                    SELECT id, doc_id, page_number, content
                    FROM text_chunks
                    WHERE file_name ILIKE %s
                      AND content ILIKE %s
                      AND content ILIKE %s
                    ORDER BY
                      CASE WHEN content ILIKE %s THEN 0 ELSE 1 END,
                      page_number ASC
                    LIMIT %s
                """,
                (file_like, content_terms[0], content_terms[1], "%计算公式如下%", top_k),
            )
        else:
            cur.execute(
                """
                    SELECT id, doc_id, page_number, content
                    FROM text_chunks
                    WHERE file_name ILIKE %s
                      AND content ILIKE %s
                    ORDER BY
                      CASE WHEN content ILIKE %s THEN 0 ELSE 1 END,
                      page_number ASC
                    LIMIT %s
                """,
                (file_like, content_terms[0], "%计算公式如下%", top_k),
            )

        for row in cur.fetchall():
            cid = f"fee_formula_{row[0]}"
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            results.append(
                {
                    "chunk_id": cid,
                    "doc_id": str(row[1] or ""),
                    "page_number": row[2] or 1,
                    "source_db": "fee_formula_text",
                    "content": row[3] or "",
                    "score": 0.97,
                    "metadata": {},
                }
            )

        if not results and item:
            cur.execute(
                """
                    SELECT id, doc_id, page_number, content
                    FROM text_chunks
                    WHERE file_name ILIKE %s
                      AND content ILIKE %s
                    ORDER BY page_number ASC
                    LIMIT %s
                """,
                (file_like, f"%{item}%", top_k),
            )
            for row in cur.fetchall():
                cid = f"fee_formula_{row[0]}"
                if cid in seen_ids:
                    continue
                seen_ids.add(cid)
                results.append(
                    {
                        "chunk_id": cid,
                        "doc_id": str(row[1] or ""),
                        "page_number": row[2] or 1,
                        "source_db": "fee_formula_text",
                        "content": row[3] or "",
                        "score": 0.93,
                        "metadata": {},
                    }
                )

    return results[:top_k]


def _query_text_chunks_literal(conn, query: str, top_k: int = 10) -> list[dict]:
    if not query.strip():
        return []

    with conn.cursor() as cur:
        cur.execute(
            """
                SELECT id, doc_id, page_number, content
                FROM text_chunks
                WHERE content ILIKE %s
                ORDER BY length(content)
                LIMIT %s
            """,
            (f"%{query.strip()}%", top_k),
        )
        rows = cur.fetchall()

    return [
        {
            "chunk_id": f"tc_{row[0]}",
            "doc_id": str(row[1] or ""),
            "page_number": row[2] or 1,
            "source_db": "literal_text",
            "content": row[3] or "",
            "score": 0.72,
            "metadata": {},
        }
        for row in rows
    ]


def _normalize_year_month(year_month: str) -> str:
    ym = (year_month or "").strip()
    if not ym:
        return ""
    m = re.match(r"(\d{4})[年\-/](\d{1,2})月?$", ym)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    if re.match(r"^\d{6}$", ym):
        return f"{ym[:4]}-{ym[4:]}"
    if re.match(r"^\d{4}-\d{2}$", ym):
        return ym
    return ym


def _is_year_only_period(period: str) -> bool:
    return bool(re.match(r"^\d{4}$", (period or "").strip()))


def _iter_months(start_month: str, end_month: str) -> list[str]:
    start = _normalize_year_month(start_month)
    end = _normalize_year_month(end_month) if end_month else start
    if not start:
        return []
    if not end:
        return [start]

    sy, sm = [int(x) for x in start.split("-", 1)]
    ey, em = [int(x) for x in end.split("-", 1)]
    months: list[str] = []
    year, month = sy, sm
    while (year, month) <= (ey, em):
        months.append(f"{year:04d}-{month:02d}")
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    return months


def _get_month_ocr_json_path(year_month: str) -> str | None:
    normalized = _normalize_year_month(year_month)
    if not normalized:
        return None

    if normalized in _ocr_month_file_cache:
        return _ocr_month_file_cache[normalized]

    repo_root = Path(__file__).resolve().parents[5]
    search_roots = [
        repo_root / "data/knowledge_base/documents",
        repo_root / "archive/reference",
    ]

    with _ocr_path_cache_lock:
        if normalized in _ocr_month_file_cache:
            return _ocr_month_file_cache[normalized]

        found: str | None = None
        pattern = f"**/{normalized}_ocr.json"
        for root in search_roots:
            if not root.exists():
                continue
            matches = sorted(
                root.glob(pattern),
                key=lambda path: path.stat().st_size if path.exists() else -1,
                reverse=True,
            )
            if matches:
                found = str(matches[0])
                break

        _ocr_month_file_cache[normalized] = found
        return found


def _normalize_material_unit(material_name: str, unit: str) -> str:
    normalized = (unit or "").strip().replace("㎡", "m²").replace("?", "")
    if normalized in {"m", "m²"} and material_name in {"中砂", "碎石", "石粉渣"}:
        return "m³"
    if not normalized and material_name == "中砂":
        return "m³"
    return normalized


def _extract_material_price_from_ocr_page(raw_text: str, material_name: str) -> tuple[str, str] | None:
    if not raw_text or material_name not in raw_text:
        return None

    match = re.search(
        rf"{re.escape(material_name)}\s*\n(?P<unit>[A-Za-z0-9㎡mM\?³²/\"]{{1,8}})\s*\n(?P<price>\d+\.\d{{2}})",
        raw_text,
    )
    if match:
        unit = _normalize_material_unit(material_name, match.group("unit"))
        return unit, match.group("price")
    return None


def _query_material_ocr_fallback(material_name: str, year_month: str) -> list[dict]:
    normalized = _normalize_year_month(year_month)
    if not normalized or not material_name.strip():
        return []

    primary_path = _get_month_ocr_json_path(normalized)
    candidate_paths = [primary_path] if primary_path else []
    if primary_path:
        repo_root = Path(__file__).resolve().parents[5]
        extra_candidates = sorted(
            (repo_root / "data/knowledge_base/documents").glob(f"**/{normalized}_ocr.json"),
            key=lambda path: path.stat().st_size if path.exists() else -1,
            reverse=True,
        )
        for candidate in extra_candidates:
            candidate_str = str(candidate)
            if candidate_str not in candidate_paths:
                candidate_paths.append(candidate_str)

    results: list[dict] = []
    for ocr_path in candidate_paths:
        try:
            data = json.loads(Path(ocr_path).read_text())
        except Exception as e:
            logger.warning(f"[ocr_fallback] failed to read {ocr_path}: {e}")
            continue

        doc_id = data.get("document_id", "")
        file_name = data.get("file_name", f"{normalized}.pdf")
        for page in data.get("pages", []):
            parsed = _extract_material_price_from_ocr_page(page.get("raw_text", "") or "", material_name)
            if not parsed:
                continue
            unit, price = parsed
            results.append(
                {
                    "chunk_id": f"ocr_price_{doc_id}_{page.get('page_number', 1)}_{material_name}",
                    "doc_id": doc_id,
                    "page_number": page.get("page_number", 1),
                    "source_db": "ocr_price_fallback",
                    "content": f"{material_name} 单位:{unit} 价格:{price}元 期间:{normalized}",
                    "score": 0.83,
                    "metadata": {
                        "year_month": normalized,
                        "unit": unit,
                        "price": price,
                        "file_name": file_name,
                    },
                }
            )
            return results

    return results


def _build_price_period_label(year_month: str) -> str:
    normalized = _normalize_year_month(year_month)
    if not normalized:
        return ""
    year, month = normalized.split("-", 1)
    return f"{year}年{int(month)}月价格"


def _build_spec_regex(specification: str) -> str:
    parts = [re.escape(part) for part in re.split(r"\s+", specification.strip()) if part]
    if not parts:
        return ""

    pattern = r"\s*".join(parts)
    pattern = pattern.replace(r"0\.6/1KV", r"0\.6/1[kK]V")
    pattern = pattern.replace(r"0\.6/1kV", r"0\.6/1[kK]V")
    pattern = pattern.replace(r"×", r"\s*[×xX*]\s*")
    pattern = pattern.replace(r"x", r"\s*[×xX*]\s*")
    pattern = pattern.replace(r"X", r"\s*[×xX*]\s*")
    return pattern


def _extract_price_row_from_text_chunk(
    content: str,
    material_name: str,
    specification: str,
) -> tuple[str, str] | None:
    def _compact(text: str) -> str:
        compacted = (text or "").lower()
        compacted = compacted.replace("×", "x").replace("*", "x")
        compacted = re.sub(r"\s+", "", compacted)
        return compacted

    compact_content = _compact(content)
    if not compact_content:
        return None

    spec_key = _compact(specification)
    material_key = _compact(material_name)

    candidates = []
    if material_key:
        candidates.append(f"{material_key}{spec_key}")
    candidates.append(spec_key)

    start = -1
    needle = ""
    for candidate in candidates:
        start = compact_content.find(candidate)
        if start >= 0:
            needle = candidate
            break
    if start < 0:
        return None

    remainder = compact_content[start + len(needle):]
    match = re.match(
        r"(?P<unit>m³|m²|㎡|m|t|kg|个|套|组|台|块|片)?(?P<price>\d+\.\d{2})",
        remainder,
    )
    if not match:
        return None

    unit = match.group("unit") or "m"
    if unit == "㎡":
        unit = "m²"
    price = match.group("price")
    return unit, price


def _query_price_text_fallback(
    conn,
    material_name: str,
    specification: str,
    year_month: str,
    top_k: int = 5,
) -> list[dict]:
    period_label = _build_price_period_label(year_month)
    if not period_label or not specification.strip():
        return []

    year_month_norm = _normalize_year_month(year_month)
    spec_tokens = [
        token
        for token in re.split(r"[^A-Za-z0-9\u4e00-\u9fff]+", specification)
        if token and len(token) >= 2
    ]
    query_terms = [f"%{period_label}%", f"%{material_name or '电力电缆'}%"]
    optional_clauses = []
    optional_params: list[str] = []
    for token in spec_tokens[:3]:
        optional_clauses.append("content ILIKE %s")
        optional_params.append(f"%{token}%")

    where_optional = ""
    if optional_clauses:
        where_optional = " AND (" + " OR ".join(optional_clauses) + ")"

    with conn.cursor() as cur:
        cur.execute(
            f"""
                SELECT DISTINCT doc_id, page_number
                FROM text_chunks
                WHERE content ILIKE %s
                  AND content ILIKE %s
                  {where_optional}
                ORDER BY page_number
                LIMIT %s
            """,
            query_terms + optional_params + [max(top_k * 4, 12)],
        )
        anchor_pages = cur.fetchall()

    results: list[dict] = []
    for doc_id, page_number in anchor_pages:
        with conn.cursor() as cur:
            cur.execute(
                """
                    SELECT id, content
                    FROM text_chunks
                    WHERE doc_id = %s AND page_number = %s
                    ORDER BY id
                """,
                (doc_id, page_number),
            )
            page_rows = cur.fetchall()

        combined_content = " ".join((row[1] or "") for row in page_rows)
        parsed = _extract_price_row_from_text_chunk(
            content=combined_content,
            material_name=material_name or "电力电缆",
            specification=specification,
        )
        if not parsed:
            continue
        unit, price = parsed
        results.append(
            {
                "chunk_id": f"price_text_{doc_id}_{page_number}",
                "doc_id": doc_id or "",
                "page_number": page_number or 1,
                "source_db": "text_price_fallback",
                "content": (
                    f"{material_name or '电力电缆'} {specification} 单位:{unit} "
                    f"价格:{price}元 期间:{year_month_norm}"
                ),
                "score": 0.84,
                "metadata": {
                    "year_month": year_month_norm,
                    "unit": unit,
                    "price": price,
                },
            }
        )
        if len(results) >= top_k:
            break

    return results


def _query_structured_tables(query: str, top_k: int = 10) -> list[dict]:
    """
    查询结构化表（fee_rates 等）并返回 chunk list。
    分数固定为 0.90，不受 SCORE_THRESHOLD 影响。
    供 text_search / keyword_search / category_search / rag_pipeline 复用。

    匹配策略：先整串 ILIKE，若无结果则对 2~8 字中文片段逐一匹配（支持长查询句）。
    """
    results: list[dict] = []
    if not query.strip() or not _should_include_structured_tables(query):
        return results
    q = query.strip()
    requested_year = _extract_requested_standard_year(q)

    # 提取候选匹配词：全串 + 滑动窗口（避免贪婪匹配漏掉关键词）
    import re as _re
    fragments: list[str] = [q]
    for _run in _re.findall(r'[\u4e00-\u9fff]+', q):
        for _len in range(3, 8):
            for _s in range(len(_run) - _len + 1):
                fragments.append(_run[_s:_s + _len])
    seen_fragments: set[str] = set()
    unique_fragments = []
    for f in fragments:
        if f not in seen_fragments:
            seen_fragments.add(f)
            unique_fragments.append(f)

    conn = None
    try:
        conn = _get_pg_conn()
        seen_ids: set[str] = set()
        with conn.cursor() as cur:
            for frag in unique_fragments:
                if len(results) >= top_k:
                    break
                try:
                    if requested_year:
                        cur.execute("""
                            SELECT id, doc_id, fee_name, fee_category,
                                   rate_min, rate_max, rate_recommended,
                                   applicable_scope, base_formula, source_text, standard_year,
                                   calc_base
                            FROM fee_rates
                            WHERE standard_year = %s
                              AND (
                                   fee_name ILIKE %s OR fee_category ILIKE %s
                                   OR source_text ILIKE %s
                              )
                            LIMIT %s
                        """, (requested_year, f"%{frag}%", f"%{frag}%", f"%{frag}%", top_k))
                    else:
                        cur.execute("""
                            SELECT id, doc_id, fee_name, fee_category,
                                   rate_min, rate_max, rate_recommended,
                                   applicable_scope, base_formula, source_text, standard_year,
                                   calc_base
                            FROM fee_rates
                            WHERE fee_name ILIKE %s OR fee_category ILIKE %s
                               OR source_text ILIKE %s
                            LIMIT %s
                        """, (f"%{frag}%", f"%{frag}%", f"%{frag}%", top_k))
                except Exception as _cur_err:
                    import psycopg2
                    if isinstance(_cur_err, psycopg2.errors.UndefinedTable):
                        break  # fee_rates table doesn't exist yet
                    raise
                for fr in cur.fetchall():
                    fid, fdoc_id, fname, fcat, rmin, rmax, rrec, scope, formula, src, yr, cbase = fr
                    cid = f"fr_{fid}"
                    if cid in seen_ids:
                        continue
                    seen_ids.add(cid)
                    rmin_s = f"{float(rmin):.4g}%" if rmin is not None else "—"
                    rmax_s = f"{float(rmax):.4g}%" if rmax is not None else "—"
                    rrec_s = f"{float(rrec):.4g}%" if rrec is not None else "—"
                    # Build clear content with calc_base so LLM knows what to multiply
                    calc_base_note = f"计算基数：{cbase}" if cbase else ""
                    content_text = (
                        f"【{yr}版费率标准】{fname}（{fcat}）\n"
                        f"费率参考范围：{rmin_s}～{rmax_s}，推荐费率：{rrec_s}（单位：%，使用时÷100）\n"
                        f"{calc_base_note}\n"
                        f"计算公式：{formula or ''}\n"
                        f"适用范围：{scope or ''}"
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
    except Exception as e:
        logger.error(f"[_query_structured_tables] fee_rates error: {e}")
    finally:
        if conn is not None:
            _put_pg_conn(conn)
    return results


# ── 新工具：pg_vector_search（PG pgvector）──────────────────────────────────


@tool
def vector_search(query: str, top_k: int = 10) -> str:
    """向量语义搜索：从 text_chunks 表中使用 pgvector 余弦相似度检索"""
    if not query.strip():
        return json.dumps([])

    conn = None
    try:
        query_embedding = _get_embedding(query.strip())
        if not query_embedding:
            return json.dumps([])

        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, doc_id, page_number, content,
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
    finally:
        if conn is not None:
            _put_pg_conn(conn)


# ── 新工具：keyword_search（PG tsvector 全文检索）────────────────────────────


@tool
def keyword_search(query: str, top_k: int = 10) -> str:
    """关键词全文搜索：从 text_chunks 表中使用 PostgreSQL tsvector + ts_rank 检索"""
    if not query.strip():
        return json.dumps([])

    conn = None
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, doc_id, page_number, content,
                       ts_rank(to_tsvector('chinese', content), plainto_tsquery('chinese', %s)) AS score
                FROM text_chunks
                WHERE to_tsvector('chinese', content) @@ plainto_tsquery('chinese', %s)
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

        # also query fee_rates and other structured tables
        for chunk in _query_fee_formula_text_chunks(conn, query, top_k):
            if chunk["chunk_id"] not in {r.get("chunk_id") for r in results}:
                results.append(chunk)
        if _should_include_structured_tables(query):
            results.extend(_query_structured_tables(query, top_k))
        for chunk in _query_text_chunks_literal(conn, query, top_k):
            if chunk["chunk_id"] not in {r.get("chunk_id") for r in results}:
                results.append(chunk)

        return json.dumps(results, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[keyword_search] error: {e}")
        return json.dumps([])
    finally:
        if conn is not None:
            _put_pg_conn(conn)


# ── category_search（目录索引检索）──────────────────────────────────────────


@tool
def category_search(query: str, top_k: int = 5) -> str:
    """目录索引检索：在文档章节目录中搜索材料/工艺所在的章节编号和标题。
    适用场景：当不确定某材料在哪个章节时，先用此工具定位章节，再用 text_search 检索具体数据。
    返回：章节编号、章节标题、页码。
    """
    if not query.strip():
        return json.dumps([])

    conn = None
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            q = query.strip()

            # 策略1：ILIKE 精确字面匹配（中文复合词可靠），限制 < 600 chars，优先带章节号的短块
            cur.execute("""
                SELECT id, doc_id, page_number, content,
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
                    SELECT id, doc_id, page_number, content,
                           length(content) AS char_len
                    FROM text_chunks
                    WHERE content ILIKE %s
                      AND length(content) < 1200
                    ORDER BY length(content)
                    LIMIT %s
                """, (f"%{q}%", top_k))
                rows = cur.fetchall()

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
        for chunk in _query_fee_formula_text_chunks(conn, query, top_k):
            results.append({
                "chunk_id": chunk["chunk_id"],
                "doc_id": chunk["doc_id"],
                "page_number": chunk["page_number"],
                "section": "",
                "content": chunk["content"][:300],
                "score": chunk["score"],
            })
        if _should_include_structured_tables(query):
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
    finally:
        if conn is not None:
            _put_pg_conn(conn)


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

    conn = None
    try:
        query_embedding = _get_embedding(query.strip())
        conn = _get_pg_conn()
        results = []
        seen_ids = set()

        with conn.cursor() as cur:
            # 向量路
            if query_embedding:
                try:
                    cur.execute("""
                        SELECT id, doc_id, page_number, content,
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
                except Exception as e:
                    logger.error(f"[hybrid_search] vector error: {e}")
                    conn.rollback()

            # 全文路
            cur.execute("""
                SELECT id, doc_id, page_number, content,
                       ts_rank(to_tsvector('chinese', content), plainto_tsquery('chinese', %s)) AS score
                FROM text_chunks
                WHERE to_tsvector('chinese', content) @@ plainto_tsquery('chinese', %s)
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

        # fee_rates 结构化表
        for chunk in _query_fee_formula_text_chunks(conn, query, top_k):
            if chunk["chunk_id"] not in seen_ids:
                seen_ids.add(chunk["chunk_id"])
                results.append(chunk)
        if _should_include_structured_tables(query):
            for chunk in _query_structured_tables(query, top_k):
                if chunk["chunk_id"] not in seen_ids:
                    seen_ids.add(chunk["chunk_id"])
                    results.append(chunk)

        for chunk in _query_text_chunks_literal(conn, query, top_k):
            if chunk["chunk_id"] not in seen_ids:
                seen_ids.add(chunk["chunk_id"])
                results.append(chunk)

        # 按分数重排
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return json.dumps(results[:top_k], ensure_ascii=False)
    except Exception as e:
        logger.error(f"[hybrid_search] error: {e}")
        return json.dumps([])
    finally:
        if conn is not None:
            _put_pg_conn(conn)


# ── text_search（PG 语义搜索，保留原名兼容）───────────────────────────────────


@tool
def text_search(query: str, top_k: int = 8) -> str:
    """语义向量搜索+全文检索：从 text_chunks 表中检索"""
    if not query.strip():
        return json.dumps([])

    results = []
    seen_ids = set()
    conn = None
    try:
        conn = _get_pg_conn()

        # 1. Full-text search (to_tsvector)
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, doc_id, page_number, content,
                           ts_rank(to_tsvector('chinese', content), plainto_tsquery('chinese', %s)) AS score
                    FROM text_chunks
                    WHERE to_tsvector('chinese', content) @@ plainto_tsquery('chinese', %s)
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
                        SELECT id, doc_id, page_number, content,
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
            if conn is not None:
                conn.rollback()

        # 3. fee_rates and other structured tables — score 0.9, always passes filter
        for chunk in _query_fee_formula_text_chunks(conn, query, top_k):
            if chunk["chunk_id"] not in seen_ids:
                seen_ids.add(chunk["chunk_id"])
                results.append(chunk)
        if _should_include_structured_tables(query):
            for chunk in _query_structured_tables(query, top_k):
                if chunk["chunk_id"] not in seen_ids:
                    seen_ids.add(chunk["chunk_id"])
                    results.append(chunk)

        for chunk in _query_text_chunks_literal(conn, query, top_k):
            if chunk["chunk_id"] not in seen_ids:
                seen_ids.add(chunk["chunk_id"])
                results.append(chunk)

    except Exception as e:
        logger.error(f"[text_search] error: {e}")
    finally:
        if conn is not None:
            _put_pg_conn(conn)

    results.sort(key=lambda x: x["score"], reverse=True)
    return json.dumps(results[:top_k], ensure_ascii=False)


# ── price_query（PG SQL 精确查询，保留）──────────────────────────────────────


@tool
def price_query(material_name: str = "", specification: str = "", year_month: str = "", top_k: int = 5) -> str:
    """价格精确查询：从 price_records 表中查询建材价格信息。
    year_month 支持多种格式：'2025-12'、'202512'、'2025年12月'、'2025'。
    若指定期间无数据，自动回退到最近有数据的期间。
    """
    conn = None
    try:
        # ── 日期格式标准化 ──────────────────────────────────────────────────
        normalized_period = _normalize_year_month(year_month)

        conn = _get_pg_conn()
        with conn.cursor() as cur:

            def _build_and_run(period_filter: str | None) -> list:
                where_clauses = []
                params: list = []
                if material_name:
                    where_clauses.append(
                        "(material_name ILIKE %s OR specification ILIKE %s OR to_tsvector('chinese', material_name) @@ plainto_tsquery('chinese', %s))"
                    )
                    params.extend([f"%{material_name}%", f"%{material_name}%", material_name])
                if specification:
                    # 兼容乘号变体：× x * X
                    spec_normalized = re.sub(r'[×xX*]', '%', specification)
                    # 提取截面部分（如 "5×120" 从 "0.6/1KV YJV 5×120"）作为更宽松的模糊键
                    _xs_m = re.search(r'(\d+)\s*[×xX*]\s*(\d+)', specification)
                    _xs_key = f"%{_xs_m.group(1)}%{_xs_m.group(2)}%" if _xs_m else f"%{spec_normalized}%"
                    where_clauses.append("(specification ILIKE %s OR specification ILIKE %s OR specification ILIKE %s)")
                    params.extend([f"%{specification}%", f"%{spec_normalized}%", _xs_key])
                if period_filter:
                    if _is_year_only_period(period_filter):
                        where_clauses.append("year_month LIKE %s")
                        params.append(f"{period_filter}-%")
                    else:
                        where_clauses.append("year_month = %s")
                        params.append(period_filter)

                where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
                sql = f"""
                    SELECT id, doc_id, page_number,
                           material_name || ' ' || COALESCE(specification, '') ||
                           ' 单位:' || COALESCE(unit, '') ||
                           ' 价格:' || COALESCE(price_tax_included::text, 'N/A') || '元' ||
                           ' 期间:' || COALESCE(year_month, '') ||
                           ' 类别:' || COALESCE(category, '') AS content,
                           metadata AS metadata,
                           0.0 AS dist
                    FROM price_records
                    {where_sql}
                    ORDER BY year_month DESC, id
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

            text_fallback_results: list[dict] = []
            if not rows and normalized_period and specification and not _is_year_only_period(normalized_period):
                text_fallback_results = _query_price_text_fallback(
                    conn=conn,
                    material_name=material_name,
                    specification=specification,
                    year_month=normalized_period,
                    top_k=top_k,
                )
                if text_fallback_results:
                    logger.info(
                        f"[price_query] text fallback recovered {len(text_fallback_results)} rows "
                        f"for spec='{specification}' period='{normalized_period}'"
                    )
                    return json.dumps(text_fallback_results[:top_k], ensure_ascii=False)
            if (
                not rows
                and normalized_period
                and material_name
                and not specification
                and not _is_year_only_period(normalized_period)
            ):
                ocr_fallback_results = _query_material_ocr_fallback(material_name, normalized_period)
                if ocr_fallback_results:
                    logger.info(
                        f"[price_query] ocr fallback recovered {len(ocr_fallback_results)} rows "
                        f"for material='{material_name}' period='{normalized_period}'"
                    )
                    return json.dumps(ocr_fallback_results[:top_k], ensure_ascii=False)

            # 若指定了期间但无结果，查询最近有数据的期间并附注
            fallback_note = ""
            if normalized_period and not rows and not _is_year_only_period(normalized_period):
                cur.execute(
                    "SELECT DISTINCT year_month FROM price_records ORDER BY year_month DESC LIMIT 30"
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
                        where_clauses2.append("(material_name ILIKE %s OR to_tsvector('chinese', material_name) @@ plainto_tsquery('chinese', %s))")
                        params2.extend([f"%{material_name}%", material_name])
                    if specification:
                        spec_norm2 = re.sub(r'[×xX*]', '%', specification)
                        _xs_m2 = re.search(r'(\d+)\s*[×xX*]\s*(\d+)', specification)
                        _xs_key2 = f"%{_xs_m2.group(1)}%{_xs_m2.group(2)}%" if _xs_m2 else f"%{spec_norm2}%"
                        where_clauses2.append("(specification ILIKE %s OR specification ILIKE %s OR specification ILIKE %s)")
                        params2.extend([f"%{specification}%", f"%{spec_norm2}%", _xs_key2])
                    if normalized_period:
                        where_clauses2.append("year_month > %s")
                        params2.append(normalized_period)
                    where_sql2 = ("WHERE " + " AND ".join(where_clauses2)) if where_clauses2 else ""
                    sql2 = f"""
                        SELECT id, doc_id, page_number,
                               material_name || ' ' || COALESCE(specification, '') ||
                               ' 单位:' || COALESCE(unit, '') ||
                               ' 价格:' || COALESCE(price_tax_included::text, 'N/A') || '元' ||
                               ' 期间:' || COALESCE(year_month, '') ||
                               ' 类别:' || COALESCE(category, '') AS content,
                               metadata AS metadata,
                               0.0 AS dist
                        FROM price_records
                        {where_sql2}
                        ORDER BY year_month ASC, id
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
    finally:
        if conn is not None:
            _put_pg_conn(conn)


# ── price_trend（时序价格走势）──────────────────────────────────────────────


@tool
def price_trend(material_name: str, start_month: str = "", end_month: str = "") -> str:
    """时序价格走势查询：返回某材料在指定时间范围内的月度均价列表，适合分析价格趋势和同比/环比变化。
    start_month / end_month 格式为 'YYYY-MM'（如 '2025-01'）。
    返回按 year_month 升序排列的 JSON 列表，每条包含 year_month、avg_price、unit、specification。
    """
    conn = None
    try:
        conn = _get_pg_conn()
        where_parts: list[str] = []
        params: list = [f"%{material_name}%", f"%{material_name}%", material_name]
        where_parts.append(
            "(material_name ILIKE %s OR specification ILIKE %s "
            "OR to_tsvector('chinese', material_name) @@ plainto_tsquery('chinese', %s))"
        )
        if start_month:
            where_parts.append("year_month >= %s")
            params.append(start_month)
        if end_month:
            where_parts.append("year_month <= %s")
            params.append(end_month)
        where_sql = "WHERE " + " AND ".join(where_parts)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT year_month,
                       AVG(price_tax_included)::numeric(10,2) AS avg_price,
                       MAX(unit)          AS unit,
                       MAX(specification) AS specification
                FROM price_records
                {where_sql}
                GROUP BY year_month
                ORDER BY year_month ASC
                LIMIT 48
                """,
                params,
            )
            rows = cur.fetchall()

        # Fallback: compound Chinese names (e.g. "装配式混凝土预制构件") won't match
        # individual items like "预制混凝土楼板" via substring or AND-based FTS.
        # Extract non-overlapping 2-char bigrams and retry with OR ILIKE.
        if not rows and len(material_name) >= 4:
            bigrams = list({material_name[i:i+2] for i in range(0, len(material_name) - 1, 2)
                           if len(material_name[i:i+2]) == 2})
            if bigrams:
                or_sql = " OR ".join(["material_name ILIKE %s"] * len(bigrams))
                fb_params: list = [f"%{b}%" for b in bigrams]
                fb_where_parts = [f"({or_sql})"]
                if start_month:
                    fb_where_parts.append("year_month >= %s")
                    fb_params.append(start_month)
                if end_month:
                    fb_where_parts.append("year_month <= %s")
                    fb_params.append(end_month)
                fb_where_parts.append("price_tax_included IS NOT NULL")
                fb_where = "WHERE " + " AND ".join(fb_where_parts)
                with conn.cursor() as cur2:
                    cur2.execute(
                        f"""
                        SELECT year_month,
                               AVG(price_tax_included)::numeric(10,2) AS avg_price,
                               MAX(unit) AS unit,
                               MAX(material_name) AS material_name
                        FROM price_records
                        {fb_where}
                        GROUP BY year_month
                        ORDER BY year_month ASC
                        LIMIT 48
                        """,
                        fb_params,
                    )
                    rows = cur2.fetchall()
                logger.info(f"[price_trend] bigram fallback bigrams={bigrams} hits={len(rows)}")

        existing_months = {str(r[0]) for r in rows}
        ocr_rows: list[tuple[str, float, str, str, int, str]] = []
        months_to_fill = [month for month in _iter_months(start_month, end_month) if month not in existing_months]
        for month in months_to_fill:
            fallback_rows = _query_material_ocr_fallback(material_name, month)
            if not fallback_rows:
                continue
            for row in fallback_rows:
                ocr_rows.append(
                    (
                        row["metadata"]["year_month"],
                        float(row["metadata"]["price"]),
                        row["metadata"]["unit"],
                        material_name,
                        row["page_number"],
                        row["doc_id"],
                    )
                )

        # 返回 chunk 格式，以便 _collect_chunks 可以处理并传递给 synthesizer
        chunks = []
        for r in rows:
            avg = float(r[1] or 0)
            unit = r[2] or ""
            spec = r[3] or ""
            content = (
                f"{material_name} 价格走势 "
                f"期间:{r[0]} "
                f"均价:{avg:.2f}元/{unit} "
                + (f"规格:{spec} " if spec else "")
            )
            chunks.append({
                "chunk_id": f"price_trend_{material_name}_{r[0]}",
                "doc_id": "price_trend",
                "page_number": 1,
                "source_db": "price_records",
                "content": content,
                "score": 0.85,
                "metadata": {"year_month": r[0], "avg_price": avg, "unit": unit},
            })
        for year_month, avg_price, unit, spec, page_number, doc_id in sorted(ocr_rows, key=lambda x: x[0]):
            content = (
                f"{material_name} 价格走势 "
                f"期间:{year_month} "
                f"均价:{avg_price:.2f}元/{unit} "
                + (f"规格:{spec} " if spec else "")
            )
            chunks.append({
                "chunk_id": f"price_trend_ocr_{material_name}_{year_month}",
                "doc_id": doc_id or "",
                "page_number": page_number or 1,
                "source_db": "ocr_price_fallback",
                "content": content,
                "score": 0.82,
                "metadata": {"year_month": year_month, "avg_price": avg_price, "unit": unit},
            })
        chunks.sort(key=lambda chunk: chunk["metadata"].get("year_month", ""))
        logger.info(
            f"[price_trend] material='{material_name}' "
            f"range=[{start_month},{end_month}] points={len(chunks)}"
        )
        return json.dumps(chunks, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[price_trend] error: {e}")
        return json.dumps([])
    finally:
        if conn is not None:
            _put_pg_conn(conn)


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
