"""
Agent 工具集 — PG + pgvector 唯一数据库
保留工具名兼容旧代码，内部全部改为 PostgreSQL 实现
"""

import os
import logging
import json
import re
import time
import uuid
import asyncio
import threading as _threading
from datetime import datetime
from typing import List
from pathlib import Path

import numpy as np

from app.agent.query_analyzer import (
    QueryAnalyzer,
    extract_appendix_standard_terms,
    extract_appendix_standard_title,
    extract_fee_standard_comparison_queries,
    extract_fill_requirement_search_term,
    is_appendix_standard_query,
    is_fee_standard_comparison_query,
    is_fill_requirement_query,
)

from langchain_core.tools import tool
from config.loader import RAGConfig as AppConfig  # Issue #122: AppConfig → RAGConfig (unified loader)
from infrastructure.vector_store import create_vector_store_adapter
from app.runtime_config import postgres_connection_kwargs, read_runtime_config
from app.runtime_overrides import get_runtime_override

# Phase 1: Import RetrievalPresets for unified top_k (#116)
import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from config.retrieval_presets import RetrievalPresets

logger = logging.getLogger(__name__)

RETRIEVAL_PATH_DATABASE = "database"
RETRIEVAL_PATH_VECTOR = "vector"
RETRIEVAL_PATH_GRAPH = "graph"
RETRIEVAL_PATH_TOPOLOGY = "topology"
RETRIEVAL_PATH_OCR_JSON = "ocr_json"
RETRIEVAL_PATH_PDF_PAGE = "pdf_page"

# ── PG 连接池（模块级单例，防止每次工具调用新建连接）────────────────────────
import psycopg2
from psycopg2 import pool as _pg_pool_mod

_pool_lock = _threading.Lock()
_pg_pool: _pg_pool_mod.ThreadedConnectionPool | None = None


def _get_pool() -> _pg_pool_mod.ThreadedConnectionPool:
    """Lazy-init connection pool (minconn=1, maxconn=10)."""
    global _pg_pool
    if _pg_pool is not None:
        return _pg_pool
    with _pool_lock:
        if _pg_pool is None:
            _pg_pool = _pg_pool_mod.ThreadedConnectionPool(1, 10, **postgres_connection_kwargs())
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
_TSV_CONFIG_NAME: str | None = None
_TSV_CONFIG_LOCK = _threading.Lock()

# ---------------------------------------------------------------------------
# Chinese industry abbreviation expansion
# 砼 (tóng) is the construction industry shorthand for 混凝土 (concrete).
# Expanding before BM25/trgm search closes the character-level vocabulary gap.
# ---------------------------------------------------------------------------
# ── 统一建筑行业别名映射 ──────────────────────────────────────────────────
# 权威来源：canonical_concepts 表 aliases 字段（启动时可增量加载）。
# 两个文件中的副本需保持同步：
#   - 本文件 _ABBREV_EXPAND（BM25/trgm 查询扩展）
#   - query_analyzer.py _MATERIAL_NORMALIZE（实体抽取规范化）
# ──────────────────────────────────────────────────────────────────────────
_ABBREV_EXPAND: dict[str, str] = {
    # ── 混凝土 / 砼 ──
    "砼": "混凝土",
    "钢砼": "钢筋混凝土",
    "防渗砼": "防水混凝土",
    "抗渗砼": "防水混凝土",
    "防水砼": "防水混凝土",
    "防渗混凝土": "防水混凝土",
    "抗渗混凝土": "防水混凝土",
    "豆石砼": "豆石混凝土",
    "细石砼": "细石混凝土",
    # ── 沥青 ──
    "热拌沥青混合料": "沥青混凝土",
    "沥青混合料": "沥青混凝土",
    "沥青砼": "沥青混凝土",
    "AC混合料": "沥青混凝土",
    "沥青路面料": "沥青混凝土",
    "热拌料": "沥青混凝土",
    # ── 电线电缆 ──
    "绝缘导线": "绝缘电线",
    "BV导线": "绝缘电线",
    "铜芯绝缘线": "绝缘电线",
    "铜芯塑料线": "绝缘电线",
    "高压导线": "电力电缆",
    "输电电缆": "电力电缆",
    "动力电缆": "电力电缆",
    "弱电线缆": "控制电缆",
    "仪表电缆": "控制电缆",
    # ── 模板 ──
    "模板支拆": "模板制安",
    "木模安装": "模板制安",
    "模板工": "模板制安",
    "木工": "木模板",
}


_canonical_aliases_loaded = False


def _load_aliases_from_canonical_concepts() -> int:
    """从 canonical_concepts 表加载别名到 _ABBREV_EXPAND（启动时调用）。
    返回新加载的别名数量。"""
    global _canonical_aliases_loaded
    if _canonical_aliases_loaded:
        return 0
    try:
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT aliases, normalized_name FROM canonical_concepts "
                    "WHERE aliases IS NOT NULL AND array_length(aliases, 1) > 0"
                )
                rows = cur.fetchall()
        finally:
            _put_pg_conn(conn)
        added = 0
        for row in rows:
            aliases = row[0] or []
            canonical = (row[1] or "").strip()
            if not canonical:
                continue
            for alias in aliases:
                alias = alias.strip()
                if alias and alias != canonical and alias not in _ABBREV_EXPAND:
                    _ABBREV_EXPAND[alias] = canonical
                    added += 1
        _canonical_aliases_loaded = True
        if added:
            logger.info("[alias_loader] loaded %d aliases from canonical_concepts (total=%d)", added, len(_ABBREV_EXPAND))
        return added
    except Exception as e:
        logger.warning("[alias_loader] failed to load canonical_concepts aliases: %s", e)
        _canonical_aliases_loaded = True  # don't retry on failure
        return 0


def _expand_query_variants(query: str) -> list[str]:
    """Return [query] plus versions with industry abbreviations expanded."""
    _load_aliases_from_canonical_concepts()
    variants = [query]
    for abbrev, full in _ABBREV_EXPAND.items():
        if abbrev in query:
            variants.append(query.replace(abbrev, full))
    return variants


# ── 数据质量：垃圾材料名过滤 ─────────────────────────────────────────────
# OCR 管道有时将表格标题、单位行、页脚等误识别为 material_name。
# 这些模式匹配已知的噪声行，在 SQL 层面用 WHERE 子句排除。
_GARBAGE_MATERIAL_PATTERNS = [
    r"^\d+\.?\d*$",                  # pure number like "0.040", "0.030"
    r"元$",                           # ends with 元 (monetary measure word)
    r"^(kg|台班|t|m²|m³|m|套|个)$",   # bare units
    r"^(机械费|材料费|人工费|管理费|利润|规费|税金|安全文明).*元$",  # fee line
    r"^(一|二|三|四|五|六|七|八|九|十)\s*[一|\s]*$",  # Chinese numeral only
    r"^[一二三四五六七八九十、.\s]+$",  # pure Chinese numerals
]

_GARBAGE_MATERIAL_RE = re.compile("|".join(_GARBAGE_MATERIAL_PATTERNS))

_GARBAGE_SQL_CLAUSE = """
    AND material_name !~ '^\\d+\\.?\\d*$'
    AND material_name !~ '元$'
    AND material_name !~ '^(kg|台班|t|m²|m³|m|套|个)$'
    AND material_name !~ '^(机械费|材料费|人工费|管理费|利润|规费|税金|安全文明).*元$'
"""


def _is_garbage_material(name: str) -> bool:
    """检查 material_name 是否是 OCR 噪声"""
    return bool(_GARBAGE_MATERIAL_RE.match(name.strip())) if name else True


# ── 标准查询接口（供合约验证和 corrective_action 使用）─────────────────

def get_latest_year_month_for_material(material_name: str) -> str:
    """返回某材料的最新有效数据期次。无结果返回空字符串。"""
    if not material_name or _is_garbage_material(material_name):
        return ""
    try:
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT year_month FROM price_records "
                    "WHERE material_name ILIKE %s "
                    "  AND price_tax_included IS NOT NULL "
                    "  AND year_month IS NOT NULL AND year_month != '' "
                    + _GARBAGE_SQL_CLAUSE +
                    " ORDER BY year_month DESC LIMIT 1",
                    (f"%{material_name}%",),
                )
                row = cur.fetchone()
                return str(row[0]) if row and row[0] else ""
        finally:
            _put_pg_conn(conn)
    except Exception as e:
        logger.warning("[db] get_latest_year_month_for_material failed: %s", e)
        return ""


def get_most_common_spec(material_name: str, year_month: str = "") -> str:
    """返回某材料最常用的规格。可选用期间过滤。无结果返回空字符串。"""
    if not material_name or _is_garbage_material(material_name):
        return ""
    try:
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                clauses = [
                    "material_name ILIKE %s",
                    "price_tax_included IS NOT NULL",
                    "specification IS NOT NULL AND specification != ''",
                ]
                params: list = [f"%{material_name}%"]
                if year_month:
                    clauses.append("year_month = %s")
                    params.append(year_month)
                cur.execute(
                    "SELECT specification, count(*) AS n FROM price_records "
                    "WHERE " + " AND ".join(clauses) + " "
                    + _GARBAGE_SQL_CLAUSE +
                    " GROUP BY specification ORDER BY n DESC LIMIT 1",
                    params,
                )
                row = cur.fetchone()
                return str(row[0]) if row and row[0] else ""
        finally:
            _put_pg_conn(conn)
    except Exception as e:
        logger.warning("[db] get_most_common_spec failed: %s", e)
        return ""


def get_price_cv(material_name: str, year_month: str) -> float | None:
    """返回某材料某期多源价格的变异系数（CV=std/mean）。单源返回 None。"""
    if not material_name or not year_month:
        return None
    try:
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT price_tax_included FROM price_records "
                    "WHERE material_name ILIKE %s AND year_month = %s "
                    "  AND price_tax_included IS NOT NULL "
                    + _GARBAGE_SQL_CLAUSE,
                    (f"%{material_name}%", year_month),
                )
                prices = [float(r[0]) for r in cur.fetchall()]
        finally:
            _put_pg_conn(conn)
        if len(prices) < 2:
            return None
        mean = sum(prices) / len(prices)
        std = (sum((p - mean) ** 2 for p in prices) / len(prices)) ** 0.5
        return float(std / mean) if mean > 0 else None
    except Exception as e:
        logger.warning("[db] get_price_cv failed: %s", e)
        return None


def get_material_price_range(material_name: str, year_month: str = "") -> dict:
    """返回某材料的 min/mean/max 价格及来源数。"""
    result = {"min": None, "mean": None, "max": None, "count": 0}
    if not material_name:
        return result
    try:
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                clauses = [
                    "material_name ILIKE %s",
                    "price_tax_included IS NOT NULL",
                ]
                params: list = [f"%{material_name}%"]
                if year_month:
                    clauses.append("year_month = %s")
                    params.append(year_month)
                cur.execute(
                    "SELECT min(price_tax_included), avg(price_tax_included), "
                    "max(price_tax_included), count(*) FROM price_records "
                    "WHERE " + " AND ".join(clauses) + " "
                    + _GARBAGE_SQL_CLAUSE,
                    params,
                )
                row = cur.fetchone()
        finally:
            _put_pg_conn(conn)
        if row and row[3] > 0:
            return {
                "min": float(row[0]) if row[0] else None,
                "mean": round(float(row[1]), 2) if row[1] else None,
                "max": float(row[2]) if row[2] else None,
                "count": int(row[3]),
            }
        return result
    except Exception as e:
        logger.warning("[db] get_material_price_range failed: %s", e)
        return result


def count_valid_price_records(material_name: str) -> int:
    """返回某材料的有效价格记录数（有价格+规格+期间）。"""
    if not material_name:
        return 0
    try:
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM price_records "
                    "WHERE material_name ILIKE %s "
                    "  AND price_tax_included IS NOT NULL "
                    "  AND specification IS NOT NULL AND specification != '' "
                    "  AND year_month IS NOT NULL AND year_month != '' "
                    + _GARBAGE_SQL_CLAUSE,
                    (f"%{material_name}%",),
                )
                row = cur.fetchone()
                return int(row[0]) if row else 0
        finally:
            _put_pg_conn(conn)
    except Exception as e:
        logger.warning("[db] count_valid_price_records failed: %s", e)
        return 0


def _get_hybrid_runtime_config(top_k: int) -> dict:
    runtime = read_runtime_config()
    requested_top_k = max(1, int(top_k))
    normalized_top_k = int(get_runtime_override("top_k", requested_top_k))
    vector_fetch_multiplier = max(1, int(runtime.hybrid_vector_fetch_multiplier))
    text_fetch_multiplier = max(1, int(runtime.hybrid_text_fetch_multiplier))
    structured_top_k = int(runtime.hybrid_structured_top_k) or normalized_top_k
    literal_top_k = int(runtime.hybrid_literal_top_k) or normalized_top_k
    return {
        "vector_min_score": get_runtime_override(
            "score_threshold",
            runtime.hybrid_vector_min_score,
        ),
        "vector_fetch_k": normalized_top_k * vector_fetch_multiplier,
        "text_fetch_k": normalized_top_k * text_fetch_multiplier,
        "rrf_rank_constant": max(1, int(runtime.hybrid_rrf_rank_constant)),
        "structured_top_k": max(1, structured_top_k),
        "literal_top_k": max(1, literal_top_k),
        "rerank_enabled": bool(get_runtime_override("rerank_enabled", True)),
    }


def _effective_vector_backend() -> str:
    override = get_runtime_override("vector_backend", None)
    if override:
        return str(override)
    try:
        return str(AppConfig().vector_store.type)
    except Exception:
        return "pgvector"


def _apply_query_family_routing(query_family: str, cfg: dict, top_k: int) -> dict:
    normalized_top_k = max(1, int(top_k))
    routed = dict(cfg)
    family_overrides = {
        "standard_ref": {
            "vector_fetch_k": max(normalized_top_k, normalized_top_k // 2),
            "text_fetch_k": normalized_top_k * 3,
            "structured_top_k": normalized_top_k * 2,
            "literal_top_k": normalized_top_k * 3,
        },
        "trend_chart": {
            "vector_fetch_k": normalized_top_k,
            "text_fetch_k": normalized_top_k,
            "structured_top_k": normalized_top_k * 3,
            "literal_top_k": normalized_top_k,
        },
        "comparison": {
            "vector_fetch_k": normalized_top_k,
            "text_fetch_k": normalized_top_k * 2,
            "structured_top_k": normalized_top_k * 3,
            "literal_top_k": normalized_top_k * 2,
        },
        "price": {
            "vector_fetch_k": normalized_top_k,
            "text_fetch_k": normalized_top_k * 2,
            "structured_top_k": normalized_top_k * 3,
            "literal_top_k": normalized_top_k,
        },
    }
    for key, value in family_overrides.get(query_family, {}).items():
        routed[key] = int(value)
    routed["route_policy"] = query_family
    return routed


def _log_retrieval_observability(event: str, payload: dict) -> None:
    if not read_runtime_config().retrieval_observability_enabled:
        return
    logger.info("[retrieval_observability] %s %s", event, json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _graph_tables_available(conn) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    to_regclass('public.canonical_concepts') IS NOT NULL
                AND to_regclass('public.concept_evidence_links') IS NOT NULL
                AND to_regclass('public.concept_relations') IS NOT NULL
                """
            )
            row = cur.fetchone()
            return bool(row and row[0])
    except Exception:
        return False


def _table_available(conn, table_name: str) -> bool:
    if not table_name:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass(%s) IS NOT NULL", (table_name,))
            row = cur.fetchone()
            return bool(row and row[0])
    except Exception:
        return False


def _table_has_column(conn, table_name: str, column_name: str) -> bool:
    """Return True if table has the named column (checks information_schema)."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_name = %s AND column_name = %s LIMIT 1
                """,
                (table_name, column_name),
            )
            return cur.fetchone() is not None
    except Exception:
        return False


def _resolve_text_search_config(conn) -> str:
    global _TSV_CONFIG_NAME
    if _TSV_CONFIG_NAME is not None:
        return _TSV_CONFIG_NAME
    with _TSV_CONFIG_LOCK:
        if _TSV_CONFIG_NAME is not None:
            return _TSV_CONFIG_NAME
        preferred_env = read_runtime_config().pg_tsv_config
        preferred = preferred_env if re.fullmatch(r"[a-z0-9_]+", preferred_env) else "simple"
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_catalog.pg_ts_config WHERE cfgname = %s LIMIT 1", (preferred,))
                if cur.fetchone() is not None:
                    _TSV_CONFIG_NAME = preferred
                else:
                    _TSV_CONFIG_NAME = "simple"
        except Exception as exc:
            logger.warning(f"[text_search_config] failed to probe ts config '{preferred}': {exc}")
            _TSV_CONFIG_NAME = "simple"
        if _TSV_CONFIG_NAME != preferred:
            logger.warning(
                "[text_search_config] ts config '%s' unavailable, fallback to '%s'",
                preferred,
                _TSV_CONFIG_NAME,
            )
    return _TSV_CONFIG_NAME


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
    started = time.perf_counter()
    try:
        svc = _get_embedding_svc()
        vector = svc.encode_single(text)
        _log_retrieval_observability(
            "embedding_encode",
            {
                "backend": getattr(svc, "backend", "unknown"),
                "dimension": int(getattr(svc, "dimension", 0) or 0),
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2),
            },
        )
        return vector
    except Exception as e:
        logger.warning(f"Embedding failed: {e}")
        _log_retrieval_observability(
            "embedding_encode_failed",
            {
                "error": str(e),
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2),
            },
        )
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


def _with_retrieval_path(
    chunk: dict,
    retrieval_path: str,
    *,
    evidence_kind: str = "",
    route_stage: str = "",
) -> dict:
    metadata = dict(chunk.get("metadata") or {})
    metadata["retrieval_path"] = retrieval_path
    if evidence_kind:
        metadata["evidence_kind"] = evidence_kind
    if route_stage:
        metadata["route_stage"] = route_stage
    chunk["metadata"] = metadata
    chunk["retrieval_path"] = retrieval_path
    return chunk


_STRUCTURED_TABLE_QUERY_HINTS = (
    "费率",
    "推荐费率",
    "推荐系数",
    "推荐比例",
    "费率标准",
    "企业管理费",
    "利润率",
    "安全文明施工费",
    "赶工措施费",
    "总包管理服务费",
    "计算基数",
    "优质优价奖励费",
    "夜间施工增加费",
    "履约担保手续费",
)

_FEE_FORMULA_HINT_RE = re.compile(r"计算方法|计算公式|计算规则|公式|怎么计算|如何计算")
_FEE_STANDARD_YEAR_RE = re.compile(r"(20\d{2})\s*版?")
_FEE_ITEM_RE = re.compile(
    r"企业管理费|安全文明施工费费率部分|安全文明施工费|履约担保手续费|夜间施工增加费|"
    r"总包管理服务费及发包人供应材料（设备）保管费|总包管理服务费|发包人供应材料（设备）保管费|"
    r"暂列金额|优质优价奖励费|利润"
)

_concept_analyzer = QueryAnalyzer()


def _should_include_structured_tables(query: str) -> bool:
    """Return True if the query is likely about fee-rate structured data.

    Strategy (rerank-first, keyword fallback):
    1. ANN gate   — embed the query, pull top-5 fee_rates candidates from pgvector.
    2. Rerank gate — BGE-reranker-v2-m3 scores each (query, fee_name + source_text)
                     pair as a cross-encoder.  Cross-encoder scores are trained
                     relevance signals; score > 0 reliably indicates a relevant pair.
                     No manually tuned threshold needed.
    3. Keyword gate — cheap fallback when embedding/reranker/DB is unavailable.
    """
    normalized = (query or "").strip()
    if not normalized:
        return False

    # --- ANN + rerank gate ---
    try:
        query_vec = _get_embedding(normalized)
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT fee_name, COALESCE(NULLIF(TRIM(applicable_scope),''), source_text, '') AS doc_text
                    FROM   fee_rates
                    WHERE  embedding IS NOT NULL
                    ORDER  BY embedding <=> %s::vector
                    LIMIT  5
                    """,
                    (query_vec,),
                )
                rows = cur.fetchall()
        finally:
            _put_pg_conn(conn)

        if rows:
            from infrastructure.reranker_service import get_reranker_service
            reranker = get_reranker_service()
            docs = [f"{r[0]} {r[1]}"[:512] for r in rows]
            scores = reranker.rerank(normalized, docs)
            best = max(scores) if scores else -999
            logger.debug(
                "[structured_table_gate] reranker best=%.3f query=%r",
                best,
                normalized[:60],
            )
            # sigmoid > 0.5 is the model's natural boundary (logit > 0 = relevant).
            # This is not an arbitrary threshold — it's the trained decision boundary.
            if best > 0.5:
                return True

    except Exception as exc:
        logger.warning("[structured_table_gate] rerank gate failed (%s), using keyword fallback", exc)

    # --- Keyword gate (fallback) ---
    return any(hint in normalized for hint in _STRUCTURED_TABLE_QUERY_HINTS)


def _extract_requested_standard_year(query: str) -> str:
    match = _FEE_STANDARD_YEAR_RE.search(query or "")
    return match.group(1) if match else ""


def _extract_requested_standard_years(query: str) -> list[str]:
    years: list[str] = []
    for year in re.findall(r"(20\d{2})\s*版?", query or ""):
        if year not in years:
            years.append(year)
    return years


def _is_fee_formula_query(query: str) -> bool:
    normalized = (query or "").strip()
    return bool(_should_include_structured_tables(normalized) and _FEE_FORMULA_HINT_RE.search(normalized))


def _extract_fee_formula_item(query: str) -> str:
    match = _FEE_ITEM_RE.search(query or "")
    return match.group(0) if match else ""


def _build_query_concepts(query: str) -> list[dict]:
    normalized_query = (query or "").strip()
    if not normalized_query:
        return []

    analysis = _concept_analyzer.analyze(normalized_query)
    entities = analysis.get("entities", {})
    concepts: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def _append(concept_type: str, concept_name: str, terms: list[str], preferred_tool: str) -> None:
        normalized_name = (concept_name or "").strip()
        if not normalized_name:
            return
        key = (concept_type, normalized_name)
        if key in seen:
            return
        seen.add(key)
        concepts.append(
            {
                "concept_type": concept_type,
                "concept_name": normalized_name,
                "terms": [term for term in terms if term],
                "preferred_tool": preferred_tool,
            }
        )

    for material in entities.get("material_names") or []:
        preferred_tool = "price_trend" if analysis.get("intent") == "trend_chart" else "price_query"
        _append("material", material, [material], preferred_tool)

    fee_item = _extract_fee_formula_item(normalized_query)
    if fee_item:
        preferred_tool = "text_search"
        if "计算基数" in normalized_query or "计算公式" in normalized_query:
            preferred_tool = "text_search"
        _append(
            "fee_item",
            fee_item,
            [fee_item, f"{fee_item} 计算基数", f"{fee_item} 计算公式"],
            preferred_tool,
        )

    if is_fill_requirement_query(normalized_query):
        field_name = extract_fill_requirement_search_term(normalized_query)
        _append("fill_field", field_name, [field_name, f"{field_name} 填写要求"], "text_search")

    if is_appendix_standard_query(normalized_query):
        title = extract_appendix_standard_title(normalized_query)
        terms = [title, *extract_appendix_standard_terms(normalized_query)]
        _append("standard_title", title, terms, "pdf_page_search")

    if not concepts:
        _append("query_theme", normalized_query[:48], [normalized_query], "text_search")

    return concepts[:6]


def _count_price_record_hits(conn, term: str) -> int:
    # Expand abbreviations: if term contains 砼 etc., also try the expanded form
    variants = _expand_query_variants(term)
    patterns = [f"%{v}%" for v in variants]
    with conn.cursor() as cur:
        clauses = " OR ".join(["(material_name ILIKE %s OR specification ILIKE %s)"] * len(variants))
        flat_params = [p for v in [f"%{v}%" for v in variants] for p in (v, v)]
        cur.execute(
            f"SELECT COUNT(*) FROM price_records WHERE {clauses}",
            flat_params,
        )
        row = cur.fetchone()
    count = int(row[0] if row else 0)
    if count == 0 and len(term) >= 3:
        # Trigram fallback for synonym/paraphrase misses (requires pg_trgm)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                        SELECT COUNT(*)
                        FROM price_records
                        WHERE word_similarity(%s, material_name) > 0.20
                    """,
                    (term,),
                )
                trgm_row = cur.fetchone()
                count = int(trgm_row[0] if trgm_row else 0)
        except Exception:
            pass  # pg_trgm not available or query failed, ignore
    return count


def _count_fee_rate_hits(conn, term: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
                SELECT COUNT(*)
                FROM fee_rates
                WHERE fee_name ILIKE %s OR source_text ILIKE %s
            """,
            (f"%{term}%", f"%{term}%"),
        )
        row = cur.fetchone()
    return int(row[0] if row else 0)


