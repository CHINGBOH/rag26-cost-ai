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
from config.settings import AppConfig
from infrastructure.vector_store import create_vector_store_adapter

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
_OBSERVABILITY_ENABLED = (
    os.environ.get("RETRIEVAL_OBSERVABILITY_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
)
_TSV_CONFIG_ENV = os.environ.get("PG_TSV_CONFIG", "chinese").strip().lower()
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


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning(f"[config] invalid int for {name}: {raw!r}; fallback={default}")
        return default
    return max(minimum, value)


def _env_float(name: str, default: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning(f"[config] invalid float for {name}: {raw!r}; fallback={default}")
        return default
    if value < min_value:
        return min_value
    if value > max_value:
        return max_value
    return value


def _get_hybrid_runtime_config(top_k: int) -> dict:
    normalized_top_k = max(1, int(top_k))
    vector_fetch_multiplier = _env_int("HYBRID_VECTOR_FETCH_MULTIPLIER", 1, minimum=1)
    text_fetch_multiplier = _env_int("HYBRID_TEXT_FETCH_MULTIPLIER", 1, minimum=1)
    return {
        "vector_min_score": _env_float("HYBRID_VECTOR_MIN_SCORE", 0.40, min_value=0.0, max_value=1.0),
        "vector_fetch_k": normalized_top_k * vector_fetch_multiplier,
        "text_fetch_k": normalized_top_k * text_fetch_multiplier,
        "rrf_rank_constant": _env_int("HYBRID_RRF_RANK_CONSTANT", 60, minimum=1),
        "structured_top_k": _env_int("HYBRID_STRUCTURED_TOP_K", normalized_top_k, minimum=1),
        "literal_top_k": _env_int("HYBRID_LITERAL_TOP_K", normalized_top_k, minimum=1),
    }


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
    if not _OBSERVABILITY_ENABLED:
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
        preferred = _TSV_CONFIG_ENV if re.fullmatch(r"[a-z0-9_]+", _TSV_CONFIG_ENV) else "simple"
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
        else max(1, min(4, _env_int("CONCEPT_RECURSIVE_DEPTH", 2, minimum=1)))
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
                drill_terms = concept_terms[:2] if concept_terms else [concept_name]
                for term in drill_terms:
                    local_hits.extend(_query_text_chunks_literal(conn, term, top_k=1))
                if _should_include_structured_tables(query):
                    local_hits.extend(_query_structured_tables(query, top_k=1))
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
        _with_retrieval_path(
            {
                "chunk_id": f"tc_{row[0]}",
                "doc_id": str(row[1] or ""),
                "page_number": row[2] or 1,
                "source_db": "literal_text",
                "content": row[3] or "",
                "score": 0.72,
                "metadata": {},
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
    try:
        vector_config = AppConfig().vector_store
    except Exception as e:
        logger.warning(f"[vector_search] failed to load vector store config: {e}")
        return []

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
def vector_search(query: str, top_k: int = 10) -> str:
    """向量语义搜索：从 text_chunks 表中使用 pgvector 余弦相似度检索"""
    if not query.strip():
        return json.dumps([])

    conn = None
    try:
        milvus_results = _milvus_vector_results(query, top_k)
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
                  AND 1 - (embedding <=> %s::vector) >= 0.40
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """, (query_embedding, query_embedding, query_embedding, top_k))

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
                            "metadata": {},
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
def concept_search(query: str, top_k: int = 6, include_evidence: bool = True) -> str:
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
def keyword_search(query: str, top_k: int = 10) -> str:
    """关键词全文搜索：从 text_chunks 表中使用 PostgreSQL tsvector + ts_rank 检索"""
    if not query.strip():
        return json.dumps([])

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
def hybrid_search(query: str, top_k: int = 10, path_constraint: str = "") -> str:
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
        cfg = _get_hybrid_runtime_config(top_k)
        query_family = str((_concept_analyzer.analyze(query).get("intent") or "semantic"))
        cfg = _apply_query_family_routing(query_family, cfg, top_k)
        milvus_vector_hits: list[dict] = []
        if not path_constraint:
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
            "top_k": int(top_k),
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
        for chunk in _rrf_fuse_chunks(
            [vector_hits, multivector_hits, text_hits],
            rank_constant=int(cfg["rrf_rank_constant"]),
        ):
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

        for chunk in _query_text_chunks_literal(conn, query, int(cfg["literal_top_k"])):
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
        return json.dumps(results[:top_k], ensure_ascii=False)
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
def text_search(query: str, top_k: int = 8, path_constraint: str = "") -> str:
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
                           ts_rank(to_tsvector('{ts_cfg}', content), plainto_tsquery('{ts_cfg}', %s)) AS score
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
                                    "metadata": {},
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
    final = results[:top_k]
    top_ids = [c.get("chunk_id") for c in final[:5]]
    logger.info(
        f"[text_search][{trace_id}] done fts={fts_count} vector={vec_count} "
        f"total_unique={len(results)} returned={len(final)} top_ids={top_ids}"
    )
    return json.dumps(final, ensure_ascii=False)


@tool
def pdf_page_search(query: str, top_k: int = 8) -> str:
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
    top_k: int = 8,
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
        for month in months_to_fill:
            prefer_page_fallback = any(token in material_name for token in ("装配式", "预制构件"))
            fallback_rows: list[dict] = []
            if prefer_page_fallback:
                fallback_rows = _query_material_page_fallback(conn, material_name, month, top_k=1)
                if not fallback_rows:
                    fallback_rows = _query_material_text_fallback(conn, material_name, month, top_k=5)
            else:
                fallback_rows = _query_material_text_fallback(conn, material_name, month, top_k=5)
                if not fallback_rows:
                    fallback_rows = _query_material_page_fallback(conn, material_name, month, top_k=1)
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
def get_catalog_map(query: str, top_k: int = 12) -> str:
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