def _sample_text_hit(conn, terms: list[str]) -> tuple[int, str, int, str] | None:
    if not terms:
        return None
    clauses = " OR ".join(["content ILIKE %s"] * len(terms))
    params = [f"%{term}%" for term in terms]
    with conn.cursor() as cur:
        cur.execute(
            f"""
                SELECT id, doc_id, page_number, content
                FROM text_chunks
                WHERE {clauses}
                ORDER BY length(content) ASC
                LIMIT 1
            """,
            params,
        )
        return cur.fetchone()


def _load_concept_hits_from_graph(conn, query: str, top_k: int = 6) -> list[dict]:
    concept_defs = _build_query_concepts(query)
    results: list[dict] = []

    for concept in concept_defs:
        terms = concept["terms"]
        concept_type = concept["concept_type"]
        concept_name = concept["concept_name"]
        preferred_tool = concept["preferred_tool"]

        patterns = [f"%{term}%" for term in ([concept_name, *terms] if terms else [concept_name])]
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    c.id,
                    c.concept_type,
                    c.concept_name,
                    COALESCE(c.preferred_route, %s) AS preferred_route,
                    COUNT(*) FILTER (WHERE l.evidence_kind IN ('structured_row', 'ocr_row')) AS structured_hits,
                    COUNT(*) FILTER (WHERE l.evidence_kind = 'embedding_chunk') AS embedding_hits,
                    COUNT(*) FILTER (WHERE l.evidence_kind = 'pdf_page') AS pdf_hits,
                    MAX(NULLIF(l.doc_id, '')) AS sample_doc_id,
                    MAX(NULLIF(l.page_number, 0)) AS sample_page_number,
                    MAX(NULLIF(l.file_name, '')) AS sample_file_name
                FROM canonical_concepts c
                LEFT JOIN concept_evidence_links l ON l.concept_id = c.id
                WHERE c.concept_type = %s
                  AND (
                    c.concept_name ILIKE ANY(%s)
                    OR EXISTS (
                        SELECT 1
                        FROM unnest(COALESCE(c.aliases, ARRAY[]::text[])) AS alias
                        WHERE alias ILIKE ANY(%s)
                    )
                  )
                GROUP BY c.id, c.concept_type, c.concept_name, c.preferred_route
                ORDER BY structured_hits DESC, embedding_hits DESC, pdf_hits DESC, c.id ASC
                LIMIT 1
                """,
                (preferred_tool, concept_type, patterns, patterns),
            )
            row = cur.fetchone()

        if not row:
            # Embedding-similarity fallback: ILIKE 未命中时用向量相似度找最近概念
            concept_term = concept_name or (terms[0] if terms else query)
            term_emb = _get_embedding(concept_term)
            if term_emb:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            c.id,
                            c.concept_type,
                            c.concept_name,
                            COALESCE(c.preferred_route, %s) AS preferred_route,
                            COUNT(*) FILTER (WHERE l.evidence_kind IN ('structured_row', 'ocr_row')) AS structured_hits,
                            COUNT(*) FILTER (WHERE l.evidence_kind = 'embedding_chunk') AS embedding_hits,
                            COUNT(*) FILTER (WHERE l.evidence_kind = 'pdf_page') AS pdf_hits,
                            MAX(NULLIF(l.doc_id, '')) AS sample_doc_id,
                            MAX(NULLIF(l.page_number, 0)) AS sample_page_number,
                            MAX(NULLIF(l.file_name, '')) AS sample_file_name,
                            1 - (c.embedding <=> %s::vector) AS emb_sim
                        FROM canonical_concepts c
                        LEFT JOIN concept_evidence_links l ON l.concept_id = c.id
                        WHERE c.embedding IS NOT NULL
                          AND 1 - (c.embedding <=> %s::vector) >= 0.70
                        GROUP BY c.id, c.concept_type, c.concept_name, c.preferred_route, c.embedding
                        ORDER BY c.embedding <=> %s::vector
                        LIMIT 1
                        """,
                        (preferred_tool, term_emb, term_emb, term_emb),
                    )
                    row = cur.fetchone()
            if not row:
                continue

        (
            concept_id,
            resolved_type,
            resolved_name,
            resolved_route,
            structured_hits,
            embedding_hits,
            pdf_hits,
            sample_doc_id,
            sample_page_number,
            sample_file_name,
            *_extra,  # emb_sim may or may not be present depending on code path
        ) = row

        structured_hits = int(structured_hits or 0)
        embedding_hits = int(embedding_hits or 0)
        pdf_hits = int(pdf_hits or 0)
        if structured_hits == 0 and embedding_hits == 0 and pdf_hits == 0:
            continue

        retrieval_path = RETRIEVAL_PATH_DATABASE if (structured_hits + embedding_hits) > 0 else RETRIEVAL_PATH_PDF_PAGE
        total_hits = structured_hits + embedding_hits + pdf_hits
        results.append(
            _with_retrieval_path(
                {
                    "chunk_id": f"concept_graph_{concept_id}",
                    "doc_id": str(sample_doc_id or ""),
                    "page_number": int(sample_page_number or 1),
                    "source_db": "concept_graph",
                    "content": (
                        f"概念:{resolved_name} 类型:{resolved_type} "
                        f"结构化:{structured_hits} 向量块:{embedding_hits} 页证据:{pdf_hits} "
                        f"建议下钻:{resolved_route} 来源:{sample_file_name or ''}"
                    ).strip(),
                    "score": 0.93 if (structured_hits + embedding_hits) > 0 else 0.81,
                    "metadata": {
                        "concept_id": int(concept_id),
                        "concept_name": resolved_name,
                        "concept_type": resolved_type,
                        "structured_hits": structured_hits,
                        "embedding_hits": embedding_hits,
                        "pdf_hits": pdf_hits,
                        "total_hits": total_hits,
                        "preferred_tool": resolved_route,
                        "concept_terms": terms or [resolved_name],
                        "graph_enabled": True,
                    },
                },
                retrieval_path,
                evidence_kind="concept_hit",
                route_stage="primary",
            )
        )

        if len(results) >= top_k:
            break

    return results


def _load_concept_hits_heuristic(conn, query: str, top_k: int = 6) -> list[dict]:
    concept_defs = _build_query_concepts(query)
    results: list[dict] = []

    for index, concept in enumerate(concept_defs, start=1):
        terms = concept["terms"]
        concept_type = concept["concept_type"]
        concept_name = concept["concept_name"]
        preferred_tool = concept["preferred_tool"]

        structured_hits = 0
        if concept_type == "material":
            structured_hits = sum(_count_price_record_hits(conn, term) for term in terms[:2])
        elif concept_type == "fee_item":
            structured_hits = sum(_count_fee_rate_hits(conn, term) for term in terms[:2])

        text_hit = _sample_text_hit(conn, terms)
        text_hits = 1 if text_hit else 0
        retrieval_path = RETRIEVAL_PATH_DATABASE if structured_hits > 0 else RETRIEVAL_PATH_PDF_PAGE
        page_number = text_hit[2] if text_hit else 1
        doc_id = str(text_hit[1] or "") if text_hit else ""
        preview = (text_hit[3] or "")[:160] if text_hit else ""

        if structured_hits == 0 and text_hits == 0:
            continue

        results.append(
            _with_retrieval_path(
                {
                    "chunk_id": f"concept_{index}_{concept_type}_{concept_name}",
                    "doc_id": doc_id,
                    "page_number": page_number,
                    "source_db": "concept_search",
                    "content": (
                        f"概念:{concept_name} 类型:{concept_type} "
                        f"结构化命中:{structured_hits} 文本命中:{text_hits} "
                        f"建议下钻:{preferred_tool} "
                        + (f"示例证据:{preview}" if preview else "")
                    ).strip(),
                    "score": 0.91 if structured_hits > 0 else 0.79,
                    "metadata": {
                        "concept_name": concept_name,
                        "concept_type": concept_type,
                        "structured_hits": structured_hits,
                        "text_hits": text_hits,
                        "preferred_tool": preferred_tool,
                        "concept_terms": terms,
                        "graph_enabled": False,
                    },
                },
                retrieval_path,
                evidence_kind="concept_hit",
                route_stage="primary",
            )
        )

        if len(results) >= top_k:
            break

    return results


def _load_concept_hits(conn, query: str, top_k: int = 6) -> list[dict]:
    if _graph_tables_available(conn):
        try:
            graph_hits = _load_concept_hits_from_graph(conn, query, top_k=top_k)
            if graph_hits:
                return graph_hits
        except Exception as exc:
            logger.warning(f"[concept_search] graph query failed, fallback to heuristic: {exc}")
    return _load_concept_hits_heuristic(conn, query, top_k=top_k)


def _attach_concept_lineage(chunk: dict, concept_hit: dict) -> dict:
    metadata = dict(chunk.get("metadata") or {})
    concept_meta = concept_hit.get("metadata") or {}
    metadata["parent_concept_id"] = concept_hit.get("chunk_id", "")
    metadata["parent_concept_graph_id"] = concept_meta.get("concept_id")
    metadata["parent_concept_name"] = concept_meta.get("concept_name", "")
    metadata["parent_concept_type"] = concept_meta.get("concept_type", "")
    metadata["relation_kind"] = "concept_to_evidence"
    metadata["route_stage"] = metadata.get("route_stage") or "secondary"
    chunk["metadata"] = metadata
    return chunk


def _query_concept_price_rows(conn, concept_name: str, top_k: int = 2) -> list[dict]:
    if not concept_name:
        return []

    with conn.cursor() as cur:
        cur.execute(
            """
                SELECT id, doc_id, page_number,
                       material_name, specification, unit, price_tax_included, year_month, category
                FROM price_records
                WHERE material_name ILIKE %s OR specification ILIKE %s
                ORDER BY year_month DESC, id
                LIMIT %s
            """,
            (f"%{concept_name}%", f"%{concept_name}%", top_k),
        )
        rows = cur.fetchall()

    results: list[dict] = []
    for row in rows:
        price = row[6]
        price_text = f"{float(price):.2f}" if price is not None else "N/A"
        chunk = _with_retrieval_path(
            {
                "chunk_id": f"concept_price_{row[0]}",
                "doc_id": str(row[1] or ""),
                "page_number": row[2] or 1,
                "source_db": "price_records",
                "content": (
                    f"{row[3] or concept_name} {row[4] or ''} "
                    f"单位:{row[5] or ''} 价格:{price_text}元 期间:{row[7] or ''} 类别:{row[8] or ''}"
                ).strip(),
                "score": 0.86,
                "metadata": {
                    "year_month": row[7] or "",
                    "unit": row[5] or "",
                    "price": price_text,
                },
            },
            RETRIEVAL_PATH_DATABASE,
            evidence_kind="structured_row",
            route_stage="secondary",
        )
        results.append(chunk)
    return results


def _query_concept_trend_points(conn, concept_name: str, top_k: int = 2) -> list[dict]:
    trend_rows = _query_trend_points(conn, concept_name, "", "")
    if not trend_rows:
        return []

    selected_rows = trend_rows[-top_k:]
    results: list[dict] = []
    for row in selected_rows:
        (
            point_id,
            year_month,
            avg_price,
            unit,
            page_number,
            doc_id,
            display_name,
            delta_value,
            delta_percent,
            trend_direction,
        ) = row
        avg = float(avg_price or 0)
        content = (
            f"{display_name or concept_name} 价格走势 期间:{year_month} 均价:{avg:.2f}元/{unit or ''}"
        )
        if delta_value is not None:
            content += (
                f" 环比变化:{float(delta_value):+.2f}"
                f" 环比幅度:{float(delta_percent):+.2f}% 趋势:{trend_direction or ''}"
            )
        chunk = _with_retrieval_path(
            {
                "chunk_id": f"concept_trend_{point_id}",
                "doc_id": doc_id or "trend_points",
                "page_number": page_number or 1,
                "source_db": "trend_points",
                "content": content,
                "score": 0.84,
                "metadata": {
                    "year_month": year_month,
                    "avg_price": avg,
                    "unit": unit,
                    "delta": float(delta_value) if delta_value is not None else None,
                    "delta_percent": float(delta_percent) if delta_percent is not None else None,
                    "trend_direction": trend_direction,
                },
            },
            RETRIEVAL_PATH_DATABASE,
            evidence_kind="trend_point",
            route_stage="secondary",
        )
        results.append(chunk)
    return results


def _materialize_graph_evidence(conn, evidence_row: tuple) -> dict | None:
    (
        concept_id,
        depth,
        evidence_kind,
        source_table,
        source_id,
        doc_id,
        file_name,
        page_number,
        parent_doc_id,
        parent_page,
        chunk_id,
        link_score,
        metadata_raw,
    ) = evidence_row

    evidence_meta: dict = {}
    if isinstance(metadata_raw, dict):
        evidence_meta = dict(metadata_raw)
    elif isinstance(metadata_raw, str) and metadata_raw.strip():
        try:
            parsed = json.loads(metadata_raw)
            if isinstance(parsed, dict):
                evidence_meta = parsed
        except Exception:
            evidence_meta = {}

    resolved_doc = str(doc_id or parent_doc_id or evidence_meta.get("doc_id") or "")
    resolved_page = int(page_number or parent_page or evidence_meta.get("page_number") or 1)
    resolved_content = str(evidence_meta.get("content") or "")
    resolved_source = str(source_table or evidence_meta.get("source_table") or "concept_graph")

    if source_table == "price_records" and source_id is not None:
        with conn.cursor() as cur:
            cur.execute(
                """
                    SELECT doc_id, page_number, material_name, specification, unit,
                           price_tax_included, year_month, category
                    FROM price_records
                    WHERE id = %s
                    LIMIT 1
                """,
                (source_id,),
            )
            row = cur.fetchone()
        if row:
            resolved_doc = str(row[0] or resolved_doc)
            resolved_page = int(row[1] or resolved_page)
            price = row[5]
            price_text = f"{float(price):.2f}" if price is not None else "N/A"
            resolved_content = (
                f"{row[2] or ''} {row[3] or ''} 单位:{row[4] or ''} "
                f"价格:{price_text}元 期间:{row[6] or ''} 类别:{row[7] or ''}"
            ).strip()
            resolved_source = "price_records"
    elif source_table == "fee_rates" and source_id is not None:
        with conn.cursor() as cur:
            cur.execute(
                """
                    SELECT doc_id, page_number, fee_name, base_formula,
                           rate_recommended, calc_base
                    FROM fee_rates
                    WHERE id = %s
                    LIMIT 1
                """,
                (source_id,),
            )
            row = cur.fetchone()
        if row:
            resolved_doc = str(row[0] or resolved_doc)
            resolved_page = int(row[1] or resolved_page)
            recommended = row[4]
            rate_text = f"{float(recommended):.2f}" if recommended is not None else "N/A"
            resolved_content = (
                f"{row[2] or ''} 计算公式:{row[3] or ''} 推荐费率:{rate_text}% 计算基数:{row[5] or ''}"
            ).strip()
            resolved_source = "fee_rates"
    elif source_table == "text_chunks":
        lookup_id = source_id if source_id is not None else chunk_id
        if lookup_id is not None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                        SELECT id, doc_id, page_number, content
                        FROM text_chunks
                        WHERE id = %s
                        LIMIT 1
                    """,
                    (lookup_id,),
                )
                row = cur.fetchone()
            if row:
                chunk_id = row[0]
                resolved_doc = str(row[1] or resolved_doc)
                resolved_page = int(row[2] or resolved_page)
                resolved_content = str(row[3] or resolved_content)
                resolved_source = "text_chunks"

    if not resolved_content:
        if evidence_kind == "pdf_page":
            resolved_content = f"PDF页面证据: {file_name or resolved_doc}"
        else:
            return None

    retrieval_path = (
        RETRIEVAL_PATH_PDF_PAGE
        if evidence_kind == "pdf_page"
        else (RETRIEVAL_PATH_OCR_JSON if evidence_kind == "ocr_row" else RETRIEVAL_PATH_DATABASE)
    )

    fallback_chunk_id = f"graph_{source_table}_{source_id or chunk_id or concept_id}_{depth}"
    return _with_retrieval_path(
        {
            "chunk_id": str(chunk_id or fallback_chunk_id),
            "doc_id": resolved_doc,
            "page_number": resolved_page,
            "source_db": f"graph_{resolved_source}",
            "content": resolved_content,
            "score": round(min(0.98, max(0.65, float(link_score or 0.65))), 4),
            "metadata": {
                "graph_depth": int(depth or 0),
                "concept_id": int(concept_id),
                "file_name": file_name or "",
                "parent_doc_id": parent_doc_id or "",
                "parent_page": parent_page,
                "source_table": source_table or "",
                "evidence_kind": evidence_kind,
                "link_score": float(link_score or 0.0),
                **evidence_meta,
            },
        },
        retrieval_path,
        evidence_kind=evidence_kind,
        route_stage="secondary",
    )


def _expand_concept_hits_from_graph(
    conn,
    concept_hits: list[dict],
    top_k: int = 2,
    recursive_depth: int | None = None,
) -> list[dict]:
    if not concept_hits:
        return []

    recursive_depth = (
        max(1, min(4, int(recursive_depth)))
        if recursive_depth is not None
        else max(1, min(4, int(read_runtime_config().concept_recursive_depth)))
    )
    per_concept_limit = max(2, top_k * 2)
    expanded: list[dict] = []
    seen_ids: set[str] = set()

    for concept_hit in concept_hits:
        concept_meta = concept_hit.get("metadata") or {}
        concept_id = concept_meta.get("concept_id")
        if concept_id is None:
            continue

        with conn.cursor() as cur:
            cur.execute(
                """
                WITH RECURSIVE relation_walk AS (
                    SELECT %s::bigint AS concept_id, 0 AS depth, ARRAY[%s::bigint] AS path
                    UNION ALL
                    SELECT
                        r.target_concept_id,
                        relation_walk.depth + 1,
                        relation_walk.path || r.target_concept_id
                    FROM relation_walk
                    JOIN concept_relations r ON r.source_concept_id = relation_walk.concept_id
                    WHERE relation_walk.depth < %s
                      AND NOT (r.target_concept_id = ANY(relation_walk.path))
                ),
                dedup AS (
                    SELECT concept_id, MIN(depth) AS depth
                    FROM relation_walk
                    GROUP BY concept_id
                )
                SELECT
                    d.concept_id,
                    d.depth,
                    l.evidence_kind,
                    l.source_table,
                    l.source_id,
                    l.doc_id,
                    l.file_name,
                    l.page_number,
                    l.parent_doc_id,
                    l.parent_page_number AS parent_page,
                    l.chunk_id,
                    l.link_score,
                    l.metadata::text
                FROM dedup d
                JOIN concept_evidence_links l ON l.concept_id = d.concept_id
                ORDER BY d.depth ASC, l.link_score DESC, l.id ASC
                LIMIT %s
                """,
                (int(concept_id), int(concept_id), recursive_depth, per_concept_limit),
            )
            evidence_rows = cur.fetchall()

        for evidence_row in evidence_rows:
            chunk = _materialize_graph_evidence(conn, evidence_row)
            if not chunk:
                continue
            cid = str(chunk.get("chunk_id") or "")
            if not cid or cid in seen_ids:
                continue
            seen_ids.add(cid)
            expanded.append(_attach_concept_lineage(chunk, concept_hit))

    return expanded


def _expand_concept_hits_heuristic(conn, query: str, concept_hits: list[dict], top_k: int = 2) -> list[dict]:
    if not concept_hits:
        return []

    expanded: list[dict] = []
    seen_ids: set[str] = set()

    for concept_hit in concept_hits:
        concept_meta = concept_hit.get("metadata") or {}
        concept_type = str(concept_meta.get("concept_type") or "")
        concept_name = str(concept_meta.get("concept_name") or "")
        concept_terms = [str(term) for term in (concept_meta.get("concept_terms") or []) if term]
        preferred_tool = str(concept_meta.get("preferred_tool") or "")

        local_hits: list[dict] = []
        try:
            if concept_type == "material" and preferred_tool == "price_trend":
                local_hits.extend(_query_concept_trend_points(conn, concept_name, top_k=top_k))
            elif concept_type == "material":
                local_hits.extend(_query_concept_price_rows(conn, concept_name, top_k=top_k))
                if not local_hits:
                    local_hits.extend(_query_text_chunks_literal(conn, concept_name, top_k=top_k))
            else:
                # Phase 1+ Task 1: Externalize drill-down top_k
                from config.param_registry import param
                drill_top_k = param("price_query_page_top_k", default=1)
                
                drill_terms = concept_terms[:2] if concept_terms else [concept_name]
                for term in drill_terms:
                    local_hits.extend(_query_text_chunks_literal(conn, term, top_k=drill_top_k))
                if _should_include_structured_tables(query):
                    local_hits.extend(_query_structured_tables(query, top_k=drill_top_k))
        except Exception as e:
            conn.rollback()
            logger.warning(f"[concept_expand] failed for concept '{concept_name}': {e}")
            continue

        for item in local_hits:
            cid = item.get("chunk_id")
            if not cid or cid in seen_ids:
                continue
            seen_ids.add(cid)
            expanded.append(_attach_concept_lineage(item, concept_hit))

    return expanded


def _expand_concept_hits(
    conn,
    query: str,
    concept_hits: list[dict],
    top_k: int = 2,
    recursive_depth: int | None = None,
) -> list[dict]:
    if not concept_hits:
        return []

    has_graph_concept = any((hit.get("metadata") or {}).get("concept_id") for hit in concept_hits)
    if has_graph_concept and _graph_tables_available(conn):
        try:
            graph_expanded = _expand_concept_hits_from_graph(
                conn,
                concept_hits,
                top_k=top_k,
                recursive_depth=recursive_depth,
            )
            if graph_expanded:
                return graph_expanded
        except Exception as exc:
            conn.rollback()
            logger.warning(f"[concept_expand] graph recursive expansion failed, fallback to heuristic: {exc}")

    return _expand_concept_hits_heuristic(conn, query, concept_hits, top_k=top_k)


def _rrf_fuse_chunks(ranked_lists: list[list[dict]], rank_constant: int = 60) -> list[dict]:
    fused_index: dict[str, dict] = {}

    for ranked in ranked_lists:
        for rank, chunk in enumerate(ranked, start=1):
            cid = str(chunk.get("chunk_id") or "")
            if not cid:
                continue
            if cid not in fused_index:
                fused_index[cid] = {
                    "chunk": dict(chunk),
                    "rrf_score": 0.0,
                    "hit_count": 0,
                    "best_rank": rank,
                }
            entry = fused_index[cid]
            entry["rrf_score"] += 1.0 / (rank_constant + rank)
            entry["hit_count"] += 1
            entry["best_rank"] = min(entry["best_rank"], rank)
            if float(chunk.get("score", 0.0) or 0.0) > float(entry["chunk"].get("score", 0.0) or 0.0):
                entry["chunk"] = dict(chunk)

    fused: list[dict] = []
    for entry in fused_index.values():
        item = dict(entry["chunk"])
        metadata = dict(item.get("metadata") or {})
        rrf_score = float(entry["rrf_score"])
        hit_count = int(entry["hit_count"])
        boost = min(0.12, rrf_score * 8.0 + max(0, hit_count - 1) * 0.03)
        base_score = float(item.get("score", 0.0) or 0.0)
        item["score"] = round(min(0.99, base_score + boost), 4)
        metadata["fusion_method"] = "rrf"
        metadata["rrf_score"] = round(rrf_score, 8)
        metadata["rrf_hit_count"] = hit_count
        metadata["rrf_best_rank"] = int(entry["best_rank"])
        metadata["fusion_boost"] = round(boost, 6)
        item["metadata"] = metadata
        fused.append(item)

    fused.sort(
        key=lambda chunk: (
            float((chunk.get("metadata") or {}).get("rrf_score", 0.0) or 0.0),
            int((chunk.get("metadata") or {}).get("rrf_hit_count", 0) or 0),
            float(chunk.get("score", 0.0) or 0.0),
        ),
        reverse=True,
    )
    return fused


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


def _query_fee_comparison_text_chunks(conn, query: str, top_k: int = 10) -> list[dict]:
    if not is_fee_standard_comparison_query(query):
        return []

    results: list[dict] = []
    seen_ids: set[str] = set()
    search_queries = extract_fee_standard_comparison_queries(query)

    with conn.cursor() as cur:
        for search_query in search_queries:
            parts = search_query.split(" ", 2)
            if len(parts) < 3:
                continue
            year, item, target = parts
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
                (f"%费率标准（{year}）%", f"%{item}%", f"%{target}%", "%参考范围%", top_k),
            )
            rows = cur.fetchall()
            if not rows:
                cur.execute(
                    """
                        SELECT id, doc_id, page_number, content
                        FROM text_chunks
                        WHERE file_name ILIKE %s
                          AND content ILIKE %s
                        ORDER BY page_number ASC
                        LIMIT %s
                    """,
                    (f"%费率标准（{year}）%", f"%{item}%", top_k),
                )
                rows = cur.fetchall()

            for row in rows:
                cid = f"fee_compare_{row[0]}"
                if cid in seen_ids:
                    continue
                seen_ids.add(cid)
                results.append(
                    {
                        "chunk_id": cid,
                        "doc_id": str(row[1] or ""),
                        "page_number": row[2] or 1,
                        "source_db": "fee_compare_text",
                        "content": row[3] or "",
                        "score": 0.97,
                        "metadata": {"year": year, "item": item, "target": target},
                    }
                )
    return results[:top_k]


def _query_text_chunks_literal(conn, query: str, top_k: int = 10, path_constraint: str = "") -> list[dict]:
    if not query.strip():
        return []

    path_clause = "AND path LIKE %s" if path_constraint else ""
    path_params: tuple = (path_constraint,) if path_constraint else ()

    with conn.cursor() as cur:
        cur.execute(
            f"""
                SELECT id, doc_id, page_number, content, file_name, path, metadata
                FROM text_chunks
                WHERE content ILIKE %s
                {path_clause}
                ORDER BY length(content)
                LIMIT %s
            """,
            (f"%{query.strip()}%", *path_params, top_k),
        )
        rows = cur.fetchall()

    return [
        _with_retrieval_path(
            {
                "chunk_id": f"tc_{row[0]}",
                "doc_id": str(row[1] or ""),
                "page_number": row[2] or 1,
                "source_db": "literal_text",
                "content": row[3] or "",
                "score": 0.72,
                "doc_filename": row[4] or "",
                "file_name": row[4] or "",
                "path": row[5] or "",
                "metadata": dict(row[6] or {}),
            },
            RETRIEVAL_PATH_PDF_PAGE,
            evidence_kind="pdf_page_literal",
            route_stage="fallback",
        )
        for row in rows
    ]


def _query_fill_requirement_text_chunks(conn, query: str, top_k: int = 10) -> list[dict]:
    if not is_fill_requirement_query(query):
        return []

    field = extract_fill_requirement_search_term(query)
    if not field:
        return []

    results: list[dict] = []
    seen_ids: set[str] = set()
    with conn.cursor() as cur:
        cur.execute(
            """
                SELECT id, doc_id, page_number, content
                FROM text_chunks
                WHERE content ILIKE %s
                  AND (
                        content ILIKE %s
                     OR content ILIKE %s
                     OR content ILIKE %s
                     OR content ILIKE %s
                  )
                ORDER BY
                  CASE
                    WHEN content ILIKE %s THEN 0
                    WHEN content ILIKE %s THEN 1
                    ELSE 2
                  END,
                  page_number ASC,
                  length(content) ASC
                LIMIT %s
            """,
            (
                f"%{field}%",
                "%应填写%",
                "%应按%",
                "%填写%",
                "%填写要求%",
                f"%{field}应%",
                f"%{field}%填写%",
                top_k,
            ),
        )
        for row in cur.fetchall():
            cid = f"fill_requirement_{row[0]}"
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            results.append(
                {
                    "chunk_id": cid,
                    "doc_id": str(row[1] or ""),
                    "page_number": row[2] or 1,
                    "source_db": "fill_requirement_text",
                    "content": row[3] or "",
                    "score": 0.96,
                    "metadata": {"field_name": field},
                }
            )

        if not results:
            cur.execute(
                """
                    SELECT id, doc_id, page_number, content
                    FROM text_chunks
                    WHERE content ILIKE %s
                    ORDER BY page_number ASC, length(content) ASC
                    LIMIT %s
                """,
                (f"%{field}%", top_k),
            )
            for row in cur.fetchall():
                cid = f"fill_requirement_{row[0]}"
                if cid in seen_ids:
                    continue
                seen_ids.add(cid)
                results.append(
                    {
                        "chunk_id": cid,
                        "doc_id": str(row[1] or ""),
                        "page_number": row[2] or 1,
                        "source_db": "fill_requirement_text",
                        "content": row[3] or "",
                        "score": 0.9,
                        "metadata": {"field_name": field},
                    }
                )

    return results[:top_k]


def _query_appendix_standard_text_chunks(conn, query: str, top_k: int = 10) -> list[dict]:
    if not is_appendix_standard_query(query):
        return []

    title = extract_appendix_standard_title(query)
    terms = extract_appendix_standard_terms(query)
    if not title:
        return []

    results: list[dict] = []
    seen_ids: set[str] = set()
    with conn.cursor() as cur:
        cur.execute(
            """
                SELECT DISTINCT doc_id
                FROM text_chunks
                WHERE content ILIKE %s OR file_name ILIKE %s
                LIMIT 5
            """,
            (f"%{title}%", f"%{title}%"),
        )
        doc_ids = [row[0] for row in cur.fetchall() if row[0]]
        if not doc_ids:
            return []

        placeholders = ",".join(["%s"] * len(doc_ids))
        term_filters = []
        term_params: list[str] = []
        for term in terms:
            term_filters.append("content ILIKE %s")
            term_params.append(f"%{term}%")
        content_filter_sql = f"({' OR '.join(term_filters)})" if term_filters else "TRUE"
        order_title = f"%{title}%"
        order_term = f"%{terms[0]}%" if terms else "%适用%"
        cur.execute(
            f"""
                SELECT id, doc_id, page_number, content
                FROM text_chunks
                WHERE doc_id IN ({placeholders})
                  AND {content_filter_sql}
                ORDER BY
                  CASE
                    WHEN content ~ '(^|\\n)\\s*[0-9]+\\.[0-9]+\\.[0-9]+' THEN 0
                    WHEN content ILIKE '%%本定额%%' OR content ILIKE '%%本标准%%' OR content ILIKE '%%本办法%%' OR content ILIKE '%%本规定%%' THEN 1
                    WHEN content ILIKE %s THEN 2
                    WHEN content ILIKE %s THEN 3
                    ELSE 4
                  END,
                  page_number ASC,
                  length(content) ASC
                LIMIT %s
            """,
            [*doc_ids, *term_params, order_title, order_term, top_k],
        )
        for row in cur.fetchall():
            cid = f"appendix_standard_{row[0]}"
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            results.append(
                {
                    "chunk_id": cid,
                    "doc_id": str(row[1] or ""),
                    "page_number": row[2] or 1,
                    "source_db": "appendix_standard_text",
                    "content": row[3] or "",
                    "score": 0.98,
                    "metadata": {"standard_title": title, "query_terms": terms},
                }
            )

        if not results:
            cur.execute(
                f"""
                    SELECT id, doc_id, page_number, content
                    FROM text_chunks
                    WHERE doc_id IN ({placeholders})
                    ORDER BY page_number ASC, length(content) ASC
                    LIMIT %s
                """,
                [*doc_ids, top_k],
            )
            for row in cur.fetchall():
                content = row[3] or ""
                if title not in content and not any(term in content for term in terms):
                    continue
                cid = f"appendix_standard_{row[0]}"
                if cid in seen_ids:
                    continue
                seen_ids.add(cid)
                results.append(
                    {
                        "chunk_id": cid,
                        "doc_id": str(row[1] or ""),
                        "page_number": row[2] or 1,
                        "source_db": "appendix_standard_text",
                        "content": content,
                        "score": 0.94,
                        "metadata": {"standard_title": title, "query_terms": terms},
                    }
                )

    return results[:top_k]


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

    patterns = [
        rf"{re.escape(material_name)}\s*\n(?P<unit>[A-Za-z0-9㎡mM\?³²/\"]{{1,8}})\s*\n(?P<price>\d+\.\d{{2}})",
        rf"{re.escape(material_name)}\s+(?P<unit>[A-Za-z0-9㎡mM\?³²/\"]{{1,8}})\s+(?P<price>\d+\.\d{{2}})",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw_text)
        if match:
            unit = _normalize_material_unit(material_name, match.group("unit"))
            return unit, match.group("price")
    return None


def _query_material_text_fallback(
    conn,
    material_name: str,
    year_month: str,
    top_k: int = 5,
) -> list[dict]:
    period_label = _build_price_period_label(year_month)
    year_month_norm = _normalize_year_month(year_month)
    if not period_label or not material_name.strip() or not year_month_norm:
        return []

    with conn.cursor() as cur:
        cur.execute(
            """
                SELECT DISTINCT doc_id, page_number
                FROM text_chunks
                WHERE content ILIKE %s
                  AND content ILIKE %s
                ORDER BY page_number
                LIMIT %s
            """,
            (f"%{period_label}%", f"%{material_name}%", max(top_k * 6, 18)),
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

        combined_content = "\n".join((row[1] or "") for row in page_rows)
        parsed = _extract_material_price_from_ocr_page(combined_content, material_name)
        if not parsed:
            continue

        unit, price = parsed
        results.append(
            _with_retrieval_path(
                {
                    "chunk_id": f"text_material_{doc_id}_{page_number}_{material_name}",
                    "doc_id": doc_id or "",
                    "page_number": page_number or 1,
                    "source_db": "text_material_fallback",
                    "content": f"{material_name} 单位:{unit} 价格:{price}元 期间:{year_month_norm}",
                    "score": 0.85,
                    "metadata": {
                        "year_month": year_month_norm,
                        "unit": unit,
                        "price": price,
                    },
                },
                RETRIEVAL_PATH_PDF_PAGE,
                evidence_kind="pdf_page_table_row",
                route_stage="secondary",
            )
        )
        if len(results) >= top_k:
            break

    return results


def _query_material_page_fallback(
    conn,
    material_name: str,
    year_month: str,
    top_k: int = 3,
) -> list[dict]:
    period_label = _build_price_period_label(year_month)
    year_month_norm = _normalize_year_month(year_month)
    if not period_label or not material_name.strip() or not year_month_norm:
        return []

    with conn.cursor() as cur:
        cur.execute(
            """
                SELECT DISTINCT doc_id, page_number
                FROM text_chunks
                WHERE content ILIKE %s
                  AND content ILIKE %s
                ORDER BY page_number
                LIMIT %s
            """,
            (f"%{period_label}%", f"%{material_name}%", max(top_k * 4, 8)),
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

        combined_content = "\n".join((row[1] or "") for row in page_rows).strip()
        if not combined_content:
            continue
        results.append(
            _with_retrieval_path(
                {
                    "chunk_id": f"text_page_{doc_id}_{page_number}_{material_name}",
                    "doc_id": doc_id or "",
                    "page_number": page_number or 1,
                    "source_db": "text_page_fallback",
                    "content": (
                        f"{material_name} 价格走势 期间:{year_month_norm} 证据页：\n"
                        f"{combined_content[:1800]}"
                    ),
                    "score": 0.82,
                    "metadata": {
                        "year_month": year_month_norm,
                    },
                },
                RETRIEVAL_PATH_PDF_PAGE,
                evidence_kind="pdf_page_chunk",
                route_stage="secondary",
            )
        )
        if len(results) >= top_k:
            break

    return results


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
                _with_retrieval_path(
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
                    },
                    RETRIEVAL_PATH_OCR_JSON,
                    evidence_kind="ocr_json_row",
                    route_stage="tertiary",
                )
            )
            return results

    return results


def _pick_consistent_spec_trend(raw_rows: list[tuple]) -> list[tuple]:
    """Select the most prevalent (specification, unit) combo across months.

    Groups raw rows by (spec, unit), picks the combo that spans the most
    distinct months (ties broken by higher avg price), and returns only
    rows matching that combo.  This prevents apples-to-oranges trend lines
    where different products (e.g. per-unit cable vs per-metre cable) are
    averaged together.
    """
    if not raw_rows:
        return []

    # Group rows by (spec_or_name, unit)
    from collections import defaultdict
    groups: dict[tuple[str, str], list[tuple]] = defaultdict(list)
    for r in raw_rows:
        year_month, avg_price, unit, spec_or_name, n = r
        key = (spec_or_name or "", unit or "")
        groups[key].append(r)

    if not groups:
        return []

    def _combo_score(kv):
        (spec_or_name, unit), group_rows = kv
        distinct_months = len({r[0] for r in group_rows})
        total_n = sum(r[4] for r in group_rows)
        avg_p = sum(float(r[1] or 0) for r in group_rows) / max(len(group_rows), 1)
        # Prefer combos with non-empty spec/unit
        has_both = 1 if (spec_or_name and unit) else 0
        return (distinct_months, has_both, total_n, avg_p)

    best_key = max(groups.items(), key=_combo_score)[0]
    return groups[best_key]


def _annotate_month_average_deltas(chunks: list[dict], *, comparability_mode: bool = False) -> None:
    """Add month-over-month deltas to chunks built from monthly average points."""
    previous_avg: float | None = None
    previous_unit = ""

    for chunk in chunks:
        metadata = chunk.get("metadata") or {}
        year_month = str(metadata.get("year_month") or "").strip()
        if not year_month or year_month == "*":
            continue

        avg_value = metadata.get("avg_price")
        if avg_value is None:
            avg_value = metadata.get("price")
        if avg_value is None:
            continue

        try:
            avg_price = float(avg_value)
        except (TypeError, ValueError):
            previous_avg = None
            previous_unit = ""
            continue

        unit = str(metadata.get("unit") or "").strip()
        if previous_avg is not None and unit == previous_unit:
            delta_value = avg_price - previous_avg
            # Issue #121: Safe delta calculation with explicit zero handling
            if previous_avg == 0:
                if avg_price == 0:
                    # Both zero: no change
                    delta_percent = 0.0
                    trend_direction = "flat"
                else:
                    # From 0 to non-zero: infinite growth (cap at special marker)
                    delta_percent = float('inf') if avg_price > 0 else float('-inf')
                    trend_direction = "up" if avg_price > 0 else "down"
                    logger.warning(
                        f"[delta_calc] price surge from 0: {previous_avg} → {avg_price}, "
                        f"delta_percent=inf"
                    )
            else:
                delta_percent = (delta_value / previous_avg * 100.0)
                trend_direction = "up" if delta_value > 0 else "down" if delta_value < 0 else "flat"

            metadata["delta"] = round(delta_value, 6)
            # Store infinity as None in JSON (JSON doesn't support inf)
            if delta_percent == float('inf') or delta_percent == float('-inf'):
                metadata["delta_percent"] = None
                metadata["delta_percent_overflow"] = "infinity"
            else:
                metadata["delta_percent"] = round(delta_percent, 4)
            metadata["trend_direction"] = trend_direction
            if comparability_mode:
                metadata["comparability_basis"] = "month_average_estimate"
            chunk["metadata"] = metadata

            content = str(chunk.get("content") or "").rstrip()
            if "环比变化:" not in content:
                content += f" 环比变化:{delta_value:+.2f}"
                if delta_percent is not None:
                    content += f" 环比幅度:{delta_percent:+.2f}%"
                content += f" 趋势:{trend_direction}"
                if comparability_mode:
                    content += " 口径:按月均价估算，跨月样本规格存在差异"
                chunk["content"] = content

        previous_avg = avg_price
        previous_unit = unit


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
            _with_retrieval_path(
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
                },
                RETRIEVAL_PATH_PDF_PAGE,
                evidence_kind="pdf_page_table_row",
                route_stage="secondary",
            )
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
    requested_years = _extract_requested_standard_years(q)

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
                    if requested_years:
                        placeholders = ",".join(["%s"] * len(requested_years))
                        cur.execute(
                            f"""
                                SELECT id, doc_id, fee_name, fee_category,
                                       rate_min, rate_max, rate_recommended,
                                       applicable_scope, base_formula, source_text, standard_year,
                                       calc_base
                                FROM fee_rates
                                WHERE standard_year IN ({placeholders})
                                  AND (
                                       fee_name ILIKE %s OR fee_category ILIKE %s
                                       OR source_text ILIKE %s
                                  )
                                LIMIT %s
                            """,
                            [*requested_years, f"%{frag}%", f"%{frag}%", f"%{frag}%", top_k],
                        )
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
                    formula_display = formula or ""
                    scope_display = scope or ""
                    # When structured fields are missing, append source_text so LLM can parse raw data
                    source_snippet = ""
                    if (not formula_display or not scope_display or not cbase) and src:
                        source_snippet = f"\n原文摘录：{src[:300]}"
                    content_text = (
                        f"【{yr}版费率标准】{fname}（{fcat}）\n"
                        f"费率参考范围：{rmin_s}～{rmax_s}，推荐费率：{rrec_s}（单位：%，使用时÷100）\n"
                        f"计算公式：{formula_display or '（见原文摘录）'}\n"
                        f"计算基数：{cbase or '（见原文摘录）'}\n"
                        f"适用范围：{scope_display or '（见原文摘录）'}"
                        f"{source_snippet}"
                    ).strip()
                    results.append({
                        "chunk_id": cid,
                        "doc_id": str(fdoc_id or ""),
                        "page_number": 1,
                        "source_db": "fee_rates",
                        "content": content_text[:500],
                        "score": 0.90,
                        "metadata": {
                            "fee_name": fname,
                            "retrieval_path": RETRIEVAL_PATH_DATABASE,
                            "evidence_kind": "structured_row",
                            "route_stage": "primary",
                        },
                        "retrieval_path": RETRIEVAL_PATH_DATABASE,
                    })
    except Exception as e:
        logger.error(f"[_query_structured_tables] fee_rates error: {e}")
    finally:
        if conn is not None:
            _put_pg_conn(conn)
    return results


# ── Time validation helpers (Issue #121) ─────────────────────────────────────
def _validate_and_normalize_time_range(
    start_month: str,
    end_month: str,
    material_name: str = "",
    max_span_years: int = 10
) -> tuple[str, str]:
    """
    Validate and normalize time range for price queries.
    
    Fixes Issue #121: Price query time validation
    - Auto-correct reversed time ranges
    - Validate against future dates
    - Enforce max time span
    - Provide clear error messages
    
    Args:
        start_month: Start month in 'YYYY-MM' format
        end_month: End month in 'YYYY-MM' format
        material_name: Material name for error messages
        max_span_years: Maximum allowed time span in years
        
    Returns:
        Tuple of (corrected_start_month, corrected_end_month)
        
    Raises:
        ValueError: If time range is invalid
    """
    current_date = datetime.now()
    current_month_str = current_date.strftime("%Y-%m")
    
    # Validate format and parse
    def parse_month(month_str: str, label: str) -> datetime | None:
        if not month_str:
            return None
        try:
            return datetime.strptime(month_str, "%Y-%m")
        except ValueError:
            raise ValueError(
                f"Invalid {label} format: '{month_str}'. Expected 'YYYY-MM' (e.g., '2025-01')"
            )
    
    start_dt = parse_month(start_month, "start_month")
    end_dt = parse_month(end_month, "end_month")
    
    # If both are provided, validate and potentially swap
    if start_dt and end_dt:
        # Auto-correct reversed order
        if start_dt > end_dt:
            logger.warning(
                f"[time_validation] Reversed time range: {start_month} > {end_month}. "
                f"Auto-correcting to {end_month} → {start_month}"
            )
            start_month, end_month = end_month, start_month
            start_dt, end_dt = end_dt, start_dt
        
        # Validate time span
        span_months = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)
        if span_months > max_span_years * 12:
            raise ValueError(
                f"Time span too large: {span_months} months ({span_months // 12} years). "
                f"Maximum allowed: {max_span_years} years"
            )
    
    # Validate against future dates
    for month_str, dt, label in [
        (start_month, start_dt, "start_month"),
        (end_month, end_dt, "end_month")
    ]:
        if dt and dt > current_date:
            raise ValueError(
                f"Cannot query future {label}: '{month_str}'. "
                f"Current month: {current_month_str}"
            )
    
    return start_month, end_month


def _query_trend_points(
    conn,
    material_name: str,
    start_month: str = "",
    end_month: str = "",
) -> list[tuple]:
    normalized_material = re.sub(r"\s+", "", (material_name or "")).replace("～", "~")
    if not normalized_material:
        return []

    where_parts = [
        "(normalized_material = %s OR material_name ILIKE %s)",
    ]
    params: list = [normalized_material, f"%{material_name}%"]
    if start_month:
        where_parts.append("year_month >= %s")
        params.append(start_month)
    if end_month:
        where_parts.append("year_month <= %s")
        params.append(end_month)

    where_sql = "WHERE " + " AND ".join(where_parts)
    with conn.cursor() as cur:
        try:
            cur.execute(
                f"""
                SELECT tp.id, tp.year_month, tp.value, tp.unit,
                       COALESCE(tp.source_table_page, tp.source_chart_page, 1) AS page_number,
                       COALESCE(tp.source_doc_id, 'trend_points') AS doc_id,
                       tp.material_name,
                       tr.delta_value,
                       tr.delta_percent,
                       tr.trend_direction
                FROM trend_points tp
                LEFT JOIN trend_relations tr
                  ON tr.to_point_id = tp.id
                {where_sql}
                ORDER BY tp.year_month ASC
                LIMIT 48
                """,
                params,
            )
        except Exception:
            return []
        return cur.fetchall()


# ── 新工具：pg_vector_search（PG pgvector）──────────────────────────────────


def _run_coro_sync(coro):
    """在同步工具函数里安全执行异步适配器调用。"""
    result_holder: dict[str, object] = {}
    error_holder: dict[str, Exception] = {}

    def _runner() -> None:
        try:
            result_holder["value"] = asyncio.run(coro)
        except Exception as exc:  # pragma: no cover - error path is surfaced to caller
            error_holder["error"] = exc

    worker = _threading.Thread(target=_runner, daemon=True)
    worker.start()
    worker.join()

    if "error" in error_holder:
        raise error_holder["error"]
    return result_holder.get("value")


def _milvus_vector_results(query: str, top_k: int) -> list[dict]:
    vector_backend = get_runtime_override("vector_backend", None)
    if vector_backend == "pgvector":
        return []
    try:
        vector_config = AppConfig().vector_store
    except Exception as e:
        logger.warning(f"[vector_search] failed to load vector store config: {e}")
        return []

    if vector_backend == "milvus":
        vector_config.type = "milvus"
    if vector_config.type != "milvus":
        return []

    try:
        adapter = create_vector_store_adapter(vector_config)
    except Exception as e:
        logger.warning(f"[vector_search] failed to create vector adapter: {e}")
        return []

    if not adapter.is_available():
        logger.warning("[vector_search] milvus adapter unavailable, falling back to pgvector")
        return []

    query_embedding = _get_embedding(query.strip())
    if not query_embedding:
        return []

    try:
        documents = _run_coro_sync(
            adapter.search(np.asarray(query_embedding, dtype=float), top_k=top_k, score_threshold=0.40)
        )
    except Exception as e:
        logger.warning(f"[vector_search] milvus search failed, falling back to pgvector: {e}")
        return []

    if not isinstance(documents, list):
        return []

    results = []
    for document, score in documents:
        results.append(
            _with_retrieval_path(
                {
                    "chunk_id": str(document.id),
                    "doc_id": str(document.doc_id or ""),
                    "page_number": document.page or 1,
                    "source_db": "milvus",
                    "content": document.content or "",
                    "score": round(float(score or 0), 4),
                    "metadata": {
                        "title": document.title,
                        "section": document.section,
                        "chunk_type": document.chunk_type,
                        **document.metadata,
                    },
                },
                RETRIEVAL_PATH_VECTOR,
                evidence_kind="vector_chunk",
                route_stage="primary",
            )
        )
    return results


@tool
def vector_search(query: str, top_k: int = RetrievalPresets.STANDARD) -> str:  # Issue #116: 10 → STANDARD (8)
    """向量语义搜索：从 text_chunks 表中使用 pgvector 余弦相似度检索"""
    if not query.strip():
        return json.dumps([])

    conn = None
    try:
        effective_top_k = int(get_runtime_override("top_k", top_k)) if top_k == RetrievalPresets.STANDARD else top_k
        score_threshold = float(get_runtime_override("score_threshold", 0.40))
        milvus_results = (
            _milvus_vector_results(query, effective_top_k)
            if _effective_vector_backend() == "milvus"
            else []
        )
        if milvus_results:
            return json.dumps(milvus_results, ensure_ascii=False)

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
                  AND 1 - (embedding <=> %s::vector) >= %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """, (query_embedding, query_embedding, score_threshold, query_embedding, effective_top_k))

            rows = cur.fetchall()
            results = []
            for row in rows:
                results.append(
                    _with_retrieval_path(
                        {
                            "chunk_id": f"tc_{row[0]}",
                            "doc_id": str(row[1] or ""),
                            "page_number": row[2] or 1,
                            "source_db": "pgvector",
                            "content": row[3] or "",
                            "score": round(float(row[4] or 0), 4),
                            "metadata": {"vector_backend": "pgvector"},
                        },
                        RETRIEVAL_PATH_VECTOR,
                        evidence_kind="vector_chunk",
                        route_stage="primary",
                    )
                )
            return json.dumps(results, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[vector_search] error: {e}")
        return json.dumps([])
    finally:
        if conn is not None:
            _put_pg_conn(conn)


@tool
def concept_search(query: str, top_k: int = RetrievalPresets.FOCUSED, include_evidence: bool = True) -> str:  # Issue #116: 6 → FOCUSED (5)
    """概念命中并递归下钻证据：返回概念节点，并可扩展结构化/OCR/PDF 页级证据。"""
    if not query.strip():
        return json.dumps([])

    conn = None
    try:
        conn = _get_pg_conn()
        concept_hits = _load_concept_hits(conn, query.strip(), top_k)
        expanded_hits: list[dict] = []
        if include_evidence and concept_hits:
            expanded_hits = _expand_concept_hits(
                conn,
                query.strip(),
                concept_hits,
                top_k=max(1, min(3, top_k)),
            )

        combined: list[dict] = []
        seen_ids: set[str] = set()
        for item in [*concept_hits, *expanded_hits]:
            cid = str(item.get("chunk_id") or "")
            if not cid or cid in seen_ids:
                continue
            seen_ids.add(cid)
            combined.append(item)

        max_results = top_k if not include_evidence else max(top_k, min(top_k * 2, len(combined)))
        return json.dumps(combined[:max_results], ensure_ascii=False)
    except Exception as e:
        logger.error(f"[concept_search] error: {e}")
        return json.dumps([])
    finally:
        if conn is not None:
            _put_pg_conn(conn)


# ── 新工具：keyword_search（PG tsvector 全文检索）────────────────────────────


@tool
def keyword_search(query: str, top_k: int = RetrievalPresets.STANDARD) -> str:  # Issue #116: 10 → STANDARD (8)
    """关键词全文搜索：从 text_chunks 表中使用 PostgreSQL tsvector + ts_rank 检索"""
    if not query.strip():
        return json.dumps([])

    # ── ES backend (BM25 + IK 分词) — drop-in replacement when KEYWORD_BACKEND=es ──
    es_results: list = []
    try:
        from infrastructure import elasticsearch_store as _es

        if _es.is_enabled():
            es_results = _es.search(query, top_k=top_k)
            if es_results:
                tagged = [
                    _with_retrieval_path(
                        {**r, "score": round(float(r.get("score") or 0), 4)},
                        RETRIEVAL_PATH_DATABASE,
                        evidence_kind="fulltext_chunk",
                        route_stage="primary",
                    )
                    for r in es_results
                ]
                logger.info("[keyword_search] ES backend returned %d hits", len(tagged))
                # Continue to structured tables enrichment below using PG
                conn = None
                try:
                    conn = _get_pg_conn()
                    seen = {r.get("chunk_id") for r in tagged}
                    for chunk in _query_fee_formula_text_chunks(conn, query, top_k):
                        if chunk["chunk_id"] not in seen:
                            tagged.append(chunk)
                            seen.add(chunk["chunk_id"])
                    for chunk in _query_fee_comparison_text_chunks(conn, query, top_k):
                        if chunk["chunk_id"] not in seen:
                            tagged.append(chunk)
                            seen.add(chunk["chunk_id"])
                    for chunk in _query_appendix_standard_text_chunks(conn, query, top_k):
                        if chunk["chunk_id"] not in seen:
                            tagged.append(chunk)
                            seen.add(chunk["chunk_id"])
                    for chunk in _query_fill_requirement_text_chunks(conn, query, top_k):
                        if chunk["chunk_id"] not in seen:
                            tagged.append(chunk)
                            seen.add(chunk["chunk_id"])
                    if _should_include_structured_tables(query):
                        tagged.extend(_query_structured_tables(query, top_k))
                    for chunk in _query_text_chunks_literal(conn, query, top_k):
                        if chunk["chunk_id"] not in seen:
                            tagged.append(chunk)
                            seen.add(chunk["chunk_id"])
                finally:
                    if conn is not None:
                        _put_pg_conn(conn)
                return json.dumps(tagged, ensure_ascii=False)
            # if ES enabled but returned 0 hits, fall through to PG (defensive)
            logger.info("[keyword_search] ES returned 0 hits, falling back to PG")
    except Exception as _es_exc:
        logger.warning("[keyword_search] ES backend error, falling back to PG: %s", _es_exc)

    conn = None
    try:
        conn = _get_pg_conn()
        ts_cfg = _resolve_text_search_config(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, doc_id, page_number, content,
                       ts_rank(to_tsvector('{ts_cfg}', content), plainto_tsquery('{ts_cfg}', %s)) AS score
                FROM text_chunks
                WHERE to_tsvector('{ts_cfg}', content) @@ plainto_tsquery('{ts_cfg}', %s)
                ORDER BY score DESC
                LIMIT %s
                """,
                (query, query, top_k),
            )

            rows = cur.fetchall()
            results = []
            for row in rows:
                results.append(
                    _with_retrieval_path(
                        {
                            "chunk_id": f"tc_{row[0]}",
                            "doc_id": str(row[1] or ""),
                            "page_number": row[2] or 1,
                            "source_db": "pg_fulltext",
                            "content": row[3] or "",
                            "score": round(float(row[4] or 0), 4),
                            "metadata": {},
                        },
                        RETRIEVAL_PATH_DATABASE,
                        evidence_kind="fulltext_chunk",
                        route_stage="primary",
                    )
                )

        # also query fee_rates and other structured tables
        for chunk in _query_fee_formula_text_chunks(conn, query, top_k):
            if chunk["chunk_id"] not in {r.get("chunk_id") for r in results}:
                results.append(chunk)
        for chunk in _query_fee_comparison_text_chunks(conn, query, top_k):
            if chunk["chunk_id"] not in {r.get("chunk_id") for r in results}:
                results.append(chunk)
        for chunk in _query_appendix_standard_text_chunks(conn, query, top_k):
            if chunk["chunk_id"] not in {r.get("chunk_id") for r in results}:
                results.append(chunk)
        for chunk in _query_fill_requirement_text_chunks(conn, query, top_k):
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
def category_search(query: str, top_k: int = RetrievalPresets.FOCUSED) -> str:  # Issue #116: 5 → FOCUSED (5) ✓
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
            # Split multi-token queries (space-separated) for token-level matching
            tokens = [t.strip() for t in q.split() if len(t.strip()) >= 2]
            primary_token = tokens[0] if tokens else q

            # 策略1：phrase ILIKE on full query (exact phrase match), limit < 600
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

            # 策略3：primary token ILIKE when multi-token phrase fails (e.g. "玻璃地板 楼梯面层")
            if not rows and primary_token != q:
                cur.execute("""
                    SELECT id, doc_id, page_number, content,
                           length(content) AS char_len
                    FROM text_chunks
                    WHERE content ILIKE %s
                    ORDER BY
                        CASE WHEN content ~ '[0-9]+\\.[0-9]+(\\.[0-9]+)*'
                                  OR content ~ '（[一二三四五六七八九十0-9]+）'
                             THEN 0 ELSE 1 END,
                        length(content)
                    LIMIT %s
                """, (f"%{primary_token}%", top_k))
                rows = cur.fetchall()

        results = []
        sec_re = re.compile(r'(\d+\.\d+(?:\.\d+)*)')
        for row in rows:
            content = row[3] or ""
            # 从内容中提取章节编号
            sec_match = sec_re.search(content)
            section_number = sec_match.group(1) if sec_match else ""
            results.append(
                _with_retrieval_path(
                    {
                        "chunk_id": f"cat_{row[0]}",
                        "doc_id": str(row[1] or ""),
                        "page_number": row[2] or 1,
                        "section": section_number,
                        "content": content[:300],
                        "score": 1.0,
                    },
                    RETRIEVAL_PATH_PDF_PAGE,
                    evidence_kind="pdf_catalog_chunk",
                    route_stage="fallback",
                )
            )

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
        for chunk in _query_fee_comparison_text_chunks(conn, query, top_k):
            results.append({
                "chunk_id": chunk["chunk_id"],
                "doc_id": chunk["doc_id"],
                "page_number": chunk["page_number"],
                "section": chunk.get("metadata", {}).get("item", ""),
                "content": chunk["content"][:300],
                "score": chunk["score"],
            })
        for chunk in _query_appendix_standard_text_chunks(conn, query, top_k):
            results.append({
                "chunk_id": chunk["chunk_id"],
                "doc_id": chunk["doc_id"],
                "page_number": chunk["page_number"],
                "section": chunk.get("metadata", {}).get("standard_title", ""),
                "content": chunk["content"][:300],
                "score": chunk["score"],
            })
        for chunk in _query_fill_requirement_text_chunks(conn, query, top_k):
            results.append({
                "chunk_id": chunk["chunk_id"],
                "doc_id": chunk["doc_id"],
                "page_number": chunk["page_number"],
                "section": chunk.get("metadata", {}).get("field_name", ""),
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


# ── graph_search（概念图入口）────────────────────────────────────────


@tool
def graph_search(query: str, top_k: int = 10) -> str:
    """知识图谱搜索：复用概念图命中与证据下钻，但显式标记 graph 路由。"""
    if not query.strip():
        return json.dumps([])

    try:
        concept_tool = getattr(concept_search, "func", None)
        if concept_tool is None:
            return json.dumps([])

        concept_results = json.loads(concept_tool(query, top_k=top_k, include_evidence=True))
        graph_results = []
        for item in concept_results:
            rewritten = dict(item)
            metadata = dict(rewritten.get("metadata") or {})
            metadata["graph_entry_query"] = query
            rewritten["metadata"] = metadata
            rewritten["retrieval_path"] = RETRIEVAL_PATH_GRAPH
            graph_results.append(rewritten)

        logger.info(f"[graph_search] query='{query}' hits={len(graph_results)}")
        return json.dumps(graph_results, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[graph_search] error: {e}")
        return json.dumps([])


@tool
def topology_search(query: str, top_k: int = 10, max_depth: int = 2) -> str:
    """拓扑遍历搜索：返回概念锚点及受限深度的关联证据，并显式标记停止原因。"""
    if not query.strip():
        return json.dumps([])

    conn = None
    bounded_depth = max(1, min(4, int(max_depth or 1)))
    anchor_limit = max(1, min(4, int(top_k or 1)))
    expansion_limit = max(1, min(4, int(top_k or 1)))
    try:
        conn = _get_pg_conn()
        concept_hits = _load_concept_hits(conn, query.strip(), top_k=anchor_limit)
        expanded_hits = _expand_concept_hits(
            conn,
            query.strip(),
            concept_hits,
            top_k=expansion_limit,
            recursive_depth=bounded_depth,
        ) if concept_hits else []

        expanded_anchor_ids = {
            str((item.get("metadata") or {}).get("parent_concept_id") or "")
            for item in expanded_hits
            if (item.get("metadata") or {}).get("parent_concept_id")
        }

        rewritten_anchors: list[dict] = []
        for anchor in concept_hits:
            rewritten = dict(anchor)
            metadata = dict(rewritten.get("metadata") or {})
            anchor_id = str(rewritten.get("chunk_id") or "")
            metadata["topology_role"] = "anchor"
            metadata["topology_depth"] = 0
            metadata["topology_anchor_id"] = anchor_id
            metadata["topology_max_depth"] = bounded_depth
            metadata["stop_reason"] = "expanded" if anchor_id in expanded_anchor_ids else "anchor_only"
            rewritten["metadata"] = metadata
            rewritten["retrieval_path"] = RETRIEVAL_PATH_TOPOLOGY
            rewritten_anchors.append(rewritten)

        expansions_by_anchor: dict[str, list[dict]] = {}
        orphan_expansions: list[dict] = []
        for item in expanded_hits:
            rewritten = dict(item)
            metadata = dict(rewritten.get("metadata") or {})
            graph_depth = int(metadata.get("graph_depth") or 0)
            parent_anchor_id = str(metadata.get("parent_concept_id") or "")
            metadata["topology_role"] = "evidence"
            metadata["topology_depth"] = graph_depth
            metadata["topology_anchor_id"] = parent_anchor_id
            metadata["topology_max_depth"] = bounded_depth
            if graph_depth >= bounded_depth:
                metadata["stop_reason"] = "max_depth_reached"
            elif graph_depth <= 0:
                metadata["stop_reason"] = "direct_evidence"
            else:
                metadata["stop_reason"] = "evidence_collected"
            rewritten["metadata"] = metadata
            rewritten["retrieval_path"] = RETRIEVAL_PATH_TOPOLOGY
            if parent_anchor_id:
                expansions_by_anchor.setdefault(parent_anchor_id, []).append(rewritten)
            else:
                orphan_expansions.append(rewritten)

        ordered: list[dict] = []
        deferred: list[dict] = []
        for anchor in rewritten_anchors:
            anchor_id = str(anchor.get("chunk_id") or "")
            ordered.append(anchor)
            anchor_expansions = expansions_by_anchor.pop(anchor_id, [])
            if anchor_expansions:
                ordered.append(anchor_expansions[0])
                deferred.extend(anchor_expansions[1:])
        for remaining in expansions_by_anchor.values():
            deferred.extend(remaining)
        ordered.extend(orphan_expansions)
        ordered.extend(deferred)

        combined: list[dict] = []
        seen_ids: set[str] = set()
        for item in ordered:
            cid = str(item.get("chunk_id") or "")
            if not cid or cid in seen_ids:
                continue
            seen_ids.add(cid)
            combined.append(item)

        max_results = max(int(top_k or 1), min(len(combined), anchor_limit + expansion_limit))
        logger.info(
            "[topology_search] query='%s' anchors=%s expansions=%s depth=%s",
            query,
            len(rewritten_anchors),
            len(expanded_hits),
            bounded_depth,
        )
        return json.dumps(combined[:max_results], ensure_ascii=False)
    except Exception as e:
        logger.error(f"[topology_search] error: {e}")
        return json.dumps([])
    finally:
        if conn is not None:
            _put_pg_conn(conn)


# ── hybrid_search（PG 双路融合）─────────────────────────────────────────────


@tool
def hybrid_search(query: str, top_k: int = RetrievalPresets.STANDARD, path_constraint: str = "") -> str:  # Issue #116: 10 → STANDARD (8)
    """混合检索（pgvector + tsvector）：综合召回，适合复杂问题。

    Args:
        query: 检索关键词
        top_k: 返回结果数量
        path_constraint: 可选，章节路径前缀过滤（如 '第二册电气设备安装工程/10.%'）。
    """
    if not query.strip():
        return json.dumps([])

    conn = None
    started = time.perf_counter()
    path_filter_sql = "AND tc.path LIKE %s" if path_constraint else ""
    path_filter_params: tuple = (path_constraint,) if path_constraint else ()
    try:
        effective_top_k = int(get_runtime_override("top_k", top_k)) if top_k == RetrievalPresets.STANDARD else top_k
        cfg = _get_hybrid_runtime_config(effective_top_k)
        query_family = str((_concept_analyzer.analyze(query).get("intent") or "semantic"))
        cfg = _apply_query_family_routing(query_family, cfg, effective_top_k)
        milvus_vector_hits: list[dict] = []
        if not path_constraint and _effective_vector_backend() == "milvus":
            milvus_vector_hits = _milvus_vector_results(query, int(cfg["vector_fetch_k"]))
            for chunk in milvus_vector_hits:
                chunk["source_db"] = "hybrid_vector"
                metadata = dict(chunk.get("metadata") or {})
                metadata["vector_backend"] = "milvus"
                chunk["metadata"] = metadata
        query_embedding = _get_embedding(query.strip())
        conn = _get_pg_conn()
        has_chunk_vector_views = _table_available(conn, "public.chunk_vector_views")
        seen_ids: set[str] = set()
        vector_hits: list[dict] = []
        multivector_hits: list[dict] = []
        text_hits: list[dict] = []
        results: list[dict] = []
        observability = {
            "query_family": query_family,
            "top_k": int(effective_top_k),
            "vector_fetch_k": int(cfg["vector_fetch_k"]),
            "text_fetch_k": int(cfg["text_fetch_k"]),
            "rrf_rank_constant": int(cfg["rrf_rank_constant"]),
            "vector_min_score": float(cfg["vector_min_score"]),
            "vector_hits": 0,
            "multivector_hits": 0,
            "text_hits": 0,
            "rrf_hits": 0,
            "structured_hits": 0,
            "literal_hits": 0,
            "formula_hits": 0,
            "comparison_hits": 0,
            "appendix_hits": 0,
            "fill_hits": 0,
            "route_policy": cfg.get("route_policy", query_family),
            "vector_backend": "milvus" if milvus_vector_hits else "pgvector",
        }
        ts_cfg = _resolve_text_search_config(conn)

        with conn.cursor() as cur:
            if milvus_vector_hits:
                vector_hits.extend(milvus_vector_hits)
                observability["vector_hits"] = len(vector_hits)
            elif query_embedding:
                cur.execute("SET hnsw.ef_search = 100")
                try:
                    cur.execute(
                        f"""
                            SELECT id, doc_id, page_number, content,
                                   1 - (embedding <=> %s::vector) AS score
                            FROM text_chunks
                            WHERE embedding IS NOT NULL
                              AND 1 - (embedding <=> %s::vector) >= %s
                              {path_filter_sql.replace('tc.', '')}
                            ORDER BY embedding <=> %s::vector
                            LIMIT %s
                        """,
                        (
                            query_embedding,
                            query_embedding,
                            float(cfg["vector_min_score"]),
                            *path_filter_params,
                            query_embedding,
                            int(cfg["vector_fetch_k"]),
                        ),
                    )
                    for row in cur.fetchall():
                        vector_hits.append(
                            _with_retrieval_path(
                                {
                                    "chunk_id": f"tc_{row[0]}",
                                    "doc_id": str(row[1] or ""),
                                    "page_number": row[2] or 1,
                                    "source_db": "hybrid_vector",
                                    "content": row[3] or "",
                                    "score": round(float(row[4] or 0), 4),
                                    "metadata": {"vector_backend": "pgvector"},
                                },
                                RETRIEVAL_PATH_VECTOR,
                                evidence_kind="vector_chunk",
                                route_stage="primary",
                            )
                        )
                    observability["vector_hits"] = len(vector_hits)

                    if has_chunk_vector_views:
                        cur.execute(
                            """
                                SELECT
                                    cv.id,
                                    cv.chunk_id,
                                    cv.view_type,
                                    tc.doc_id,
                                    tc.page_number,
                                    tc.content,
                                    1 - (cv.embedding <=> %s::vector) AS score
                                FROM chunk_vector_views cv
                                JOIN text_chunks tc ON tc.id = cv.chunk_id
                                WHERE cv.embedding IS NOT NULL
                                  AND 1 - (cv.embedding <=> %s::vector) >= %s
                                ORDER BY cv.embedding <=> %s::vector
                                LIMIT %s
                            """,
                            (
                                query_embedding,
                                query_embedding,
                                float(cfg["vector_min_score"]),
                                query_embedding,
                                int(cfg["vector_fetch_k"]),
                            ),
                        )
                        for row in cur.fetchall():
                            multivector_hits.append(
                                _with_retrieval_path(
                                    {
                                        "chunk_id": f"tc_{row[1]}",
                                        "doc_id": str(row[3] or ""),
                                        "page_number": row[4] or 1,
                                        "source_db": "hybrid_multivector",
                                        "content": row[5] or "",
                                        "score": round(float(row[6] or 0), 4),
                                        "metadata": {
                                            "vector_backend": "pgvector",
                                            "vector_view_id": row[0],
                                            "vector_view_type": row[2] or "raw_chunk",
                                        },
                                    },
                                    RETRIEVAL_PATH_VECTOR,
                                    evidence_kind="multi_vector_parent",
                                    route_stage="primary",
                                )
                            )
                        observability["multivector_hits"] = len(multivector_hits)
                except Exception as e:
                    logger.error(f"[hybrid_search] vector error: {e}")
                    conn.rollback()
                    observability["vector_error"] = str(e)

            # Use stored tsv column (GIN index) when available (chinese config via zhparser),
            # fall back to inline to_tsvector for deployments without zhparser.
            _has_tsv_col = _table_has_column(conn, "text_chunks", "tsv")
            if _has_tsv_col:
                cur.execute(
                    f"""
                        SELECT id, doc_id, page_number, content,
                               ts_rank(tsv, plainto_tsquery('{ts_cfg}', %s)) AS score
                        FROM text_chunks
                        WHERE tsv @@ plainto_tsquery('{ts_cfg}', %s)
                        {path_filter_sql.replace('tc.', '')}
                        ORDER BY score DESC
                        LIMIT %s
                    """,
                    (query, query, *path_filter_params, int(cfg["text_fetch_k"])),
                )
            else:
                cur.execute(
                    f"""
                        SELECT id, doc_id, page_number, content,
                               ts_rank(to_tsvector('{ts_cfg}', content),
                                       plainto_tsquery('{ts_cfg}', %s)) AS score
                        FROM text_chunks
                        WHERE to_tsvector('{ts_cfg}', content) @@ plainto_tsquery('{ts_cfg}', %s)
                        {path_filter_sql.replace('tc.', '')}
                        ORDER BY score DESC
                        LIMIT %s
                    """,
                    (query, query, *path_filter_params, int(cfg["text_fetch_k"])),
                )
            for row in cur.fetchall():
                text_hits.append(
                    _with_retrieval_path(
                        {
                            "chunk_id": f"tc_{row[0]}",
                            "doc_id": str(row[1] or ""),
                            "page_number": row[2] or 1,
                            "source_db": "hybrid_text",
                            "content": row[3] or "",
                            "score": round(float(row[4] or 0), 4),
                            "metadata": {},
                        },
                        RETRIEVAL_PATH_DATABASE,
                        evidence_kind="fulltext_chunk",
                        route_stage="primary",
                    )
                )
            observability["text_hits"] = len(text_hits)

        # dense + sparse 融合：RRF
        ranked_lists = [vector_hits, multivector_hits, text_hits]
        fused_chunks = (
            _rrf_fuse_chunks(ranked_lists, rank_constant=int(cfg["rrf_rank_constant"]))
            if bool(cfg.get("rerank_enabled", True))
            else [chunk for ranked in ranked_lists for chunk in ranked]
        )
        for chunk in fused_chunks:
            cid = chunk.get("chunk_id")
            if cid and cid not in seen_ids:
                seen_ids.add(cid)
                metadata = dict(chunk.get("metadata") or {})
                metadata["query_family"] = query_family
                chunk["metadata"] = metadata
                results.append(chunk)
        observability["rrf_hits"] = len(results)

        for chunk in _query_fee_formula_text_chunks(conn, query, int(cfg["literal_top_k"])):
            if chunk["chunk_id"] not in seen_ids:
                seen_ids.add(chunk["chunk_id"])
                observability["formula_hits"] = int(observability["formula_hits"]) + 1
                results.append(chunk)
        for chunk in _query_fee_comparison_text_chunks(conn, query, int(cfg["literal_top_k"])):
            if chunk["chunk_id"] not in seen_ids:
                seen_ids.add(chunk["chunk_id"])
                observability["comparison_hits"] = int(observability["comparison_hits"]) + 1
                results.append(chunk)
        for chunk in _query_appendix_standard_text_chunks(conn, query, int(cfg["literal_top_k"])):
            if chunk["chunk_id"] not in seen_ids:
                seen_ids.add(chunk["chunk_id"])
                observability["appendix_hits"] = int(observability["appendix_hits"]) + 1
                results.append(chunk)
        for chunk in _query_fill_requirement_text_chunks(conn, query, int(cfg["literal_top_k"])):
            if chunk["chunk_id"] not in seen_ids:
                seen_ids.add(chunk["chunk_id"])
                observability["fill_hits"] = int(observability["fill_hits"]) + 1
                results.append(chunk)
        if _should_include_structured_tables(query):
            for chunk in _query_structured_tables(query, int(cfg["structured_top_k"])):
                if chunk["chunk_id"] not in seen_ids:
                    seen_ids.add(chunk["chunk_id"])
                    observability["structured_hits"] = int(observability["structured_hits"]) + 1
                    results.append(chunk)

        for chunk in _query_text_chunks_literal(conn, query, int(cfg["literal_top_k"]), path_constraint=path_constraint):
            if chunk["chunk_id"] not in seen_ids:
                seen_ids.add(chunk["chunk_id"])
                observability["literal_hits"] = int(observability["literal_hits"]) + 1
                results.append(chunk)

        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
        observability["elapsed_ms"] = elapsed_ms
        observability["total_candidates"] = len(results)
        _log_retrieval_observability("hybrid_search", observability)

        results.sort(
            key=lambda chunk: (
                float((chunk.get("metadata") or {}).get("rrf_score", 0.0) or 0.0),
                float(chunk.get("score", 0.0) or 0.0),
            ),
            reverse=True,
        )
        for rank, chunk in enumerate(results, start=1):
            metadata = dict(chunk.get("metadata") or {})
            metadata["hybrid_rank"] = rank
            metadata["query_family"] = query_family
            metadata["hybrid_elapsed_ms"] = elapsed_ms
            chunk["metadata"] = metadata
        return json.dumps(results[:effective_top_k], ensure_ascii=False)
    except Exception as e:
        logger.error(f"[hybrid_search] error: {e}")
        _log_retrieval_observability(
            "hybrid_search_failed",
            {
                "query": query.strip(),
                "top_k": int(top_k),
                "error": str(e),
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2),
            },
        )
        return json.dumps([])
    finally:
        if conn is not None:
            _put_pg_conn(conn)


# ── text_search（PG 语义搜索，保留原名兼容）───────────────────────────────────


@tool
def text_search(query: str, top_k: int = RetrievalPresets.STANDARD, path_constraint: str = "") -> str:  # Issue #116: 8 → STANDARD (8) ✓
    """语义向量搜索+全文检索：从 text_chunks 表中检索。

    Args:
        query: 检索关键词
        top_k: 返回结果数量
        path_constraint: 可选，章节路径前缀过滤（如 '第二册电气设备安装工程/10.%'），
                         限定检索范围到特定章节，避免跨册噪声。
    """
    if not query.strip():
        return json.dumps([])

    # ── tracking number: every text_search call gets a short ID so log lines
    # for FTS / vector / structured can be correlated with this exact invocation.
    trace_id = uuid.uuid4().hex[:8]
    logger.info(
        f"[text_search][{trace_id}] query={query!r} top_k={top_k} "
        f"path_constraint={path_constraint!r}"
    )

    results = []
    seen_ids = set()
    conn = None
    fts_count = 0
    vec_count = 0
    structured_count = 0
    # Build optional path filter clause (parameterized, injection-safe)
    path_filter_sql = "AND path LIKE %s" if path_constraint else ""
    path_filter_params: tuple = (path_constraint,) if path_constraint else ()
    try:
        conn = _get_pg_conn()
        ts_cfg = _resolve_text_search_config(conn)

        # 1. Full-text search (to_tsvector)
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT id, doc_id, page_number, content,
                           ts_rank(to_tsvector('{ts_cfg}', content), plainto_tsquery('{ts_cfg}', %s)) AS score,
                           file_name, path, metadata
                    FROM text_chunks
                    WHERE to_tsvector('{ts_cfg}', content) @@ plainto_tsquery('{ts_cfg}', %s)
                    {path_filter_sql}
                    ORDER BY score DESC
                    LIMIT %s
                """, (query, query, *path_filter_params, top_k))
                for row in cur.fetchall():
                    if row[0] not in seen_ids:
                        seen_ids.add(row[0])
                        fts_count += 1
                        results.append(
                            _with_retrieval_path(
                                {
                                    "chunk_id": f"tc_{row[0]}",
                                    "doc_id": str(row[1] or ""),
                                    "page_number": row[2] or 1,
                                    "source_db": "pg_fulltext",
                                    "content": row[3] or "",
                                    "score": round(float(row[4] or 0), 4),
                                    "doc_filename": row[5] or "",
                                    "file_name": row[5] or "",
                                    "path": row[6] or "",
                                    "metadata": dict(row[7] or {}),
                                },
                                RETRIEVAL_PATH_DATABASE,
                                evidence_kind="fulltext_chunk",
                                route_stage="primary",
                            )
                        )
        except Exception as e:
            logger.error(f"[text_search] fulltext error: {e}")

        # 2. Vector search if embedding available
        try:
            query_embedding = _get_embedding(query.strip())
            if query_embedding:
                with conn.cursor() as cur:
                    cur.execute("SET hnsw.ef_search = 100")
                    cur.execute(f"""
                        SELECT id, doc_id, page_number, content,
                               1 - (embedding <=> %s::vector) AS score
                        FROM text_chunks
                        WHERE embedding IS NOT NULL
                          AND 1 - (embedding <=> %s::vector) >= 0.40
                          {path_filter_sql}
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                    """, (query_embedding, query_embedding, *path_filter_params, query_embedding, top_k))
                    for row in cur.fetchall():
                        if row[0] not in seen_ids:
                            seen_ids.add(row[0])
                            vec_count += 1
                            results.append(
                                _with_retrieval_path(
                                    {
                                        "chunk_id": f"tc_{row[0]}",
                                        "doc_id": str(row[1] or ""),
                                        "page_number": row[2] or 1,
                                        "source_db": "pgvector",
                                        "content": row[3] or "",
                                        "score": round(float(row[4] or 0), 4),
                                        "metadata": {},
                                    },
                                    RETRIEVAL_PATH_DATABASE,
                                    evidence_kind="vector_chunk",
                                    route_stage="primary",
                                )
                            )
        except Exception as e:
            logger.error(f"[text_search] vector error: {e}")
            if conn is not None:
                conn.rollback()

        # 3. fee_rates and other structured tables — score 0.9, always passes filter
        for chunk in _query_fee_formula_text_chunks(conn, query, top_k):
            if chunk["chunk_id"] not in seen_ids:
                seen_ids.add(chunk["chunk_id"])
                results.append(chunk)
        for chunk in _query_fee_comparison_text_chunks(conn, query, top_k):
            if chunk["chunk_id"] not in seen_ids:
                seen_ids.add(chunk["chunk_id"])
                results.append(chunk)
        for chunk in _query_appendix_standard_text_chunks(conn, query, top_k):
            if chunk["chunk_id"] not in seen_ids:
                seen_ids.add(chunk["chunk_id"])
                results.append(chunk)
        for chunk in _query_fill_requirement_text_chunks(conn, query, top_k):
            if chunk["chunk_id"] not in seen_ids:
                seen_ids.add(chunk["chunk_id"])
                results.append(chunk)
        if _should_include_structured_tables(query):
            for chunk in _query_structured_tables(query, top_k):
                if chunk["chunk_id"] not in seen_ids:
                    seen_ids.add(chunk["chunk_id"])
                    results.append(chunk)

        for chunk in _query_text_chunks_literal(conn, query, top_k, path_constraint=path_constraint):
            if chunk["chunk_id"] not in seen_ids:
                seen_ids.add(chunk["chunk_id"])
                results.append(chunk)

    except Exception as e:
        logger.error(f"[text_search] error: {e}")
    finally:
        if conn is not None:
            _put_pg_conn(conn)

    results.sort(key=lambda x: x["score"], reverse=True)
    final = results[:top_k]
    top_ids = [c.get("chunk_id") for c in final[:5]]
    logger.info(
        f"[text_search][{trace_id}] done fts={fts_count} vector={vec_count} "
        f"total_unique={len(results)} returned={len(final)} top_ids={top_ids}"
    )
    return json.dumps(final, ensure_ascii=False)


@tool
def pdf_page_search(query: str, top_k: int = RetrievalPresets.STANDARD) -> str:  # Issue #116: 8 → STANDARD (8) ✓
    """PDF 页级证据检索：直接返回最接近原文页面的 text_chunks 片段，适合规则条文和兜底取证。"""
    if not query.strip():
        return json.dumps([])

    conn = None
    try:
        conn = _get_pg_conn()
        ts_cfg = _resolve_text_search_config(conn)
        results: list[dict] = []
        seen_ids: set[str] = set()

        for chunk in _query_text_chunks_literal(conn, query, top_k):
            if chunk["chunk_id"] not in seen_ids:
                seen_ids.add(chunk["chunk_id"])
                chunk["source_db"] = "pdf_page"
                results.append(chunk)

        with conn.cursor() as cur:
            cur.execute(
                f"""
                    SELECT id, doc_id, page_number, content,
                           ts_rank(to_tsvector('{ts_cfg}', content), plainto_tsquery('{ts_cfg}', %s)) AS score
                    FROM text_chunks
                    WHERE to_tsvector('{ts_cfg}', content) @@ plainto_tsquery('{ts_cfg}', %s)
                    ORDER BY score DESC, length(content) ASC
                    LIMIT %s
                """,
                (query, query, top_k),
            )
            for row in cur.fetchall():
                chunk_id = f"pdf_{row[0]}"
                if chunk_id in seen_ids:
                    continue
                seen_ids.add(chunk_id)
                results.append(
                    _with_retrieval_path(
                        {
                            "chunk_id": chunk_id,
                            "doc_id": str(row[1] or ""),
                            "page_number": row[2] or 1,
                            "source_db": "pdf_page",
                            "content": row[3] or "",
                            "score": round(float(row[4] or 0), 4),
                            "metadata": {},
                        },
                        RETRIEVAL_PATH_PDF_PAGE,
                        evidence_kind="pdf_page_fulltext",
                        route_stage="fallback",
                    )
                )

        results.sort(key=lambda item: item.get("score", 0), reverse=True)
        return json.dumps(results[:top_k], ensure_ascii=False)
    except Exception as e:
        logger.error(f"[pdf_page_search] error: {e}")
        return json.dumps([])
    finally:
        if conn is not None:
            _put_pg_conn(conn)


@tool
def rule_clause_search(
    query: str,
    doc_id: str = "",
    doc_filename: str = "",
    section: str = "",
    page_start: int = 0,
    page_end: int = 0,
    top_k: int = RetrievalPresets.STANDARD,  # Issue #116: 8 → STANDARD (8) ✓
) -> str:
    """在限定文档/章节/页码范围内检索条文正文，适合目录命中后的二跳下钻。"""
    if not query.strip():
        return json.dumps([])

    conn = None
    try:
        conn = _get_pg_conn()

        cleaned_doc_filename = (
            (doc_filename or "").strip().replace("《", "").replace("》", "")
        )
        terms = [query.strip()]
        section_term = (section or "").strip()
        if section_term and section_term not in terms:
            terms.append(section_term)

        where_clauses = ["1=1"]
        params: list = []
        if doc_id.strip():
            where_clauses.append("doc_id = %s")
            params.append(doc_id.strip())
        if cleaned_doc_filename:
            where_clauses.append("file_name ILIKE %s")
            params.append(f"%{cleaned_doc_filename}%")
        if int(page_start or 0) > 0:
            where_clauses.append("page_number >= %s")
            params.append(int(page_start))
        if int(page_end or 0) > 0:
            where_clauses.append("page_number <= %s")
            params.append(int(page_end))

        term_clauses = []
        for term in terms:
            term_clauses.append("content ILIKE %s")
            params.append(f"%{term}%")
        if term_clauses:
            where_clauses.append(f"({' OR '.join(term_clauses)})")

        sql = f"""
            SELECT id, doc_id, file_name, page_number, content
            FROM text_chunks
            WHERE {' AND '.join(where_clauses)}
            ORDER BY
                CASE WHEN content ILIKE %s THEN 0 ELSE 1 END,
                page_number ASC,
                length(content) ASC
            LIMIT %s
        """
        params.extend((f"%{query.strip()}%", int(top_k)))

        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        results: list[dict] = []
        for index, row in enumerate(rows):
            score = max(0.75, 0.98 - index * 0.03)
            results.append(
                _with_retrieval_path(
                    {
                        "chunk_id": f"rule_clause_{row[0]}",
                        "doc_id": str(row[1] or ""),
                        "page_number": row[3] or 1,
                        "source_db": "rule_clause",
                        "content": row[4] or "",
                        "score": round(score, 4),
                        "metadata": {
                            "file_name": row[2] or "",
                            "target_doc_id": doc_id or "",
                            "target_doc_filename": cleaned_doc_filename,
                            "target_section": section_term,
                            "target_page_start": int(page_start or 0),
                            "target_page_end": int(page_end or 0),
                        },
                    },
                    RETRIEVAL_PATH_PDF_PAGE,
                    evidence_kind="rule_clause_chunk",
                    route_stage="scoped",
                )
            )

        logger.info(
            "[rule_clause_search] query='%s' doc_id='%s' file='%s' section='%s' pages=%s-%s hits=%s",
            query,
            doc_id,
            cleaned_doc_filename,
            section_term,
            page_start,
            page_end,
            len(results),
        )
        return json.dumps(results[:top_k], ensure_ascii=False)
    except Exception as e:
        logger.error(f"[rule_clause_search] error: {e}")
        return json.dumps([])
    finally:
        if conn is not None:
            _put_pg_conn(conn)


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
        ts_cfg = _resolve_text_search_config(conn)
        with conn.cursor() as cur:

            def _build_and_run(period_filter: str | None) -> list:
                where_clauses = []
                params: list = []
                if material_name:
                    where_clauses.append(
                        f"(material_name ILIKE %s OR specification ILIKE %s OR to_tsvector('{ts_cfg}', material_name) @@ plainto_tsquery('{ts_cfg}', %s))"
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
                where_clauses.append("price_tax_included IS NOT NULL")
                # 排除 OCR 噪声行（表格标题、单位行等）
                where_clauses.append(
                    "material_name !~ '^\\\\d+\\\\.?\\\\d*$'"
                )
                where_clauses.append(
                    "material_name !~ '^(kg|台班|t|m²|m³|m|套|个)$'"
                )
                where_clauses.append(
                    "material_name !~ '元$'"
                )
                where_clauses.append(
                    "material_name !~ '^(机械费|材料费|人工费|管理费|利润|规费|税金|安全文明).*元$'"
                )

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

            # Alias fallback: if material_name is an industry alias, retry with canonical name
            if not rows and material_name and material_name in _ABBREV_EXPAND:
                canonical = _ABBREV_EXPAND[material_name]
                logger.info(f"[price_query] '{material_name}' -> alias fallback to '{canonical}'")
                original_name = material_name
                material_name = canonical
                rows = _build_and_run(normalized_period if normalized_period else None)
                if not rows:
                    material_name = original_name

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
                text_fallback_results = _query_material_text_fallback(
                    conn=conn,
                    material_name=material_name,
                    year_month=normalized_period,
                    top_k=top_k,
                )
                if text_fallback_results:
                    logger.info(
                        f"[price_query] text material fallback recovered {len(text_fallback_results)} rows "
                        f"for material='{material_name}' period='{normalized_period}'"
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
                        where_clauses2.append(
                            f"(material_name ILIKE %s OR to_tsvector('{ts_cfg}', material_name) @@ plainto_tsquery('{ts_cfg}', %s))"
                        )
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
            chunk = _with_retrieval_path(
                _chunk_from_pg_row(row, "price_records", 0.85),
                RETRIEVAL_PATH_DATABASE,
                evidence_kind="structured_row",
                route_stage="primary",
            )
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
    # Issue #121: Validate time range before querying
    try:
        if start_month or end_month:
            start_month, end_month = _validate_and_normalize_time_range(
                start_month, end_month, material_name
            )
    except ValueError as e:
        error_msg = str(e)
        logger.error(f"[price_trend] time validation failed: {error_msg}")
        return json.dumps(
            [{
                "error": "time_validation_error",
                "message": error_msg,
                "material_name": material_name,
                "start_month": start_month,
                "end_month": end_month
            }],
            ensure_ascii=False
        )
    
    conn = None
    try:
        conn = _get_pg_conn()
        ts_cfg = _resolve_text_search_config(conn)
        trend_point_rows = _query_trend_points(conn, material_name, start_month, end_month)
        if trend_point_rows:
            chunks = []
            for point_id, year_month, avg_price, unit, page_number, doc_id, display_name, delta_value, delta_percent, trend_direction in trend_point_rows:
                avg = float(avg_price or 0)
                content = (
                    f"{display_name or material_name} 价格走势 "
                    f"期间:{year_month} "
                    f"均价:{avg:.2f}元/{unit} "
                )
                if delta_value is not None:
                    content += (
                        f"环比变化:{float(delta_value):+.2f} "
                        f"环比幅度:{float(delta_percent):+.2f}% "
                        f"趋势:{trend_direction} "
                    )
                chunks.append(
                    _with_retrieval_path(
                        {
                            "chunk_id": f"trend_point_{point_id}",
                            "doc_id": doc_id or "trend_points",
                            "page_number": page_number or 1,
                            "source_db": "trend_points",
                            "content": content,
                            "score": 0.88,
                            "metadata": {
                                "year_month": year_month,
                                "avg_price": avg,
                                "unit": unit,
                                "delta": float(delta_value) if delta_value is not None else None,
                                "delta_percent": float(delta_percent) if delta_percent is not None else None,
                                "trend_direction": trend_direction,
                            },
                        },
                        RETRIEVAL_PATH_DATABASE,
                        evidence_kind="trend_point",
                        route_stage="primary",
                    )
                )
            return json.dumps(chunks, ensure_ascii=False)

        where_parts: list[str] = []
        params: list = [f"%{material_name}%", f"%{material_name}%", material_name]
        where_parts.append(
            f"(material_name ILIKE %s OR specification ILIKE %s "
            f"OR to_tsvector('{ts_cfg}', material_name) @@ plainto_tsquery('{ts_cfg}', %s))"
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
                       MAX(unit) AS unit,
                       specification,
                       COUNT(*)  AS n
                FROM price_records
                {where_sql}
                GROUP BY year_month, specification, unit
                ORDER BY year_month ASC, n DESC
                LIMIT 200
                """,
                params,
            )
            raw_rows = cur.fetchall()

        rows = _pick_consistent_spec_trend(raw_rows)

        if not rows and any(token in material_name for token in ("装配式", "预制构件")):
            category_params: list = ["%预制%", "%预制%", "%混凝土%", "%混凝土%"]
            category_where_parts = [
                "(material_name ILIKE %s OR specification ILIKE %s)",
                "(material_name ILIKE %s OR specification ILIKE %s)",
                "price_tax_included IS NOT NULL",
            ]
            if start_month:
                category_where_parts.append("year_month >= %s")
                category_params.append(start_month)
            if end_month:
                category_where_parts.append("year_month <= %s")
                category_params.append(end_month)
            category_where = "WHERE " + " AND ".join(category_where_parts)
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT year_month,
                           AVG(price_tax_included)::numeric(10,2) AS avg_price,
                           COALESCE(NULLIF(MAX(unit), ''), '综合') AS unit,
                           material_name,
                           COUNT(*) AS n
                    FROM price_records
                    {category_where}
                    GROUP BY year_month, material_name, unit
                    ORDER BY year_month ASC, n DESC
                    LIMIT 120
                    """,
                    category_params,
                )
                raw_rows = cur.fetchall()
            rows = _pick_consistent_spec_trend(raw_rows)
            logger.info(f"[price_trend] precast category fallback hits={len(rows)}")

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
                               material_name,
                               COUNT(*) AS n
                        FROM price_records
                        {fb_where}
                        GROUP BY year_month, material_name, unit
                        ORDER BY year_month ASC, n DESC
                        LIMIT 120
                        """,
                        fb_params,
                    )
                    raw_rows = cur2.fetchall()
                rows = _pick_consistent_spec_trend(raw_rows)
                logger.info(f"[price_trend] bigram fallback bigrams={bigrams} hits={len(rows)}")

        existing_months = {str(r[0]) for r in rows}
        fallback_chunks: list[dict] = []
        months_to_fill = [month for month in _iter_months(start_month, end_month) if month not in existing_months]
        # Phase 1+ Task 1: Externalize price query fallback top_k
        from config.param_registry import param
        page_top_k = param("price_query_page_top_k", default=1)
        text_top_k = param("price_query_text_top_k", default=5)
        
        for month in months_to_fill:
            prefer_page_fallback = any(token in material_name for token in ("装配式", "预制构件"))
            fallback_rows: list[dict] = []
            if prefer_page_fallback:
                fallback_rows = _query_material_page_fallback(conn, material_name, month, top_k=page_top_k)
                if not fallback_rows:
                    fallback_rows = _query_material_text_fallback(conn, material_name, month, top_k=text_top_k)
            else:
                fallback_rows = _query_material_text_fallback(conn, material_name, month, top_k=text_top_k)
                if not fallback_rows:
                    fallback_rows = _query_material_page_fallback(conn, material_name, month, top_k=page_top_k)
            if not fallback_rows:
                fallback_rows = _query_material_ocr_fallback(material_name, month)
            if not fallback_rows:
                continue
            priced_rows = [row for row in fallback_rows if (row.get("metadata") or {}).get("price")]
            if priced_rows:
                prices = [
                    float(price)
                    for row in priced_rows
                    if (price := (row.get("metadata") or {}).get("price")) is not None
                ]
                if not prices:
                    continue
                first_row = priced_rows[0]
                first_metadata = first_row.get("metadata") or {}
                unit = str(first_metadata.get("unit") or "")
                fallback_chunks.append(
                    {
                        "chunk_id": f"price_trend_fallback_aggregate_{material_name}_{month}",
                        "doc_id": first_row.get("doc_id") or "",
                        "page_number": first_row.get("page_number") or 1,
                        "source_db": first_row.get("source_db", "text_price_fallback"),
                        "content": (
                            f"{material_name} 价格走势 期间:{month} 均价:{sum(prices) / len(prices):.2f}元/{unit} "
                            f"样本数:{len(prices)}"
                        ),
                        "score": max(float(row.get("score", 0.0)) for row in priced_rows),
                        "metadata": {
                            "year_month": month,
                            "price": f"{sum(prices) / len(prices):.2f}",
                            "unit": unit,
                            "sample_count": len(prices),
                            "retrieval_path": first_metadata.get("retrieval_path") or first_row.get("retrieval_path") or RETRIEVAL_PATH_DATABASE,
                            "evidence_kind": "fallback_price_aggregate",
                            "route_stage": "secondary",
                        },
                        "retrieval_path": first_row.get("retrieval_path") or first_metadata.get("retrieval_path") or RETRIEVAL_PATH_DATABASE,
                    }
                )
                continue
            fallback_chunks.extend(fallback_rows[:1])

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
            chunks.append(
                _with_retrieval_path(
                    {
                        "chunk_id": f"price_trend_{material_name}_{r[0]}",
                        "doc_id": "price_trend",
                        "page_number": 1,
                        "source_db": "price_records",
                        "content": content,
                        "score": 0.85,
                        "metadata": {"year_month": r[0], "avg_price": avg, "unit": unit, "specification": spec},
                    },
                    RETRIEVAL_PATH_DATABASE,
                    evidence_kind="structured_row",
                    route_stage="primary",
                )
            )
        for row in sorted(fallback_chunks, key=lambda item: item.get("metadata", {}).get("year_month", "")):
            year_month = row["metadata"]["year_month"]
            if "price" not in (row.get("metadata") or {}):
                chunks.append(row)
                continue
            avg_price = float(row["metadata"]["price"])
            unit = row["metadata"]["unit"]
            spec = material_name
            page_number = row.get("page_number")
            doc_id = row.get("doc_id")
            content = (
                f"{material_name} 价格走势 "
                f"期间:{year_month} "
                f"均价:{avg_price:.2f}元/{unit} "
                + (f"规格:{spec} " if spec else "")
            )
            chunks.append(
                _with_retrieval_path(
                    {
                        "chunk_id": f"price_trend_fallback_{material_name}_{year_month}_{row.get('source_db', '')}",
                        "doc_id": doc_id or "",
                        "page_number": page_number or 1,
                        "source_db": row.get("source_db", "price_fallback"),
                        "content": content,
                        "score": row.get("score", 0.82),
                        "metadata": {
                            "year_month": year_month,
                            "avg_price": avg_price,
                            "unit": unit,
                        },
                    },
                    str(row.get("metadata", {}).get("retrieval_path") or RETRIEVAL_PATH_OCR_JSON),
                    evidence_kind=str(row.get("metadata", {}).get("evidence_kind") or "fallback_row"),
                    route_stage=str(row.get("metadata", {}).get("route_stage") or "secondary"),
                )
            )
        chunks.sort(key=lambda chunk: chunk["metadata"].get("year_month", ""))

        primary_specs = {(r[3] or "").strip() for r in rows if r[3]}
        all_specs: set[str] = set(primary_specs)
        for fb in fallback_chunks:
            md = fb.get("metadata") or {}
            spec = (md.get("specification") or "").strip()
            if spec:
                all_specs.add(spec)
            elif fallback_chunks:  # fallback aggregate uses material_name → marker
                all_specs.add("__fallback_aggregate__")
        spec_mismatch = (
            len(chunks) >= 2
            and (
                len(all_specs) > 1
                or "__fallback_aggregate__" in all_specs
            )
        )
        _annotate_month_average_deltas(chunks, comparability_mode=spec_mismatch)
        if spec_mismatch:
            warning = {
                "chunk_id": f"price_trend_warning_{material_name}",
                "doc_id": "price_trend",
                "page_number": 1,
                "source_db": "price_records",
                "content": (
                    f"⚠️ 数据口径提示：检索到的 {material_name} 跨月样本规格不一致，"
                    f"涉及规格 {sorted(all_specs)[:5]}。以下环比变化已按各月月均价口径估算，"
                    f"可用于粗粒度走势参考，但不能视为同规格精确对比。"
                    f"回答时应明确说明规格差异；如需精确对比，请指定具体规格后再查询。"
                ),
                "score": 0.99,
                "metadata": {
                    "evidence_kind": "comparability_notice",
                    "specs_seen": sorted(all_specs)[:10],
                    "year_month": "*",
                },
                "retrieval_path": RETRIEVAL_PATH_DATABASE,
            }
            chunks.insert(0, warning)
            logger.info(
                f"[price_trend] spec_mismatch warning emitted material='{material_name}' "
                f"specs={sorted(all_specs)[:5]}"
            )

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


@tool
def get_catalog_map(query: str, top_k: int = RetrievalPresets.BROAD) -> str:  # Issue #116: 12 → BROAD (12) ✓
    """章节目录检索：根据关键词查找相关章节的 ID 和路径，用于在调用 text_search/hybrid_search 前确定 path_constraint。

    调用时机：当需要检索工程标准条文、计算规则、费率说明时，先调用此工具确定目标章节路径，
    再将 path 字段作为 path_constraint 传给 text_search 或 hybrid_search。

    返回：[{chapter_id, title, path, file_name, depth}]
    示例：get_catalog_map('送配电装置系统调试') →
          [{chapter_id: '10.1.7', path: '第二册电气设备安装工程/10.1/10.1.7', ...}]
    """
    if not query.strip():
        return json.dumps([])
    conn = None
    try:
        conn = _get_pg_conn()
        ts_cfg = _resolve_text_search_config(conn)
        results = []
        with conn.cursor() as cur:
            # BM25 search on catalog_index.title
            cur.execute(
                f"""
                SELECT chapter_id, title, path, file_name, depth,
                       ts_rank(to_tsvector('simple', coalesce(title,'')),
                               plainto_tsquery('simple', %s)) AS score
                FROM catalog_index
                WHERE to_tsvector('simple', coalesce(title,''))
                      @@ plainto_tsquery('simple', %s)
                ORDER BY score DESC, depth ASC
                LIMIT %s
                """,
                (query, query, top_k),
            )
            for row in cur.fetchall():
                results.append({
                    "chapter_id": row[0] or "",
                    "title":      row[1] or "",
                    "path":       row[2] or "",
                    "file_name":  row[3] or "",
                    "depth":      row[4] or 1,
                    "score":      round(float(row[5] or 0), 4),
                })
        if not results:
            # Fallback: ILIKE title search
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT chapter_id, title, path, file_name, depth, 0.1 AS score
                    FROM catalog_index
                    WHERE title ILIKE %s
                    ORDER BY depth ASC
                    LIMIT %s
                    """,
                    (f"%{query}%", top_k),
                )
                for row in cur.fetchall():
                    results.append({
                        "chapter_id": row[0] or "",
                        "title":      row[1] or "",
                        "path":       row[2] or "",
                        "file_name":  row[3] or "",
                        "depth":      row[4] or 1,
                        "score":      round(float(row[5] or 0), 4),
                    })
        logger.info(f"[get_catalog_map] query='{query}' hits={len(results)}")
        return json.dumps(results, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[get_catalog_map] error: {e}")
        return json.dumps([])
    finally:
        if conn is not None:
            _put_pg_conn(conn)


# ===========================================================================
# Schema-aware domain-neutral data backbone tools
# ---------------------------------------------------------------------------
# These tools are deliberately field-name-agnostic so the same agent toolbox
# works on any structured corpus (construction prices today, annual reports
# tomorrow). They introspect schema instead of hardcoding column names.
# ===========================================================================

# Whitelist of tables this toolbox is allowed to query. Add new domain tables
# here; nothing outside the whitelist is reachable through these tools.
_QUERYABLE_TABLES = {
    "text_chunks",
    "catalog_index",
    "document_registry",
    "price_records",
    "fee_rates",
    "trend_points",
    "trend_relations",
}

# Forbidden SQL keywords (case-insensitive) for sql_query. Anything matching
# is rejected before reaching PG. Read-only role would be ideal but rag_user
# is a single shared role so we enforce at the application layer.
_SQL_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|"
    r"COPY|CREATE|MERGE|VACUUM|ANALYZE|REINDEX|CLUSTER|LOCK|"
    r"SET|RESET|CALL|DO|EXECUTE|PREPARE|DEALLOCATE|LISTEN|NOTIFY|"
    r"BEGIN|COMMIT|ROLLBACK|SAVEPOINT)\b",
    re.IGNORECASE,
)


def _safe_table(table: str) -> str | None:
    """Return canonical table name if whitelisted, else None."""
    t = (table or "").strip().lower()
    if t in _QUERYABLE_TABLES:
        return t
    return None


@tool
def list_tables() -> str:
    """列出工具箱可查询的所有表及行数。领域无关，自描述数据库内容。"""
    conn = None
    try:
        conn = _get_pg_conn()
        results = []
        with conn.cursor() as cur:
            for tbl in sorted(_QUERYABLE_TABLES):
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                row_count = cur.fetchone()[0]
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=%s",
                    (tbl,),
                )
                cols = [r[0] for r in cur.fetchall()]
                results.append({
                    "table": tbl,
                    "row_count": int(row_count or 0),
                    "column_count": len(cols),
                    "columns_preview": cols[:6],
                })
        return json.dumps(results, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[list_tables] error: {e}")
        return json.dumps([])
    finally:
        if conn is not None:
            _put_pg_conn(conn)


@tool
def describe_table(table: str) -> str:
    """给定表名返回完整字段列表（名称、类型、是否可空）。用于 agent 写查询前自我探索。"""
    canonical = _safe_table(table)
    if canonical is None:
        return json.dumps({"error": f"table '{table}' not in whitelist"})
    conn = None
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=%s "
                "ORDER BY ordinal_position",
                (canonical,),
            )
            cols = [
                {
                    "name": r[0],
                    "type": r[1],
                    "nullable": (r[2] == "YES"),
                    "default": r[3],
                }
                for r in cur.fetchall()
            ]
            cur.execute(f"SELECT COUNT(*) FROM {canonical}")
            row_count = int(cur.fetchone()[0] or 0)
        return json.dumps(
            {"table": canonical, "row_count": row_count, "columns": cols},
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error(f"[describe_table] error: {e}")
        return json.dumps({"error": str(e)})
    finally:
        if conn is not None:
            _put_pg_conn(conn)


@tool
def sql_query(sql: str, max_rows: int = 50) -> str:
    """执行只读 SELECT。安全约束：单条 SELECT、禁 DDL/DML、强制 LIMIT≤200。

    例：SELECT material_name, price FROM price_records WHERE year_month='2026-01' LIMIT 10
    换皮场景：SELECT company, revenue FROM annual_reports WHERE year=2024 LIMIT 10
    """
    if not sql or not sql.strip():
        return json.dumps({"error": "empty sql"})

    cleaned = sql.strip().rstrip(";").strip()

    # 必须以 SELECT 或 WITH 开头
    head = cleaned[:6].upper()
    if head not in ("SELECT", "WITH  ") and not cleaned.upper().startswith("WITH "):
        if not cleaned.upper().startswith("SELECT"):
            return json.dumps({"error": "only SELECT/WITH queries are allowed"})

    # 禁多语句
    if ";" in cleaned:
        return json.dumps({"error": "multiple statements forbidden"})

    # 禁危险关键字
    if _SQL_FORBIDDEN.search(cleaned):
        return json.dumps({"error": "forbidden keyword detected"})

    cap = max(1, min(int(max_rows or 50), 200))
    # 若用户 SQL 已经写了 LIMIT，则保留；否则附加
    if not re.search(r"\blimit\b", cleaned, re.IGNORECASE):
        cleaned = f"{cleaned} LIMIT {cap}"

    conn = None
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute(cleaned)
            cols = [d[0] for d in (cur.description or [])]
            rows = cur.fetchmany(cap)
            data = [
                {col: (v.isoformat() if hasattr(v, "isoformat") else v)
                 for col, v in zip(cols, row)}
                for row in rows
            ]
        return json.dumps(
            {"columns": cols, "row_count": len(data), "rows": data},
            ensure_ascii=False, default=str,
        )
    except Exception as e:
        logger.error(f"[sql_query] error: {e} sql={cleaned[:200]}")
        return json.dumps({"error": str(e)})
    finally:
        if conn is not None:
            _put_pg_conn(conn, error=True)


@tool
def aggregate_query(
    table: str,
    group_by: str = "",
    agg: str = "count",
    agg_column: str = "",
    where: str = "",
    order_desc: bool = True,
    top_k: int = 20,
) -> str:
    """通用结构化聚合。agg ∈ {count,sum,avg,min,max}。where 是无引号的安全片段（仅 = 比较）。

    例 1（建筑造价）: aggregate_query(table='price_records', group_by='year_month', agg='avg', agg_column='price_tax_included')
    例 2（年报场景）: aggregate_query(table='annual_reports',  group_by='industry',   agg='sum', agg_column='revenue')
    """
    canonical = _safe_table(table)
    if canonical is None:
        return json.dumps({"error": f"table '{table}' not in whitelist"})

    agg_lower = (agg or "count").strip().lower()
    if agg_lower not in {"count", "sum", "avg", "min", "max"}:
        return json.dumps({"error": f"unsupported agg '{agg}'"})

    # column safety: alphanumeric/underscore only
    def _safe_col(c: str) -> bool:
        return bool(c) and bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", c))

    group = (group_by or "").strip()
    if group and not _safe_col(group):
        return json.dumps({"error": "invalid group_by"})

    if agg_lower != "count":
        if not _safe_col(agg_column):
            return json.dumps({"error": "agg_column required for non-count"})
        agg_expr = f"{agg_lower.upper()}({agg_column})"
    else:
        agg_expr = "COUNT(*)"

    # WHERE: very limited; only equality of safe column to a literal
    where_sql = ""
    where_params: list = []
    if where:
        m = re.fullmatch(
            r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*'([^';]{0,80})'\s*",
            where,
        )
        if not m:
            return json.dumps({"error": "where must be: col='value' (single equality)"})
        where_sql = f"WHERE {m.group(1)} = %s"
        where_params = [m.group(2)]

    cap = max(1, min(int(top_k or 20), 200))
    direction = "DESC" if order_desc else "ASC"

    if group:
        sql = (
            f"SELECT {group} AS bucket, {agg_expr} AS value "
            f"FROM {canonical} {where_sql} "
            f"GROUP BY {group} ORDER BY value {direction} LIMIT {cap}"
        )
    else:
        sql = f"SELECT {agg_expr} AS value FROM {canonical} {where_sql}"

    conn = None
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute(sql, where_params)
            cols = [d[0] for d in (cur.description or [])]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        return json.dumps(
            {"sql": sql, "rows": rows, "row_count": len(rows)},
            ensure_ascii=False, default=str,
        )
    except Exception as e:
        logger.error(f"[aggregate_query] error: {e} sql={sql}")
        return json.dumps({"error": str(e)})
    finally:
        if conn is not None:
            _put_pg_conn(conn, error=True)


@tool
def list_documents(
    name_like: str = "",
    limit: int = 20,
) -> str:
    """列出已入库文档（document_registry）。可按文件名模糊过滤。领域无关。"""
    cap = max(1, min(int(limit or 20), 100))
    conn = None
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            # 自适应字段：取所有列再返回，确保换皮场景仍有用
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='document_registry' "
                "ORDER BY ordinal_position"
            )
            all_cols = [r[0] for r in cur.fetchall()]
            select_list = ", ".join(all_cols) if all_cols else "*"
            params: list = []
            where = ""
            if name_like and "file_name" in all_cols:
                where = "WHERE file_name ILIKE %s"
                params.append(f"%{name_like}%")
            cur.execute(
                f"SELECT {select_list} FROM document_registry {where} LIMIT %s",
                params + [cap],
            )
            cols = [d[0] for d in (cur.description or [])]
            rows = [
                {c: (v.isoformat() if hasattr(v, "isoformat") else v)
                 for c, v in zip(cols, r)}
                for r in cur.fetchall()
            ]
        return json.dumps({"row_count": len(rows), "rows": rows},
                          ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"[list_documents] error: {e}")
        return json.dumps({"error": str(e), "rows": []})
    finally:
        if conn is not None:
            _put_pg_conn(conn)


@tool
def fetch_chunk(chunk_id: str, with_neighbors: bool = True) -> str:
    """按 chunk_id 取完整 chunk，可同时返回同文档前后 2 条邻居。

    chunk_id 可为 'tc_123' 或纯数字。
    """
    raw_id = (chunk_id or "").strip()
    if raw_id.startswith("tc_"):
        raw_id = raw_id[3:]
    if not raw_id.isdigit():
        return json.dumps({"error": "invalid chunk_id"})
    pk = int(raw_id)

    conn = None
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, doc_id, page_number, content, metadata "
                "FROM text_chunks WHERE id=%s",
                (pk,),
            )
            row = cur.fetchone()
            if row is None:
                return json.dumps({"error": "not found"})
            main = {
                "chunk_id": f"tc_{row[0]}",
                "doc_id": str(row[1] or ""),
                "page_number": row[2],
                "content": row[3] or "",
                "metadata": row[4] or {},
            }
            neighbors: list = []
            if with_neighbors:
                cur.execute(
                    "SELECT id, page_number, content FROM text_chunks "
                    "WHERE doc_id=%s AND id<>%s "
                    "ORDER BY ABS(id-%s) LIMIT 4",
                    (row[1], pk, pk),
                )
                for n in cur.fetchall():
                    neighbors.append({
                        "chunk_id": f"tc_{n[0]}",
                        "page_number": n[1],
                        "content": (n[2] or "")[:300],
                    })
        return json.dumps({"chunk": main, "neighbors": neighbors},
                          ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"[fetch_chunk] error: {e}")
        return json.dumps({"error": str(e)})
    finally:
        if conn is not None:
            _put_pg_conn(conn)


@tool
def similar_chunks(chunk_id: str, top_k: int = 5) -> str:
    """给定 chunk_id 用 pgvector 找余弦最相似的其它 chunk。用于推荐/去重/盲点发现。"""
    raw_id = (chunk_id or "").strip()
    if raw_id.startswith("tc_"):
        raw_id = raw_id[3:]
    if not raw_id.isdigit():
        return json.dumps({"error": "invalid chunk_id"})
    pk = int(raw_id)
    cap = max(1, min(int(top_k or 5), 20))

    conn = None
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT embedding FROM text_chunks WHERE id=%s", (pk,))
            row = cur.fetchone()
            if not row or row[0] is None:
                return json.dumps({"error": "chunk has no embedding"})
            emb = row[0]
            cur.execute(
                "SELECT id, doc_id, page_number, content, "
                "1 - (embedding <=> %s::vector) AS score "
                "FROM text_chunks "
                "WHERE id<>%s AND embedding IS NOT NULL "
                "ORDER BY embedding <=> %s::vector LIMIT %s",
                (emb, pk, emb, cap),
            )
            results = []
            for r in cur.fetchall():
                results.append({
                    "chunk_id": f"tc_{r[0]}",
                    "doc_id": str(r[1] or ""),
                    "page_number": r[2],
                    "content": (r[3] or "")[:400],
                    "score": round(float(r[4] or 0), 4),
                })
        return json.dumps(results, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[similar_chunks] error: {e}")
        return json.dumps([])
    finally:
        if conn is not None:
            _put_pg_conn(conn)


@tool
def stats_overview() -> str:
    """库内全局体检：每表行数、向量覆盖率、最早/最晚时间。无参数。"""
    conn = None
    try:
        conn = _get_pg_conn()
        out: dict = {"tables": {}}
        with conn.cursor() as cur:
            for tbl in sorted(_QUERYABLE_TABLES):
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                    out["tables"][tbl] = {"rows": int(cur.fetchone()[0] or 0)}
                except Exception:
                    out["tables"][tbl] = {"rows": 0}

            # 向量覆盖率
            try:
                cur.execute(
                    "SELECT COUNT(*) FILTER (WHERE embedding IS NOT NULL),"
                    " COUNT(*) FROM text_chunks"
                )
                with_e, total = cur.fetchone()
                out["embedding_coverage"] = {
                    "with_embedding": int(with_e or 0),
                    "total_chunks": int(total or 0),
                    "ratio": round((with_e or 0) / max(int(total or 1), 1), 3),
                }
            except Exception:
                pass

            # 时间维度（如果存在 year_month / created_at 等）
            for tbl, col in [
                ("price_records", "year_month"),
                ("trend_points", "year_month"),
                ("document_registry", "created_at"),
            ]:
                try:
                    cur.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema='public' AND table_name=%s AND column_name=%s",
                        (tbl, col),
                    )
                    if cur.fetchone():
                        cur.execute(f"SELECT MIN({col}), MAX({col}) FROM {tbl}")
                        lo, hi = cur.fetchone()
                        out.setdefault("time_ranges", {})[tbl] = {
                            "column": col,
                            "min": str(lo) if lo else None,
                            "max": str(hi) if hi else None,
                        }
                except Exception:
                    pass

        return json.dumps(out, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"[stats_overview] error: {e}")
        return json.dumps({"error": str(e)})
    finally:
        if conn is not None:
            _put_pg_conn(conn)


# ════════════════════════════════════════════════════════════════════════
# Round 3: Active RAG penetration tools (graph + proactive)
# ════════════════════════════════════════════════════════════════════════

import re as _re_r3

_CN_TERM_RE = _re_r3.compile(r"[\u4e00-\u9fff][\u4e00-\u9fff\w]{1,7}")
_STOPWORDS_R3 = {
    "我们", "他们", "可以", "进行", "包括", "如下", "以及", "等等", "不过",
    "因此", "所以", "如果", "虽然", "但是", "同时", "或者", "并且", "其中",
    "应当", "需要", "不能", "可能", "不得", "应该", "要求", "通过", "采用",
    "本节", "本章", "本规", "本标", "本条", "说明", "本表", "本款",
    "什么", "怎么", "哪些", "哪个", "如何", "为何", "多少",
}

def _extract_terms(text: str, min_len: int = 2, max_len: int = 8) -> list:
    """从中文文本里抽 2-8 字术语，去停用词。先按助词拆，再滑窗。"""
    if not text:
        return []
    # 按常见助词/疑问词切段，避免长跨界 term
    segments = _re_r3.split(r"[的中和或与是以为及对到从在由把被让所对于关于以及通过根据按照另外另一这一那些这些任何什么怎么哪些哪个如何为何多少\s\W]+", text)
    out = []
    seen = set()
    for seg in segments:
        if not seg:
            continue
        # 在段内用原 regex 抽
        for w in _CN_TERM_RE.findall(seg):
            if min_len <= len(w) <= max_len and w not in _STOPWORDS_R3 and w not in seen:
                seen.add(w)
                out.append(w)
        # 段本身若是合法长度也加入
        if min_len <= len(seg) <= max_len and seg not in seen and seg not in _STOPWORDS_R3 and _re_r3.match(r"^[\u4e00-\u9fff]+$", seg):
            seen.add(seg)
            out.insert(0, seg)  # 整段优先级更高
    return out


@tool
def concept_neighbors(concept: str, hops: int = 1, top_k: int = 15) -> str:
    """图谱穿透：给定概念，返回语义+结构相关概念。
    实现：embedding 近邻 chunk → 抽 catalog path 节点 + 关键词；hops>=2 时迭代扩展。
    Args: concept 概念词；hops 跳数 1-2；top_k 返回数量
    Returns: JSON {seed, neighbors:[{term,score,source}]}
    """
    if not concept or not concept.strip():
        return json.dumps({"error": "concept is required"})
    hops = max(1, min(int(hops or 1), 2))
    top_k = max(1, min(int(top_k or 15), 50))

    vec = _get_embedding(concept.strip())
    if not vec:
        return json.dumps({"error": "embedding failed"})

    conn = None
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            vec_lit = "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
            cur.execute(
                """
                SELECT id, content, section, path, depth,
                       1 - (embedding <=> %s::vector) AS score
                FROM text_chunks
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT 30
                """,
                (vec_lit, vec_lit),
            )
            rows = cur.fetchall()

        scores = {}  # term -> {score, source}
        for cid, content, section, path, depth, sim in rows:
            sim = float(sim or 0)
            # catalog path 节点 (e.g. "1/2/3" or "建筑/安装/电气")
            if path:
                for part in str(path).split("/"):
                    part = part.strip()
                    if part and part != concept and len(part) >= 2:
                        s = scores.setdefault(part, {"score": 0, "source": "catalog"})
                        s["score"] = max(s["score"], sim * 0.95)
            # section 标题
            if section and section != concept:
                s = scores.setdefault(str(section), {"score": 0, "source": "section"})
                s["score"] = max(s["score"], sim * 0.9)
            # 内容里的术语
            for term in _extract_terms(content[:400]):
                if term == concept or concept in term:
                    continue
                s = scores.setdefault(term, {"score": 0, "source": "term"})
                s["score"] = max(s["score"], sim * 0.7)

        # hop 2: 用 top-3 邻居自动扩展
        if hops >= 2 and scores:
            top_seeds = sorted(scores.items(), key=lambda x: -x[1]["score"])[:3]
            for seed, _ in top_seeds:
                vec2 = _get_embedding(seed)
                if not vec2:
                    continue
                vec_lit2 = "[" + ",".join(f"{x:.6f}" for x in vec2) + "]"
                conn2 = _get_pg_conn()
                try:
                    with conn2.cursor() as cur:
                        cur.execute(
                            "SELECT content, 1 - (embedding <=> %s::vector) "
                            "FROM text_chunks WHERE embedding IS NOT NULL "
                            "ORDER BY embedding <=> %s::vector LIMIT 5",
                            (vec_lit2, vec_lit2),
                        )
                        for content, sim2 in cur.fetchall():
                            for term in _extract_terms(content[:200]):
                                if term in (concept, seed):
                                    continue
                                s = scores.setdefault(term, {"score": 0, "source": "hop2"})
                                s["score"] = max(s["score"], float(sim2) * 0.5)
                finally:
                    _put_pg_conn(conn2)

        ranked = sorted(
            [{"term": k, "score": round(v["score"], 4), "source": v["source"]} for k, v in scores.items()],
            key=lambda x: -x["score"],
        )[:top_k]
        return json.dumps({"seed": concept, "hops": hops, "neighbors": ranked}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[concept_neighbors] {e}")
        return json.dumps({"error": str(e)})
    finally:
        if conn is not None:
            _put_pg_conn(conn)


@tool
def concept_path(from_concept: str, to_concept: str, max_hops: int = 4) -> str:
    """语义桥：找两个概念间的桥梁概念链（embedding 空间插值）。
    Args: from_concept 起点；to_concept 终点；max_hops 最大跳数 2-6
    Returns: JSON {from, to, path:[{step,term,sim_to_target}]}
    """
    if not from_concept or not to_concept:
        return json.dumps({"error": "both concepts required"})
    max_hops = max(2, min(int(max_hops or 4), 6))

    v_from = _get_embedding(from_concept.strip())
    v_to = _get_embedding(to_concept.strip())
    if not v_from or not v_to:
        return json.dumps({"error": "embedding failed"})

    conn = None
    try:
        conn = _get_pg_conn()
        path = [{"step": 0, "term": from_concept, "sim_to_target": 0.0}]
        current_vec = v_from
        visited = {from_concept, to_concept}

        for step in range(1, max_hops + 1):
            # 朝目标插值：每步取 step/(max_hops) 比例朝 v_to
            alpha = step / (max_hops + 1)
            interp = [(1 - alpha) * a + alpha * b for a, b in zip(current_vec, v_to)]
            vec_lit = "[" + ",".join(f"{x:.6f}" for x in interp) + "]"
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT content, section, 1 - (embedding <=> %s::vector) AS sim "
                    "FROM text_chunks WHERE embedding IS NOT NULL "
                    "ORDER BY embedding <=> %s::vector LIMIT 8",
                    (vec_lit, vec_lit),
                )
                rows = cur.fetchall()

            picked = None
            for content, section, sim in rows:
                candidates = []
                if section:
                    candidates.append(str(section))
                candidates.extend(_extract_terms(content[:300])[:5])
                for cand in candidates:
                    if cand and cand not in visited and 2 <= len(cand) <= 12:
                        picked = (cand, float(sim))
                        break
                if picked:
                    break
            if not picked:
                break
            term, sim = picked
            visited.add(term)
            # sim to target
            vec_term = _get_embedding(term)
            sim_target = 0.0
            if vec_term:
                num = sum(a * b for a, b in zip(vec_term, v_to))
                da = sum(a * a for a in vec_term) ** 0.5
                db = sum(b * b for b in v_to) ** 0.5
                if da and db:
                    sim_target = num / (da * db)
            path.append({"step": step, "term": term, "sim_to_target": round(sim_target, 4)})
            current_vec = vec_term or interp
            if sim_target > 0.85:
                break

        path.append({"step": len(path), "term": to_concept, "sim_to_target": 1.0})
        return json.dumps({"from": from_concept, "to": to_concept, "path": path}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[concept_path] {e}")
        return json.dumps({"error": str(e)})
    finally:
        if conn is not None:
            _put_pg_conn(conn)


@tool
def entity_cooccur(entity: str, top_k: int = 20) -> str:
    """共现分析：找与指定实体在同一 chunk 中频繁共现的术语。
    Args: entity 实体词；top_k 返回数量
    Returns: JSON {entity, cooccur:[{term,count,sample_chunk_id}]}
    """
    if not entity or not entity.strip():
        return json.dumps({"error": "entity is required"})
    top_k = max(1, min(int(top_k or 20), 100))

    conn = None
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, content FROM text_chunks "
                "WHERE content ILIKE %s LIMIT 200",
                (f"%{entity}%",),
            )
            rows = cur.fetchall()

        if not rows:
            return json.dumps({"entity": entity, "cooccur": [], "note": "no chunk contains this entity"}, ensure_ascii=False)

        counts = {}  # term -> [count, sample_chunk_id]
        for cid, content in rows:
            for term in _extract_terms(content):
                if term == entity or entity in term or term in entity:
                    continue
                if term not in counts:
                    counts[term] = [0, cid]
                counts[term][0] += 1

        ranked = sorted(
            [{"term": k, "count": v[0], "sample_chunk_id": v[1]} for k, v in counts.items()],
            key=lambda x: -x["count"],
        )[:top_k]
        return json.dumps(
            {"entity": entity, "containing_chunks": len(rows), "cooccur": ranked},
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error(f"[entity_cooccur] {e}")
        return json.dumps({"error": str(e)})
    finally:
        if conn is not None:
            _put_pg_conn(conn)


@tool
def upstream_downstream(item: str, direction: str = "both") -> str:
    """上下游：给定物料/概念，找其 catalog 父/子/兄弟节点 + 文本中的因果短语。
    Args: item 名称；direction 'up' | 'down' | 'both' (默认)
    Returns: JSON {item, parents, children, siblings, causal_phrases}
    """
    if not item or not item.strip():
        return json.dumps({"error": "item is required"})
    direction = (direction or "both").lower()
    if direction not in ("up", "down", "both"):
        direction = "both"

    conn = None
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            # catalog hits
            cur.execute(
                "SELECT id, file_name, chapter_id, title, path, depth "
                "FROM catalog_index WHERE title ILIKE %s LIMIT 10",
                (f"%{item}%",),
            )
            cat_hits = cur.fetchall()

            parents, children, siblings = [], [], []
            for cid, fname, chap, title, path, depth in cat_hits:
                if not path:
                    continue
                # parent: prefix of path
                if direction in ("up", "both"):
                    cur.execute(
                        "SELECT title, path, depth FROM catalog_index "
                        "WHERE file_name=%s AND %s LIKE path || '/%%' AND depth = %s "
                        "LIMIT 5",
                        (fname, path, max(0, (depth or 1) - 1)),
                    )
                    for t, p, d in cur.fetchall():
                        if t and t != title:
                            parents.append({"title": t, "path": p, "depth": d})
                if direction in ("down", "both"):
                    cur.execute(
                        "SELECT title, path, depth FROM catalog_index "
                        "WHERE file_name=%s AND path LIKE %s AND depth = %s LIMIT 10",
                        (fname, path + "/%", (depth or 0) + 1),
                    )
                    for t, p, d in cur.fetchall():
                        children.append({"title": t, "path": p, "depth": d})
                    cur.execute(
                        "SELECT title, path FROM catalog_index "
                        "WHERE file_name=%s AND depth=%s AND path != %s "
                        "AND path LIKE %s LIMIT 8",
                        (fname, depth, path, "/".join(path.split("/")[:-1]) + "/%"),
                    )
                    for t, p in cur.fetchall():
                        if t and t != title:
                            siblings.append({"title": t, "path": p})

            # causal phrases from chunks
            cur.execute(
                "SELECT content FROM text_chunks WHERE content ILIKE %s LIMIT 30",
                (f"%{item}%",),
            )
            phrases = []
            patterns = [
                _re_r3.compile(rf"({item}[^。;；,，]{{0,30}}?(?:由|包含|包括|含有|组成|构成)[^。;；]{{2,40}})"),
                _re_r3.compile(rf"((?:由|用于|应用于|适用于)[^。;；]{{2,30}}?{item}[^。;；,，]{{0,20}})"),
                _re_r3.compile(rf"({item}[^。;；,，]{{0,20}}?(?:用于|适用于|对应)[^。;；]{{2,30}})"),
            ]
            seen_phr = set()
            for (content,) in cur.fetchall():
                for pat in patterns:
                    for m in pat.findall(content)[:3]:
                        m = m.strip()
                        if m and m not in seen_phr and len(m) <= 80:
                            seen_phr.add(m)
                            phrases.append(m)
                if len(phrases) >= 12:
                    break

        return json.dumps(
            {
                "item": item,
                "direction": direction,
                "parents": parents[:6],
                "children": children[:12],
                "siblings": siblings[:8],
                "causal_phrases": phrases[:12],
            },
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error(f"[upstream_downstream] {e}")
        return json.dumps({"error": str(e)})
    finally:
        if conn is not None:
            _put_pg_conn(conn)


_QUESTION_TEMPLATES = [
    "{e}的定义/概念是什么？",
    "{e}的计算规则/公式是什么？",
    "{e}的适用范围/条件是什么？",
    "{e}有哪些类型/分类？",
    "{e}的标准依据/规范来源？",
    "{e}的常见单位/计量方式？",
    "{e}与相关概念的区别？",
    "{e}的典型应用场景？",
]


@tool
def expand_question(question: str, n: int = 5) -> str:
    """问题展开：把一个问题拆成 N 个子问题（实体 × 5W1H 模板）。
    Args: question 原问题；n 子问数量 (1-10)
    Returns: JSON {question, sub_questions:[...]}
    """
    if not question or not question.strip():
        return json.dumps({"error": "question is required"})
    n = max(1, min(int(n or 5), 10))

    entities = _extract_terms(question, min_len=2, max_len=10)[:4]
    if not entities:
        return json.dumps({"question": question, "sub_questions": [question], "note": "no entity extracted"}, ensure_ascii=False)

    subs = []
    seen = set()
    # 主实体 × 多模板
    main = entities[0]
    for tpl in _QUESTION_TEMPLATES:
        q = tpl.format(e=main)
        if q not in seen:
            seen.add(q)
            subs.append(q)
        if len(subs) >= n:
            break
    # 其它实体 × 1-2 个模板
    if len(subs) < n:
        for ent in entities[1:]:
            for tpl in _QUESTION_TEMPLATES[:3]:
                q = tpl.format(e=ent)
                if q not in seen:
                    seen.add(q)
                    subs.append(q)
                if len(subs) >= n:
                    break
            if len(subs) >= n:
                break

    return json.dumps({"question": question, "entities": entities, "sub_questions": subs[:n]}, ensure_ascii=False)


@tool
def suggest_followup(question: str, answer: str, n: int = 3) -> str:
    """追问建议：用 LLM 基于问答原文生成 N 个上下文相关的追问。
    Args: question 原问题；answer 回答文本；n 追问数量
    Returns: JSON {followups:[{question, reason}]}
    """
    if not question or not answer:
        return json.dumps({"error": "question and answer required"})
    n = max(1, min(int(n or 3), 8))

    try:
        from app.agent.prompts import invoke_llm
        from langchain_core.messages import SystemMessage, HumanMessage

        system = (
            "你是一个工程造价知识库的智能助手。"
            "根据用户的问题和系统给出的回答，生成若干个自然、深入的追问建议。"
            "要求：\n"
            "1. 追问必须基于回答中实际出现的概念或数据，不能凭空造词\n"
            "2. 追问应是用户看到这个回答后最可能想继续了解的问题\n"
            "3. 避免模板化措辞，每个追问都应具体且有意义\n"
            "4. 只输出 JSON，格式：{\"followups\": [{\"question\": \"...\", \"reason\": \"...\"}]}\n"
            "5. reason 字段说明该追问基于回答中的哪个具体信息点"
        )
        user = (
            f"原问题：{question}\n\n"
            f"回答（前1200字）：{answer[:1200]}\n\n"
            f"请生成 {n} 个追问建议。"
        )
        response, _ = invoke_llm([SystemMessage(content=system), HumanMessage(content=user)])
        raw = response.content if hasattr(response, "content") else str(response)
        # 从 LLM 输出中提取 JSON
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            parsed = json.loads(m.group())
            followups = parsed.get("followups", [])
            if followups:
                return json.dumps({"original": question, "followups": followups[:n]}, ensure_ascii=False)
    except Exception as e:
        logger.debug(f"[suggest_followup] LLM call failed: {e}, falling back to entity templates")

    # 降级：实体模板（LLM 不可用时兜底）
    q_terms = set(_extract_terms(question))
    a_terms = _extract_terms(answer, max_len=20)  # 放宽长度限制，保留完整实体名
    new_entities = [t for t in a_terms if t not in q_terms][:4]
    if not new_entities:
        return json.dumps({"followups": [], "note": "no new entity in answer"}, ensure_ascii=False)
    fallback_tpls = [
        "{ne}的计算规则是什么？",
        "{ne}的适用范围有哪些限制？",
        "{ne}与{qe}有什么区别？",
        "{ne}在哪些场景下需要调整系数？",
    ]
    main_q_entity = next(iter(q_terms), "本主题") if q_terms else "本主题"
    followups = []
    seen: set = set()
    for ne in new_entities:
        for tpl in fallback_tpls:
            q = tpl.format(ne=ne, qe=main_q_entity)
            if q not in seen:
                seen.add(q)
                followups.append({"question": q, "reason": f"基于回答中出现的「{ne}」"})
            if len(followups) >= n:
                break
        if len(followups) >= n:
            break
    return json.dumps({"original": question, "followups": followups[:n]}, ensure_ascii=False)


@tool
def find_knowledge_gaps(question: str, threshold: float = 0.55) -> str:
    """缺口侦测：把问题拆为子问，对每个子问做 vector_search，标出库中无法回答的部分。
    Args: question 原问题；threshold 命中阈值 (默认 0.55)
    Returns: JSON {gaps:[{sub_q,best_score}], covered:[...], advice}
    """
    if not question or not question.strip():
        return json.dumps({"error": "question is required"})
    threshold = float(threshold or 0.55)

    # 先展开
    expanded = json.loads(expand_question.invoke({"question": question, "n": 6}))
    subs = expanded.get("sub_questions", [])
    if not subs:
        return json.dumps({"error": "could not expand"})

    conn = None
    try:
        conn = _get_pg_conn()
        gaps, covered = [], []
        for sub in subs:
            vec = _get_embedding(sub)
            if not vec:
                continue
            vec_lit = "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 - (embedding <=> %s::vector) FROM text_chunks "
                    "WHERE embedding IS NOT NULL "
                    "ORDER BY embedding <=> %s::vector LIMIT 1",
                    (vec_lit, vec_lit),
                )
                row = cur.fetchone()
            best = float(row[0]) if row else 0.0
            entry = {"sub_question": sub, "best_score": round(best, 4)}
            if best < threshold:
                gaps.append(entry)
            else:
                covered.append(entry)

        advice = (
            f"知识库覆盖 {len(covered)}/{len(subs)} 子问。建议补充以下方向资料："
            + "; ".join(g["sub_question"] for g in gaps[:3])
            if gaps
            else f"知识库完整覆盖该问题的 {len(covered)} 个子方向。"
        )
        return json.dumps(
            {"question": question, "threshold": threshold, "covered": covered, "gaps": gaps, "advice": advice},
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error(f"[find_knowledge_gaps] {e}")
        return json.dumps({"error": str(e)})
    finally:
        if conn is not None:
            _put_pg_conn(conn)


# ════════════════════════════════════════════════════════════════════════
# Round 4: Data science tools (numpy/pandas/sklearn/scipy)
# ════════════════════════════════════════════════════════════════════════

def _safe_table_check(table: str) -> bool:
    return table in _QUERYABLE_TABLES


@tool
def forecast_series(
    table: str,
    time_col: str,
    value_col: str,
    where: str = "",
    periods: int = 6,
    method: str = "linear",
) -> str:
    """时间序列预测：对表中某时间序列做未来 N 期预测。
    Args: table 表名；time_col 时间列；value_col 数值列；where 可选 col='val' 过滤；
          periods 预测期数 (1-24)；method 'linear' 线性回归 | 'mean' 均值
    Returns: JSON {history:[{t,v}], forecast:[{t,v_hat,lower,upper}], r2}
    """
    if not _safe_table_check(table):
        return json.dumps({"error": f"table not allowed: {table}"})
    if not _re_r3.match(r"^[A-Za-z_][A-Za-z0-9_]*$", time_col or ""):
        return json.dumps({"error": "invalid time_col"})
    if not _re_r3.match(r"^[A-Za-z_][A-Za-z0-9_]*$", value_col or ""):
        return json.dumps({"error": "invalid value_col"})
    periods = max(1, min(int(periods or 6), 24))
    method = (method or "linear").lower()

    where_sql = ""
    where_params = []
    if where:
        m = _re_r3.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*'([^']{1,80})'$", where.strip())
        if not m:
            return json.dumps({"error": "where must be: col='value'"})
        where_sql = f"WHERE {m.group(1)} = %s AND {value_col} IS NOT NULL AND {time_col} IS NOT NULL"
        where_params = [m.group(2)]
    else:
        where_sql = f"WHERE {value_col} IS NOT NULL AND {time_col} IS NOT NULL"

    conn = None
    try:
        import numpy as np  # local import
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {time_col}, AVG({value_col}::numeric)::float "
                f"FROM {table} {where_sql} "
                f"GROUP BY {time_col} ORDER BY {time_col} LIMIT 200",
                where_params,
            )
            rows = cur.fetchall()
        if len(rows) < 3:
            return json.dumps({"error": f"need >=3 points, got {len(rows)}"})

        ts = [str(r[0]) for r in rows]
        vs = [float(r[1]) for r in rows]
        x = np.arange(len(vs), dtype=float)
        y = np.array(vs)

        if method == "mean":
            y_hat = float(y.mean())
            std = float(y.std() or 0)
            forecast = [{"t": f"+{i+1}", "v_hat": round(y_hat, 4),
                         "lower": round(y_hat - 1.96 * std, 4),
                         "upper": round(y_hat + 1.96 * std, 4)} for i in range(periods)]
            r2 = 0.0
        else:
            slope, intercept = np.polyfit(x, y, 1)
            pred_in = slope * x + intercept
            ss_res = float(((y - pred_in) ** 2).sum())
            ss_tot = float(((y - y.mean()) ** 2).sum()) or 1e-9
            r2 = round(1 - ss_res / ss_tot, 4)
            sigma = float(np.std(y - pred_in)) or 0
            forecast = []
            for i in range(periods):
                xi = len(vs) + i
                yh = slope * xi + intercept
                forecast.append({
                    "t": f"+{i+1}",
                    "v_hat": round(float(yh), 4),
                    "lower": round(float(yh - 1.96 * sigma), 4),
                    "upper": round(float(yh + 1.96 * sigma), 4),
                })

        return json.dumps({
            "table": table, "time_col": time_col, "value_col": value_col,
            "method": method, "n_history": len(vs),
            "history": [{"t": t, "v": round(v, 4)} for t, v in zip(ts, vs)],
            "forecast": forecast, "r2": r2,
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[forecast_series] {e}")
        return json.dumps({"error": str(e)})
    finally:
        if conn is not None:
            _put_pg_conn(conn)


@tool
def outlier_detect(table: str, column: str, method: str = "iqr", where: str = "") -> str:
    """异常值检测：用 IQR 或 zscore 找数值列异常。
    Args: table 表名；column 数值列；method 'iqr' (默认) | 'zscore'；where 可选过滤
    Returns: JSON {threshold_lo, threshold_hi, outlier_count, samples:[{rowid,value}]}
    """
    if not _safe_table_check(table):
        return json.dumps({"error": f"table not allowed: {table}"})
    if not _re_r3.match(r"^[A-Za-z_][A-Za-z0-9_]*$", column or ""):
        return json.dumps({"error": "invalid column"})
    method = (method or "iqr").lower()
    if method not in ("iqr", "zscore"):
        return json.dumps({"error": "method must be iqr or zscore"})

    where_sql = f"WHERE {column} IS NOT NULL"
    where_params = []
    if where:
        m = _re_r3.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*'([^']{1,80})'$", where.strip())
        if not m:
            return json.dumps({"error": "where must be: col='value'"})
        where_sql += f" AND {m.group(1)} = %s"
        where_params = [m.group(2)]

    conn = None
    try:
        import numpy as np
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, {column}::numeric::float FROM {table} {where_sql} LIMIT 10000",
                where_params,
            )
            rows = cur.fetchall()
        if len(rows) < 5:
            return json.dumps({"error": f"need >=5 rows, got {len(rows)}"})

        ids = [r[0] for r in rows]
        vals = np.array([float(r[1]) for r in rows])

        if method == "iqr":
            q1, q3 = np.percentile(vals, [25, 75])
            iqr = q3 - q1
            lo, hi = float(q1 - 1.5 * iqr), float(q3 + 1.5 * iqr)
            mask = (vals < lo) | (vals > hi)
        else:
            mu, sd = float(vals.mean()), float(vals.std() or 1e-9)
            lo, hi = mu - 3 * sd, mu + 3 * sd
            mask = np.abs(vals - mu) > 3 * sd

        out_idx = np.where(mask)[0]
        samples = [{"row_id": int(ids[i]), "value": round(float(vals[i]), 4)} for i in out_idx[:30]]
        return json.dumps({
            "table": table, "column": column, "method": method,
            "n": int(len(vals)),
            "threshold_lo": round(lo, 4), "threshold_hi": round(hi, 4),
            "outlier_count": int(mask.sum()),
            "ratio": round(float(mask.mean()), 4),
            "samples": samples,
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[outlier_detect] {e}")
        return json.dumps({"error": str(e)})
    finally:
        if conn is not None:
            _put_pg_conn(conn)


@tool
def correlate(table: str, columns: str, method: str = "pearson") -> str:
    """相关性矩阵：给定多个数值列，计算两两相关。
    Args: table 表名；columns 逗号分隔的列名 (2-8 个)；method 'pearson' (默认) | 'spearman'
    Returns: JSON {columns, matrix:[[...]], top_pairs:[{a,b,corr}]}
    """
    if not _safe_table_check(table):
        return json.dumps({"error": f"table not allowed: {table}"})
    cols = [c.strip() for c in (columns or "").split(",") if c.strip()]
    if not (2 <= len(cols) <= 8):
        return json.dumps({"error": "columns: 2-8 names, comma separated"})
    for c in cols:
        if not _re_r3.match(r"^[A-Za-z_][A-Za-z0-9_]*$", c):
            return json.dumps({"error": f"invalid column: {c}"})
    method = (method or "pearson").lower()
    if method not in ("pearson", "spearman"):
        return json.dumps({"error": "method must be pearson or spearman"})

    conn = None
    try:
        import pandas as pd
        conn = _get_pg_conn()
        sel = ", ".join(f"{c}::numeric::float AS {c}" for c in cols)
        where = " AND ".join(f"{c} IS NOT NULL" for c in cols)
        with conn.cursor() as cur:
            cur.execute(f"SELECT {sel} FROM {table} WHERE {where} LIMIT 5000")
            rows = cur.fetchall()
        if len(rows) < 5:
            return json.dumps({"error": f"need >=5 rows, got {len(rows)}"})

        df = pd.DataFrame(rows, columns=cols)
        corr = df.corr(method=method).round(4)
        # top pairs
        pairs = []
        for i, a in enumerate(cols):
            for j, b in enumerate(cols):
                if j <= i:
                    continue
                v = float(corr.iloc[i, j])
                if not (v != v):  # not NaN
                    pairs.append({"a": a, "b": b, "corr": round(v, 4)})
        pairs.sort(key=lambda p: -abs(p["corr"]))

        return json.dumps({
            "table": table, "columns": cols, "method": method,
            "n": int(len(rows)),
            "matrix": corr.values.tolist(),
            "top_pairs": pairs[:10],
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[correlate] {e}")
        return json.dumps({"error": str(e)})
    finally:
        if conn is not None:
            _put_pg_conn(conn)


@tool
def cluster_records(table: str, columns: str, k: int = 4, sample_per_cluster: int = 3) -> str:
    """KMeans 聚类：基于多列把记录分 K 簇，返回每簇统计 + 样本。
    Args: table；columns 逗号分隔数值列 (2-8)；k 簇数 (2-10)；sample_per_cluster 每簇样本数
    Returns: JSON {clusters:[{label,size,center,samples}]}
    """
    if not _safe_table_check(table):
        return json.dumps({"error": f"table not allowed: {table}"})
    cols = [c.strip() for c in (columns or "").split(",") if c.strip()]
    if not (2 <= len(cols) <= 8):
        return json.dumps({"error": "columns: 2-8 names, comma separated"})
    for c in cols:
        if not _re_r3.match(r"^[A-Za-z_][A-Za-z0-9_]*$", c):
            return json.dumps({"error": f"invalid column: {c}"})
    k = max(2, min(int(k or 4), 10))
    sample_per_cluster = max(1, min(int(sample_per_cluster or 3), 8))

    conn = None
    try:
        import numpy as np
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import StandardScaler
        conn = _get_pg_conn()
        sel = "id, " + ", ".join(f"{c}::numeric::float AS {c}" for c in cols)
        where = " AND ".join(f"{c} IS NOT NULL" for c in cols)
        with conn.cursor() as cur:
            cur.execute(f"SELECT {sel} FROM {table} WHERE {where} LIMIT 5000")
            rows = cur.fetchall()
        if len(rows) < k * 3:
            return json.dumps({"error": f"need >={k*3} rows, got {len(rows)}"})

        ids = [r[0] for r in rows]
        X = np.array([list(r[1:]) for r in rows], dtype=float)
        Xs = StandardScaler().fit_transform(X)
        km = KMeans(n_clusters=k, n_init=10, random_state=42).fit(Xs)
        labels = km.labels_

        clusters = []
        for cid in range(k):
            idx = np.where(labels == cid)[0]
            if len(idx) == 0:
                continue
            center = X[idx].mean(axis=0)
            sample_idx = idx[:sample_per_cluster]
            samples = [{"row_id": int(ids[i]), **{cols[j]: round(float(X[i, j]), 4) for j in range(len(cols))}} for i in sample_idx]
            clusters.append({
                "label": int(cid),
                "size": int(len(idx)),
                "center": {cols[j]: round(float(center[j]), 4) for j in range(len(cols))},
                "samples": samples,
            })
        clusters.sort(key=lambda c: -c["size"])
        return json.dumps({"table": table, "columns": cols, "k": k, "n": int(len(rows)), "clusters": clusters}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[cluster_records] {e}")
        return json.dumps({"error": str(e)})
    finally:
        if conn is not None:
            _put_pg_conn(conn)


# ──────────────────────────────────────────────────────────────────────
# Round 6 · Sandbox utilities + proactive knowledge explorer
# Domain-agnostic helpers so the agent can operate on cost data today
# and pivot to e.g. annual reports tomorrow.
# ──────────────────────────────────────────────────────────────────────

def regex_extract(text: str, pattern: str, flags: str = "") -> str:
    """从一段文本里按正则提取所有匹配（含命名分组）。flags: i(忽略大小写) m(多行) s(.匹配换行)"""
    import re as _re
    try:
        flag_val = 0
        if "i" in flags.lower(): flag_val |= _re.IGNORECASE
        if "m" in flags.lower(): flag_val |= _re.MULTILINE
        if "s" in flags.lower(): flag_val |= _re.DOTALL
        rx = _re.compile(pattern, flag_val)
        out = []
        for m in rx.finditer(text or ""):
            if m.groupdict():
                out.append({"match": m.group(0), **m.groupdict()})
            elif m.groups():
                out.append({"match": m.group(0), "groups": list(m.groups())})
            else:
                out.append({"match": m.group(0)})
            if len(out) >= 200:
                break
        return json.dumps({"count": len(out), "matches": out}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


_UNIT_CATEGORIES = {
    "length":   {"mm": 0.001, "cm": 0.01, "dm": 0.1, "m": 1.0, "km": 1000.0, "寸": 0.0333, "尺": 0.333, "丈": 3.333},
    "area":     {"mm2": 1e-6, "cm2": 1e-4, "m2": 1.0, "㎡": 1.0, "公顷": 1e4, "亩": 666.6667, "km2": 1e6},
    "volume":   {"ml": 1e-6, "L": 1e-3, "m3": 1.0, "立方米": 1.0, "㎥": 1.0},
    "mass":     {"mg": 1e-6, "g": 1e-3, "kg": 1.0, "t": 1000.0, "吨": 1000.0, "斤": 0.5},
    "currency": {"元": 1.0, "¥": 1.0, "RMB": 1.0, "千元": 1000.0, "万元": 10000.0, "亿元": 1e8},
    "time":     {"s": 1.0, "min": 60.0, "h": 3600.0, "d": 86400.0, "工日": 28800.0, "月": 2592000.0, "年": 31536000.0},
}

def unit_convert(value: float, from_unit: str, to_unit: str) -> str:
    """单位换算：长度/面积/体积/质量/货币/时间。
    支持单位：mm/cm/m/km、mm2/m2/㎡、L/m3、g/kg/t、元/万元/亿元、min/h/d/工日 等。"""
    try:
        fv = float(value)
        for cat, table in _UNIT_CATEGORIES.items():
            if from_unit in table and to_unit in table:
                base = fv * table[from_unit]
                result = base / table[to_unit]
                return json.dumps({
                    "input": {"value": fv, "unit": from_unit},
                    "output": {"value": round(result, 8), "unit": to_unit},
                    "category": cat,
                    "factor": round(table[from_unit] / table[to_unit], 8),
                }, ensure_ascii=False)
        return json.dumps({"error": "unknown_or_mismatched_units",
                           "supported": {k: list(v.keys()) for k, v in _UNIT_CATEGORIES.items()}},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def date_math(operation: str, a: str = "", b: str = "", days: int = 0, fmt: str = "%Y-%m-%d") -> str:
    """日期算术。operation:
       - diff:  返回 a - b 的天数差
       - add:   返回 a + days 的日期
       - period_diff: a/b 为 YYYY-MM 或 YYYYMM，返回相差月数
       - quarter: a 为日期，返回所属季度（YYYYQn）"""
    from datetime import datetime, timedelta
    try:
        op = (operation or "").strip().lower()
        if op == "diff":
            da = datetime.strptime(a, fmt); db = datetime.strptime(b, fmt)
            return json.dumps({"days": (da - db).days})
        if op == "add":
            da = datetime.strptime(a, fmt)
            return json.dumps({"date": (da + timedelta(days=int(days))).strftime(fmt)})
        if op == "period_diff":
            def parse_p(s: str):
                s = s.replace("-", "").replace("/", "")
                return int(s[:4]), int(s[4:6])
            ya, ma = parse_p(a); yb, mb = parse_p(b)
            return json.dumps({"months": (ya - yb) * 12 + (ma - mb)})
        if op == "quarter":
            da = datetime.strptime(a, fmt)
            return json.dumps({"quarter": f"{da.year}Q{(da.month - 1) // 3 + 1}"})
        return json.dumps({"error": f"unknown operation: {operation}",
                           "supported": ["diff", "add", "period_diff", "quarter"]})
    except Exception as e:
        return json.dumps({"error": str(e)})


def compare_values(current: float, baseline: float, label: str = "") -> str:
    """比较两个数值，给出绝对差、百分比变化、基点变化（适合费率/价格对比）。"""
    try:
        c = float(current); b = float(baseline)
        abs_diff = c - b
        pct = (abs_diff / b * 100.0) if b != 0 else None
        bp  = abs_diff * 10000.0
        direction = "up" if abs_diff > 0 else "down" if abs_diff < 0 else "flat"
        return json.dumps({
            "label": label,
            "current": c,
            "baseline": b,
            "abs_change": round(abs_diff, 6),
            "pct_change": round(pct, 4) if pct is not None else None,
            "bp_change": round(bp, 2),
            "direction": direction,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def number_stats(values_json: str) -> str:
    """对一组数值做描述性统计：均值/中位数/标准差/极值/分位数。values_json 为 JSON 数组。"""
    try:
        arr = json.loads(values_json) if isinstance(values_json, str) else list(values_json)
        nums = [float(x) for x in arr if x is not None]
        if not nums:
            return json.dumps({"error": "empty"})
        import statistics as _st
        ns = sorted(nums)
        n = len(ns)
        def q(p):
            idx = (n - 1) * p; lo = int(idx); hi = min(lo + 1, n - 1); frac = idx - lo
            return ns[lo] * (1 - frac) + ns[hi] * frac
        return json.dumps({
            "n": n, "min": ns[0], "max": ns[-1],
            "mean": round(sum(ns) / n, 6),
            "median": round(_st.median(ns), 6),
            "stdev": round(_st.pstdev(ns), 6) if n > 1 else 0.0,
            "p25": round(q(0.25), 6), "p75": round(q(0.75), 6),
            "p95": round(q(0.95), 6), "p99": round(q(0.99), 6),
            "sum": round(sum(ns), 6),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def chart_spec(chart_type: str, data_json: str, title: str = "", x_key: str = "x", y_key: str = "y") -> str:
    """生成可被前端 recharts 渲染的图表 spec。chart_type: line/bar/pie/area/scatter。
       data_json 为对象数组 JSON 字符串。返回 {chart_spec: ...} 供前端直接消费。"""
    try:
        rows = json.loads(data_json) if isinstance(data_json, str) else data_json
        if not isinstance(rows, list):
            return json.dumps({"error": "data_json must be a JSON array of objects"})
        ct = (chart_type or "line").lower().strip()
        if ct not in {"line", "bar", "pie", "area", "scatter"}:
            return json.dumps({"error": f"unknown chart_type: {chart_type}"})
        return json.dumps({
            "chart_spec": {
                "type": ct,
                "title": title,
                "x_key": x_key,
                "y_key": y_key,
                "data": rows[:200],
            }
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def proactive_explore(question: str, max_concepts: int = 3, neighbor_top_k: int = 8) -> str:
    """主动认知 — 从问题里抽取核心概念，沿图谱穿透邻居/上下游/共现实体，
    把用户没主动问、但极相关的知识点也带回来。返回:
    { question, concepts:[{name, neighbors:[...], upstream:[...], downstream:[...]}],
      followups:[...], gaps:[...] }"""
    out = {"question": question, "concepts": [], "followups": [], "gaps": []}
    try:
        # 1. 概念命中
        concept_raw = concept_search(question, top_k=max_concepts, include_evidence=False)
        try:
            concept_payload = json.loads(concept_raw)
        except Exception:
            concept_payload = {}
        concept_hits = (concept_payload or {}).get("concepts") or []
        seen = set()
        names: list[str] = []
        for c in concept_hits:
            nm = (c.get("concept") or c.get("name") or "").strip()
            if nm and nm not in seen:
                seen.add(nm)
                names.append(nm)
            if len(names) >= max_concepts:
                break
        # 2. 退化为关键词
        if not names:
            terms = _extract_terms(question, min_len=2, max_len=8)
            names = list(dict.fromkeys(terms))[:max_concepts]

        # 3. 对每个概念跑邻居 / 上下游
        for nm in names:
            entry = {"concept": nm, "neighbors": [], "upstream": [], "downstream": [], "cooccur": []}
            try:
                nb = json.loads(concept_neighbors(nm, hops=1, top_k=neighbor_top_k))
                entry["neighbors"] = (nb or {}).get("neighbors", [])[:neighbor_top_k]
            except Exception:
                pass
            try:
                ud = json.loads(upstream_downstream(nm, direction="both"))
                entry["upstream"]   = (ud or {}).get("upstream", [])[:6]
                entry["downstream"] = (ud or {}).get("downstream", [])[:6]
            except Exception:
                pass
            # Phase 1+ Task 1: Externalize graph cooccurrence top_k
            try:
                from config.param_registry import param
                cooccur_top_k = param("graph_cooccur_top_k", default=6)
                co = json.loads(entity_cooccur(nm, top_k=cooccur_top_k))
                entry["cooccur"] = (co or {}).get("cooccur", [])[:cooccur_top_k]
            except Exception:
                pass
            out["concepts"].append(entry)

        # 4. 追问 + 知识缺口
        try:
            fu = json.loads(suggest_followup(question, "", n=3))
            out["followups"] = (fu or {}).get("suggestions", [])
        except Exception:
            pass
        try:
            gp = json.loads(find_knowledge_gaps(question, threshold=0.55))
            out["gaps"] = (gp or {}).get("gaps", [])
        except Exception:
            pass
        return json.dumps(out, ensure_ascii=False)
    except Exception as e:
        out["error"] = str(e)
        return json.dumps(out, ensure_ascii=False)
