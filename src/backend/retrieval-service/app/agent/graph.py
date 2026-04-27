"""
LangGraph Hybrid Agent: Forced-RAG + ReAct 补充
架构：
  query_analysis → forced_rag → evaluator → [passed? END : react_loop]
                                              ↓
                               react_node → [tool_calls? tool_node : synthesize_node]
                                              ↑                ↓
                                              └── tool_node ──┘
                               synthesize_node → evaluator → [passed? END : react_loop]

增强点：
  - query_analysis_node: 意图分类 + 实体抽取 + 子查询分解
  - retrieval_filter: 分数阈值 + 去重 + token_budget
  - tool_call_cache: 去重缓存防止重复调用
  - loop_detection: 检测 ReAct 循环
"""

import json
import re
import logging
import hashlib

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode, tools_condition

from app.agent.state import RAGAgentState
from app.agent.prompts import (
    SYSTEM_PROMPT,
    _strip_think_tags,
    invoke_llm,
    invoke_llm_with_tools,
)
from app.agent.retrieval_filter import filter_chunks
from app.agent.query_analyzer import (
    QueryAnalyzer,
    extract_appendix_standard_terms,
    extract_appendix_standard_title,
    extract_fee_standard_comparison_queries,
    extract_fill_requirement_search_term,
    extract_fee_formula_search_term,
    extract_quota_search_term,
    is_appendix_standard_query,
    is_fee_standard_comparison_query,
    is_fill_requirement_query,
    is_fee_formula_query,
)
from app.agent.tools import (
    concept_search,
    vector_search,
    keyword_search,
    graph_search,
    hybrid_search,
    pdf_page_search,
    price_query,
    text_search,
    calculator,
    python_eval,
    category_search,
    price_trend,
    rule_clause_search,
)
from app.agent.evaluator import evaluate_retrieval_quality
from app.agent.presentation_payloads import (
    _build_presentation_payload,
    _format_citations,
    _normalize_final_answer,
    _prune_chunks_for_query,
    finalize_presentation_payload,
    refine_citations_for_answer,
)

logger = logging.getLogger(__name__)

_graph = None
_checkpointer = None
_analyzer = QueryAnalyzer()

# ReAct 补充轮可用的工具（PG 优先，graph_search 已废弃返回空）
REACT_TOOLS = [concept_search, price_query, price_trend, rule_clause_search, text_search, hybrid_search, pdf_page_search, vector_search, keyword_search, category_search, calculator, python_eval]

# Executor 节点的系统提示 — 带自省要求
_REACT_SYSTEM = """你是工程造价知识库问答助手，可调用以下工具检索知识库：

工具说明：
- concept_search(query, top_k=6)：先命中问题核心概念，返回建议下钻工具与证据层级，再继续检索真实证据
- category_search(query, top_k=5)：目录索引检索，先用此工具确认材料/工艺所在章节编号，返回章节号+标题+页码
- rule_clause_search(query, doc_id='', doc_filename='', section='', page_start=0, page_end=0, top_k=8)：在已锁定文档和页段范围内二跳检索条文正文，目录命中后优先使用
- text_search(query, top_k=10)：全文+语义混合检索，适合费率标准、定额规范等文档；自动检索 fee_rates 结构化表
- hybrid_search(query, top_k=10)：**pgvector 向量 + BM25 全文双路融合（RRF 排序）**，同时查 text_chunks 与 chunk_vector_views；适合同义改写、语义模糊、定额子目等需要语义召回的场景；是 text_search 的语义增强版，优先于 text_search 用于定额/规范类问题
- pdf_page_search(query, top_k=8)：PDF 页级原文检索，适合规则条文兜底取证；返回最接近原文页面的片段
- price_query(material_name, year_month=None, specification=None)：精确查询建设工程【材料价格】（SQL），仅用于 price_records 表
- price_trend(material_name, start_month=None, end_month=None)：时序价格走势查询，返回某材料在时间范围内的月度均价列表（走势/趋势分析必用此工具）
- vector_search(query, top_k=10)：向量相似度检索，适合语义相关段落
- keyword_search(query, top_k=10)：关键词全文检索，适合精确名称匹配；自动检索 fee_rates 结构化表
- calculator(expression)：数学表达式计算
- python_eval(code)：Python代码执行（适合复杂计算）

费率标准专用路由规则（重要）：
- 含“推荐系数”、“推荐费率”、“费率标准”、“赶工措施费”、“文明施工费”的问题 → 使用 text_search 或 category_search（text_search 自动检索 fee_rates 结构化表）
- 定额消耗量/工艺描述类问题（如安装/装饰/建筑消耗量标准，同义词多、措辞不固定）→ 优先用 hybrid_search 而非 text_search
- 严禁对费率标准类问题使用 price_query（price_query 只查材料单价，不含费率系数）
- fee_rates 表会被 text_search/keyword_search/category_search 自动检索，无需手动 SQL
- 检索路径按顺序分化：数据库/向量索引 → OCR 字典化 JSON → PDF 页级原文；上一路命中充分时不要跳到下一路
- 价格走势/趋势/变化幅度类问题 → 必须使用 price_trend，不得用 price_query 逐期查询
- 费率版本对比（2023版 vs 2025版）→ 使用 keyword_search 并在参数中包含版本年份关键词

工作方式：
1. 优先用 concept_search 命中核心概念，再根据建议下钻到价格、条文或页级证据
2. 执行当前计划步骤，选用最合适的工具（价格类用 price_query，规范文件用 text_search）
3. 在发起新工具调用前，先评价上一步工具结果是否找到核心数据；若未找到，换关键词或换工具
4. 信息已足够时直接停止调用工具（不要重复搜索），由后续合成节点生成答案
5. 如果工具结果为空或不相关，明确说明检索失败，不要强行使用空结果

特殊检索规则（定额子目）：
- 定额文档的子目按材料/工艺命名，楼梯/墙面/柱面/天棚/楼地面等是章节分类词，不是材料名
- 检索定额子目前必须先用 category_search 确认材料所在章节编号，再带章节号做 text_search
- 一旦目录/章节命中，下一步必须用 rule_clause_search 在锁定文档和页段范围内下钻，不要回到无约束 text_search
- 禁止把位置限定词（楼梯/墙面/柱面/台阶/踢脚等）与材料名合并成一个检索词
- 若 text_search/keyword_search 返回空结果，立即去除位置限定词，只用材料名重试

严格禁止：在没有检索证据时编造数值或费率。
引用格式：【文件名 P页码】，如【费率标准 P4】
"""

# Planner 节点的系统提示 — 引导任务拆解
_PLANNER_SYSTEM = """你是工程造价专业规划助手。收到用户问题后，将其拆分为 1~4 个具体执行步骤。

规划原则：
- 简单问题（如单一价格/费率查询）只需 1 步
- 复杂问题（如多工程类型对比、计算+引用）可拆 2~4 步
- 每步格式：「动词 + 具体检索目标」，例如：「检索 2024年深圳市建筑人工单价」
- 不要规划「合成答案」这一步（由系统自动完成）
- 优先先做 concept_search 命中核心概念，再决定往结构化/OCR/PDF 哪条证据路径下钻
- 优先使用 price_query 查材料价格，text_search 查定额规范文件
- 三路检索原则：优先数据库和向量索引；结构化缺口再用 OCR JSON；仍不足时再用 pdf_page_search 做页级取证
- 含"推荐系数"、"推荐费率"、"费率标准"、"赶工"、"措施费"的问题 → 第一步用 text_search（不用 price_query）
  例："赶工措施费推荐系数" → 步骤1: text_search query="赶工措施费"
- 定额消耗量/施工工艺描述类问题（如安装/装饰/建筑工程消耗量标准）→ 第一步用 hybrid_search
- 价格对比查询规则（重要）：若问题要求对比不同时期的价格，必须拆分为多步，
  每步单独调用 price_query 并指定对应 year_month，不得合并为一步
  例：“对比2025-12和2023-12” → 步骤1: price_query year_month=2025-12，步骤2: price_query year_month=2023-12
- 价格走势/趋势分析查询（重要）：若问题涉及价格走势、变化趋势、同比/环比，必须使用 price_trend
  例：“从25年开始至今的价格走势” → 步骤1: price_trend material_name=xxx start_month=2025-01
- 费率版本对比（重要）：若问题含“2023版”/“2025版”，使用 keyword_search/text_search 时
  必须在查询词中包含版本年份，以确保分版本检索
  例：“2023版与2025版利润率” → 步骤1: keyword_search "2023 利润率"，步骤2: keyword_search "2025 利润率"

定额子目检索规则（重要）：
- 若问题涉及定额子目的人工费/材料费/机械费/消耗量，第一步必须是：
  调用 category_search 确认材料/工艺所在章节编号
- 第二步再用 text_search 带章节号检索具体子目数值
- 材料名与位置词（楼梯/墙面/地面）要分离，category_search 只传材料名

输出格式（纯 JSON，不含 markdown 代码块）：
{"steps": ["步骤1", "步骤2", ...]}
"""

_QUERY_TYPE_INSTRUCTIONS: dict[str, str] = {
    "trend_chart": "4. 先给出趋势结论（涨/跌/平稳，涨跌幅），再列关键时间节点数据；不要仅罗列数字",
    "comparison": "4. 先给对比结论（谁高/谁低/差距多少），再分别列各方数据，最后计算差值",
    "calculation": "4. 先列计算公式和费率来源，再逐步计算，最后给出带单位的结果",
    "price": "4. 给出价格数值时注明时间、规格、单位；多条记录按时间倒序排列",
    "default": "4. 先给出核心结论，再补充细节；语言自然流畅，避免机械罗列",
}


# ── 辅助函数 ────────────────────────────────────────────────────────────────

def _enrich_chunks_with_filename(chunks: list) -> list:
    """批量查 PG，给 chunks 注入 doc_filename 字段（同时查 text_chunks 和 price_records）"""
    if not chunks:
        return chunks
    doc_ids = list({c.get("doc_id") for c in chunks if c.get("doc_id")})
    if not doc_ids:
        return chunks
    try:
        from app.agent.tools import _get_pg_conn, _put_pg_conn
        conn = _get_pg_conn()
        id_to_name: dict = {}
        try:
            with conn.cursor() as cur:
                placeholders = ",".join(["%s"] * len(doc_ids))
                cur.execute(
                    f"SELECT DISTINCT doc_id, file_name FROM text_chunks WHERE doc_id IN ({placeholders})",
                    doc_ids,
                )
                id_to_name = {r[0]: r[1] for r in cur.fetchall()}
                # 兜底：price_records 中查找 text_chunks 未覆盖的 doc_id
                missing = [d for d in doc_ids if d not in id_to_name]
                if missing:
                    m_ph = ",".join(["%s"] * len(missing))
                    cur.execute(
                        f"SELECT DISTINCT doc_id, file_name FROM price_records WHERE doc_id IN ({m_ph})",
                        missing,
                    )
                    for r in cur.fetchall():
                        id_to_name[r[0]] = r[1]
        finally:
            _put_pg_conn(conn)
        for c in chunks:
            c["doc_filename"] = id_to_name.get(c.get("doc_id", ""), "")
    except Exception as e:
        logger.warning(f"[enrich_filename] failed: {e}")
    return chunks


def _collect_chunks(tool_result_str: str, existing_chunks: list) -> list:
    """从工具返回的 JSON 字符串中提取 chunks，去重后追加"""
    try:
        result_data = json.loads(tool_result_str)
        if not isinstance(result_data, list):
            return existing_chunks
        existing_ids = {c.get("chunk_id") for c in existing_chunks}
        for c in result_data:
            cid = c.get("chunk_id")
            if cid and cid not in existing_ids:
                existing_chunks.append(c)
                existing_ids.add(cid)
    except Exception:
        pass
    return existing_chunks


_SECTION_ID_RE = re.compile(r"^\d{1,2}(?:\.\d{1,2})+$")
_REFUSAL_RE = re.compile(
    r"无法直接回答|无法回答|无法确认|无法给出可靠结论|暂时无法给出可靠结论|"
    r"知识库中未检索到相关信息|未检索到可用原文|未检索到直接依据|未检索到直接价格依据|"
    r"现有检索结果不足|暂无可用来源"
)


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _looks_like_refusal_answer(answer: str) -> bool:
    return bool(_REFUSAL_RE.search(_compact_text(answer)))


def _is_catalog_evidence(chunk: dict) -> bool:
    metadata = chunk.get("metadata") or {}
    return metadata.get("evidence_kind") == "pdf_catalog_chunk"


def _has_substantive_evidence(chunks: list[dict]) -> bool:
    return any(
        chunk.get("source_db") != "concept_search" and not _is_catalog_evidence(chunk)
        for chunk in chunks
    )


def _build_answer_evaluation(query_type: str, final_answer: str, chunks: list[dict]) -> dict:
    catalog_hits = sum(1 for chunk in chunks if _is_catalog_evidence(chunk))
    usable_hits = sum(
        1
        for chunk in chunks
        if chunk.get("source_db") != "concept_search" and not _is_catalog_evidence(chunk)
    )
    refusal = _looks_like_refusal_answer(final_answer)
    only_catalog = catalog_hits > 0 and usable_hits == 0
    source_count = len(
        {
            chunk.get("doc_filename") or chunk.get("source") or chunk.get("doc_id")
            for chunk in chunks
            if chunk.get("doc_filename") or chunk.get("source") or chunk.get("doc_id")
        }
    )

    if refusal and only_catalog:
        confidence = 0.2
        passed = False
        feedback = "catalog_only_refusal"
    elif query_type == "standard_ref" and only_catalog:
        confidence = 0.32
        passed = False
        feedback = "catalog_only_insufficient"
    elif refusal and usable_hits == 0:
        confidence = 0.25
        passed = False
        feedback = "refusal_without_evidence"
    else:
        confidence = 0.35 if usable_hits == 0 else min(0.93, 0.56 + usable_hits * 0.08 + min(0.12, max(0, source_count - 1) * 0.04))
        passed = usable_hits > 0 and not refusal
        feedback = "ok" if passed else "insufficient_evidence"
        if refusal:
            confidence = min(confidence, 0.45)
            passed = False
            feedback = "refusal_with_evidence"

    completeness = min(1.0, usable_hits / 4) if usable_hits else (0.2 if catalog_hits else 0.0)
    coverage_estimate = min(1.0, (usable_hits + min(catalog_hits, 1)) / 4) if chunks else 0.0
    source_diversity = min(1.0, source_count / 3) if source_count else 0.0

    return {
        "passed": passed,
        "confidence": round(confidence, 3),
        "completeness": round(completeness, 3),
        "consistency": 0.9 if usable_hits else 0.45,
        "information_gain": round(min(1.0, usable_hits / 3), 3),
        "source_diversity": round(source_diversity, 3),
        "fact_consistency": 0.88 if usable_hits else 0.4,
        "coverage_estimate": round(coverage_estimate, 3),
        "feedback": feedback,
        "catalog_hits": catalog_hits,
        "usable_hits": usable_hits,
    }


def _build_rule_clause_search_query(query: str) -> str:
    if is_fill_requirement_query(query):
        fill_field = extract_fill_requirement_search_term(query)
        if fill_field:
            return fill_field
    if is_appendix_standard_query(query):
        standard_title = extract_appendix_standard_title(query)
        clause_terms = extract_appendix_standard_terms(query)
        appendix_query = " ".join([standard_title, *clause_terms]).strip()
        if appendix_query:
            return appendix_query
    if is_fee_formula_query(query):
        fee_query = extract_fee_formula_search_term(query).replace("计算公式", "").strip()
        if fee_query:
            return fee_query
    quota_term = extract_quota_search_term(query)
    return quota_term or query.strip()


def _extract_catalog_entries(content: str) -> list[tuple[str, int]]:
    entries: list[tuple[str, int]] = []
    pending_section = ""
    for raw_line in content.splitlines():
        line = _compact_text(raw_line)
        if not line:
            continue

        direct_match = re.match(
            r"(?P<section>\d{1,2}(?:\.\d{1,2})+)(?P<title>.*?)(?:[.·…]{2,})?(?P<page>\d{1,4})$",
            line,
        )
        if direct_match:
            entries.append((direct_match.group("section"), int(direct_match.group("page"))))
            pending_section = ""
            continue

        section_match = re.match(r"(?P<section>\d{1,2}(?:\.\d{1,2})+)(?P<title>.+)$", line)
        if section_match:
            pending_section = section_match.group("section")
            continue

        digits = re.sub(r"[^0-9]", "", line)
        if pending_section and digits and len(digits) <= 4:
            entries.append((pending_section, int(digits)))
            pending_section = ""

    return entries


def _resolve_catalog_page_window(content: str, section: str, fallback_page: int) -> tuple[int, int]:
    if not section:
        return fallback_page, fallback_page + 6 if fallback_page else 0

    entries = _extract_catalog_entries(content)
    anchor_page = 0
    next_page = 0
    for index, (entry_section, page) in enumerate(entries):
        if entry_section != section:
            continue
        anchor_page = page
        if index + 1 < len(entries):
            next_page = entries[index + 1][1] - 1
        break

    if anchor_page <= 0:
        anchor_page = fallback_page
    if next_page <= 0 or next_page < anchor_page:
        next_page = anchor_page + 6 if anchor_page else 0
    return anchor_page, next_page


def _resolve_chapter_scope(query: str, chunks: list[dict]) -> dict | None:
    if not chunks:
        return None

    core_query = _compact_text(_build_rule_clause_search_query(query))
    best_scope: dict | None = None
    best_score: tuple[int, int, int, int, int, int, float] | None = None

    for chunk in _enrich_chunks_with_filename(list(chunks)):
        content = str(chunk.get("content") or "")
        compact_content = _compact_text(content)
        section = str(chunk.get("section") or "").strip()
        if section and not _SECTION_ID_RE.match(section):
            section = ""
        page_number = int(chunk.get("page_number") or 0)
        exact_term_hit = bool(core_query and core_query in compact_content)
        exact_section_hit = bool(section and compact_content.startswith(section))
        page_start, page_end = _resolve_catalog_page_window(content, section, page_number)
        score = (
            1 if exact_term_hit else 0,
            1 if exact_section_hit else 0,
            1 if page_start > 20 else 0,
            section.count(".") if section else 0,
            1 if chunk.get("doc_filename") else 0,
            page_start,
            float(chunk.get("score") or 0.0),
        )
        if best_score is not None and score <= best_score:
            continue
        best_score = score
        best_scope = {
            "target_doc_id": str(chunk.get("doc_id") or ""),
            "target_doc_filename": str(chunk.get("doc_filename") or ""),
            "target_section": section,
            "target_page_start": page_start,
            "target_page_end": page_end,
        }

    return best_scope


def _build_scope_hint(state: RAGAgentState) -> str:
    doc_name = str(state.get("target_doc_filename") or "")
    section = str(state.get("target_section") or "")
    page_start = int(state.get("target_page_start") or 0)
    page_end = int(state.get("target_page_end") or 0)
    parts = []
    if doc_name:
        parts.append(doc_name)
    if section:
        parts.append(f"section={section}")
    if page_start > 0:
        if page_end > 0 and page_end >= page_start:
            parts.append(f"pages={page_start}-{page_end}")
        else:
            parts.append(f"page={page_start}")
    return ", ".join(parts)


def _build_forced_rule_clause_tool_call(state: RAGAgentState) -> dict | None:
    if not state.get("force_clause_drilldown"):
        return None

    doc_id = str(state.get("target_doc_id") or "")
    doc_filename = str(state.get("target_doc_filename") or "")
    if not doc_id and not doc_filename:
        return None

    query = _build_rule_clause_search_query(state["query"])
    section = str(state.get("target_section") or "")
    page_start = int(state.get("target_page_start") or 0)
    page_end = int(state.get("target_page_end") or 0)
    if page_start > 0 and page_end <= 0:
        page_end = page_start + 6

    args = {
        "query": query,
        "doc_id": doc_id,
        "doc_filename": doc_filename,
        "section": section,
        "page_start": page_start,
        "page_end": page_end,
        "top_k": 6,
    }
    tool_hash = hashlib.md5(json.dumps(args, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return {
        "id": f"forced_rule_clause_{tool_hash}",
        "name": "rule_clause_search",
        "args": args,
        "type": "tool_call",
    }


def _build_synthesis_prompt(query: str, chunks: list, query_type: str = "semantic") -> str:
    """把检索结果拼成 prompt，让 LLM 生成答案"""
    if not chunks:
        return (
            f"用户问题：{query}\n\n"
            "知识库中未检索到相关信息。请按以下结构回复：\n"
            "第一段直接说明当前无法确认答案，不要复述问题。\n"
            "第二段以\"简要分析：\"开头，说明知识库未检索到可用原文。\n"
            "第三段以\"参考索引：\"开头，并写 [1] 暂无可用来源。"
        )

    chunks = sorted(chunks, key=lambda x: x.get("score", 0), reverse=True)
    chunks_text = ""
    for i, c in enumerate(chunks[:8], 1):
        doc_name = c.get("doc_filename") or c.get("source") or ""
        page = c.get("page_number") or c.get("page") or "?"
        score = c.get("score", 0)
        content = c.get("content", "")[:600]
        retrieval_path = str((c.get("metadata") or {}).get("retrieval_path") or c.get("retrieval_path") or "")
        path_label = {
            "database": "数据库",
            "ocr_json": "OCR JSON",
            "pdf_page": "PDF页",
        }.get(retrieval_path, "未标注路径")
        display = doc_name.replace(".pdf", "").replace(".xlsx", "").replace(".docx", "")
        display = display.strip("《》")
        ref_label = f"《{display}》P{page}" if doc_name else f"来源[{i}]"
        chunks_text += f"\n证据{i}：来源 {ref_label}，路径 {path_label}，相关度 {score:.4f}\n内容：{content}\n"

    first_ref = ""
    if chunks:
        fn = chunks[0].get("doc_filename") or chunks[0].get("source") or ""
        pg = chunks[0].get("page_number") or chunks[0].get("page") or "?"
        display0 = fn.replace(".pdf", "").replace(".xlsx", "").replace(".docx", "")
        first_ref = f"《{display0}》P{pg}" if fn else "来源[1]"

    query_type_hint = _QUERY_TYPE_INSTRUCTIONS.get(query_type, _QUERY_TYPE_INSTRUCTIONS["default"])

    # 提取回退注记，用于提示合成器
    fallback_notices = []
    for c in chunks[:8]:
        content = c.get("content", "")
        if content.startswith("[注：") and "无数据" in content:
            import re as _re
            m = _re.match(r'(\[注：[^\]]+\])', content)
            if m:
                fallback_notices.append(m.group(1))
    fallback_hint = ""
    if fallback_notices:
        fallback_hint = (
            "\n4. 检索结果含以下回退注记，表示原请求期间无数据，已返回最近可用期间数据。"
            "请在答案中明确说明原期间缺失，并引用回退数据作参考：\n"
            + "\n".join(f"   - {n}" for n in fallback_notices) + "\n"
        )

    catalog_only_hint = ""
    if query_type == "standard_ref" and chunks and not _has_substantive_evidence(chunks) and any(_is_catalog_evidence(c) for c in chunks):
        catalog_only_hint = (
            "\n5. 当前只有目录/索引命中，没有条文正文。必须明确说明无法确认具体条文内容，"
            "不能把目录标题或目录页内容当作最终规则答案。\n"
        )

    return (
        f"用户问题：{query}\n\n"
        f"知识库检索结果（共 {len(chunks)} 条，已按相关度排序）\n"
        f"{chunks_text}\n"
        f"回答要求\n"
        f"1. 严格基于上述检索结果回答，每处数值后必须用【文件名 P页码】格式标注来源，如 【{first_ref}】；\n"
        f"   每条价格数据至少标注一次来源，禁止用\"来源为各期价格文件\"等模糊表述代替具体引用\n"
        f"2. 数值（金额、比例、系数）必须来自检索结果原文，不得编造\n"
        f"3. {query_type_hint}\n"
        f"{fallback_hint}\n"
        f"{catalog_only_hint}"
        "格式要求（必须遵守）\n"
        "1. 第一段直接回答用户问题，不写\"【问题】\"\"【结论】\"等标签。\n"
        "2. 第二段以\"简要分析：\"开头，只保留关键依据、对比逻辑或必要计算过程，不要展开冗长思维记录。\n"
        "3. 否定答案简短处理——信息不足时一句说清缺什么即可，不要反复论证为什么缺。\n"
        "4. 禁止使用任何 Markdown 符号，包括 #、##、###、-、*、>、```、|。\n"
        "5. 公式和计算仅用普通文本，不要 LaTeX，不要 Markdown 表格。\n"
        "6. 禁止输出\"参考索引：\"段——系统会自动追加真实来源，你只需输出前两段。"
    )


def _detect_loop(state: RAGAgentState) -> bool:
    """检测 tool_call 是否与缓存重复"""
    last_msg = state["messages"][-1]
    if not hasattr(last_msg, "tool_calls"):
        return False
    cache = state.get("tool_call_cache", {})
    for tc in last_msg.tool_calls:
        key = tc["name"] + json.dumps(tc["args"], sort_keys=True)
        if key in cache:
            logger.warning(f"[loop_detect] duplicate tool call: {key}")
            return True
    return False


def _cache_tool_calls(state: RAGAgentState, results: list):
    """将工具调用结果写入缓存"""
    last_msg = state["messages"][-1]
    if not hasattr(last_msg, "tool_calls"):
        return
    cache = state.get("tool_call_cache", {})
    for tc, result in zip(last_msg.tool_calls, results):
        key = tc["name"] + json.dumps(tc["args"], sort_keys=True)
        cache[key] = str(result)
    state["tool_call_cache"] = cache


# ── 节点函数 ────────────────────────────────────────────────────────────────

_DOMAIN_RE = re.compile(
    r"工程|造价|定额|费率?|价格|材料|施工|建设|规范|标准|计算|工期|招标|合同|税|"
    r"人工|机械|建筑|市政|安装|措施|费用|系数|推荐|预算|决算|清单|概算|签证|变更"
)


def _is_off_topic(query: str) -> bool:
    return not bool(_DOMAIN_RE.search(query))


# 闲聊检测：打招呼/自我介绍类直接回复，不走 RAG
_CHITCHAT_RE = re.compile(
    r"^(你好|您好|hi|hello|哈喽|早上好|下午好|晚上好|嗨|嘿|hey"
    r"|你是谁|你是什么|你叫什么|介绍一下自己|你能做什么|你能帮我什么|怎么用|如何使用"
    r"|谢谢|感谢|多谢|很好|非常好|好的|明白了|我知道了"
    r")[！!？?。\s]*$",
    re.IGNORECASE
)

# 定额/合规查询检测 — 触发 category_search 前置步骤
_QUOTA_RE = re.compile(
    r"定额|消耗量标准|子目|人工费|材料费|机械费|工料机|合规|计价规范|计算规则"
)

# 位置限定词 — 检索失败时从查询词中剔除
_STRIP_LOCATION_RE = re.compile(
    r"楼梯|墙面|柱面|台阶|天棚|楼地面|地面|顶面|踢脚|外墙|内墙|屋面|坡屋面|吊顶|地坪|面层"
)

# 价格对比查询检测 — 提取两个时间段
_PRICE_COMPARE_RE = re.compile(
    r"对比.*?(\d{4}[年\-/]\d{1,2}月?).*?(\d{4}[年\-/]\d{1,2}月?)|"
    r"(\d{4}[年\-/]\d{1,2}月?).*?(?:和|与|vs|对比|比较).*?(\d{4}[年\-/]\d{1,2}月?).*?价格",
    re.DOTALL
)


def _looks_like_annual_price_query(query: str, entities: dict) -> bool:
    """检测是否为全年/某年度价格查询（year_month 仅含年份，或查询中明确提到'全年'/'年度'）。"""
    year_month = str(entities.get("year_month") or "")
    # year-only pattern e.g. "2025" or "2025年"
    if re.fullmatch(r"\d{4}年?", year_month.strip()):
        return True
    if any(kw in query for kw in ("全年", "年度", "当年", "整年")):
        return True
    return False


def _looks_like_multi_material_price_change_query(query: str, entities: dict) -> bool:
    """检测是否为多材料价格变化查询（material_names 有多项，或查询含'变化/涨跌/幅度'等）。"""
    material_names = entities.get("material_names") or []
    if isinstance(material_names, list) and len(material_names) >= 2:
        return True
    change_keywords = ("变化", "涨跌", "幅度", "涨幅", "跌幅", "价格变化", "价格涨", "价格跌", "较上月", "环比")
    return any(kw in query for kw in change_keywords)


def _previous_month(year_month: str) -> str:
    """返回给定月份的上一个月，格式与输入一致 (YYYY-MM 或 YYYY年MM月)。"""
    if not year_month:
        return ""
    try:
        m = re.search(r"(\d{4})[年\-/](\d{1,2})", year_month)
        if not m:
            return year_month
        year, month = int(m.group(1)), int(m.group(2))
        if month == 1:
            year, month = year - 1, 12
        else:
            month -= 1
        sep = "年" if "年" in year_month else "-"
        end = "月" if "月" in year_month else ""
        return f"{year}{sep}{month:02d}{end}"
    except Exception:
        return year_month


def query_analysis_node(state: RAGAgentState) -> dict:
    """
    查询分析节点：意图分类 + 实体抽取 + 子查询分解
    """
    query = state["query"].strip()

    # 闲聊：直接回复，不走 RAG
    if _CHITCHAT_RE.search(query):
        logger.info(f"[query_analysis] chitchat: {query[:40]}")
        return {
            "query_type": "chitchat",
            "sub_queries": [],
            "final_answer": "您好！我是工程造价智能问答助手，专注于深圳市建设工程定额、费率标准、材料信息价等领域。有什么造价问题欢迎随时提问！",
        }

    # 真正 off-topic：拒绝回答
    if _is_off_topic(query):
        logger.info(f"[query_analysis] off-topic: {query[:40]}")
        return {
            "query_type": "irrelevant",
            "sub_queries": [],
            "final_answer": "您好！我是专注于工程造价领域的智能问答助手，只能回答与建设工程定额、费率标准、材料信息价等相关的问题。",
        }
    analysis = _analyzer.analyze(query)
    return {
        "query_type": analysis["intent"],
        "query_entities": analysis["entities"],
        "sub_queries": analysis["sub_queries"],
    }


def forced_rag_node(state: RAGAgentState) -> dict:
    """已废弃 — 保留签名以防止旧引用报错，实际不再挂载到 graph。"""
    raise RuntimeError("forced_rag_node is no longer part of the graph")


def _parse_plan(content: str) -> list[str]:
    """从 LLM 输出中提取步骤列表，容忍格式噪声。"""
    # 去掉 think 标签和 markdown 代码块
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    content = re.sub(r"```[\w]*\n?", "", content).strip()
    try:
        data = json.loads(content)
        steps = data.get("steps", [])
        if isinstance(steps, list) and steps:
            return [str(s) for s in steps]
    except Exception:
        pass
    # 降级：按行解析（如 "1. xxx" 或 "- xxx"）
    steps = []
    for line in content.splitlines():
        line = re.sub(r"^[\d\-\*\．。]+[\.\s]+", "", line.strip())
        if len(line) > 3:
            steps.append(line)
    return steps[:4] if steps else [state["query"] if False else ""]


def planner_node(state: RAGAgentState) -> dict:
    """
    规划节点：用强模型将用户问题拆分为 1~4 个执行步骤，写入 plan + current_step。
    首次调用时向 messages channel 注入 system + user 消息。
    """
    query = state["query"]
    entities = state.get("query_entities") or {}
    llm_config = state.get("llm_config") or {}
    logger.info(f"[planner] query='{query[:60]}'")

    try:
        response, runtime = invoke_llm(
            [
                SystemMessage(content=_PLANNER_SYSTEM),
                HumanMessage(content=f"用户问题：{query}"),
            ],
            thinking=False,
            prefer_strong=True,
            llm_config=llm_config,
        )
        steps = _parse_plan(response.content or "")
    except Exception as e:
        logger.error(f"[planner] LLM failed: {e}, fallback to single step")
        steps = [query]
        runtime = state.get("llm_runtime") or {}

    if not steps or (len(steps) == 1 and not steps[0]):
        steps = [query]

    if state.get("query_type") in {"price", "trend_chart", "comparison", "standard_ref"}:
        first_step_lower = steps[0].lower() if steps else ""
        if "concept_search" not in first_step_lower and "概念" not in steps[0]:
            steps = [f"使用 concept_search 命中『{query}』中的核心概念并确认下钻方向"] + steps
            logger.info("[planner] prepended concept_search step")

    # 定额/合规查询：若 LLM 未主动规划 category_search，确定性地前置一步
    if _QUOTA_RE.search(query):
        first_step_lower = steps[0].lower() if steps else ""
        if "category_search" not in first_step_lower and "目录" not in steps[0]:
            core_material = extract_quota_search_term(query) or query
            steps = [f"调用 category_search 确认『{core_material}』所在章节编号"] + steps
            logger.info(f"[planner] quota query detected, prepended category_search step, core='{core_material}'")

    if is_fee_formula_query(query):
        core_term = extract_fee_formula_search_term(query)
        steps = [
            f"使用 text_search 检索『{core_term}』原文公式",
            f"如需补充费率范围，再使用 keyword_search 检索『{core_term.replace('计算公式', '推荐费率')}』",
        ]
        logger.info(f"[planner] fee formula query override, core='{core_term}'")

    if is_fee_standard_comparison_query(query):
        comparison_queries = extract_fee_standard_comparison_queries(query)
        steps = [f"使用 text_search 检索『{term}』费率标准原文" for term in comparison_queries]
        logger.info(f"[planner] fee comparison override, queries={comparison_queries}")

    if is_fill_requirement_query(query):
        fill_field = extract_fill_requirement_search_term(query)
        steps = [
            f"使用 text_search 检索『{fill_field} 应填写』原文要求",
            f"如需补充上下文，再使用 keyword_search 检索『{fill_field} 填写』相关条文",
        ]
        logger.info(f"[planner] fill requirement override, field='{fill_field}'")

    if is_appendix_standard_query(query):
        standard_title = extract_appendix_standard_title(query)
        clause_terms = extract_appendix_standard_terms(query)
        clause_query = " ".join([standard_title, *clause_terms]).strip()
        steps = [
            f"使用 text_search 检索『{clause_query}』附件标准原文",
            f"如需补充上下文，再使用 keyword_search 检索『{clause_query}』相关条文",
        ]
        logger.info(
            f"[planner] appendix standard override, title='{standard_title}' terms={clause_terms}"
        )

    if state.get("query_type") == "price" and _looks_like_annual_price_query(query, entities):
        annual_period = str(entities.get("year_month") or "")
        annual_material = str(entities.get("material_name") or "")
        steps = [
            f"使用 price_query 查询『{annual_material}』在 {annual_period} 年的信息价记录",
            f"若 price_query 无结果，仅使用 keyword_search 精确检索『{annual_period} 深圳 信息价 {annual_material}』原文，禁止拆分材料名称",
        ]
        logger.info(f"[planner] annual price query override, period='{annual_period}' material='{annual_material}'")

    if state.get("query_type") in {"price", "trend_chart"} and _looks_like_multi_material_price_change_query(query, entities):
        period = str(entities.get("year_month") or "")
        previous_period = _previous_month(period)
        materials = [str(item).strip() for item in (entities.get("material_names") or []) if str(item).strip()]
        steps = [
            f"使用 price_trend 查询『{material}』在 {previous_period} 至 {period} 的月度价格变化"
            for material in materials
        ]
        logger.info(
            f"[planner] multi-material price change override, period='{period}' "
            f"previous='{previous_period}' materials={materials}"
        )

    # 价格对比查询：提取两个期间，确保每个期间都有独立的 price_query 步骤
    price_compare_match = _PRICE_COMPARE_RE.search(query)
    if price_compare_match:
        groups = [g for g in price_compare_match.groups() if g]
        if len(groups) >= 2:
            period1, period2 = groups[0], groups[1]
            # 检查 plan 里是否已有两个不同期间的步骤
            plan_text = " ".join(steps)
            if period1 not in plan_text or period2 not in plan_text:
                # 提取规格词（去掉日期/动词/介词）
                spec_part = re.sub(r'\d{4}[年\-/]\d{1,2}月?|对比|查询|检索|工程建设信息价|深圳市|中|和|与', '', query).strip()
                steps = [
                    f"使用 price_query 查询 {period1} 的价格：{spec_part}",
                    f"使用 price_query 查询 {period2} 的价格：{spec_part}",
                ]
                logger.info(f"[planner] price compare override: {period1} vs {period2}")

    logger.info(f"[planner] plan={steps}")
    # Channel seed：将 system + user 注入 messages，executor_node 追加
    seed_messages = [
        SystemMessage(content=_REACT_SYSTEM),
        HumanMessage(content=query),
    ]
    return {
        "messages": seed_messages,
        "plan": steps,
        "current_step": 0,
        "thought_process": [],
        "category_hints": [],
        "target_doc_id": "",
        "target_doc_filename": "",
        "target_section": "",
        "target_page_start": 0,
        "target_page_end": 0,
        "force_clause_drilldown": False,
        "fallback_mode": False,
        "llm_runtime": runtime,
    }


def executor_node(state: RAGAgentState) -> dict:
    """
    执行节点：根据当前计划步骤调用工具（tool_choice=auto）。
    - 如果 LLM 决定不调工具：记录自省、步骤+1
    - 如果工具返回为空：注入 fallback 提示让 LLM 换词重试
    - Loop 检测：重复调用则跳过当前步骤
    """
    iteration = state.get("iterations", 0)
    max_iter = state.get("max_iterations", 3)
    plan = state.get("plan") or [state["query"]]
    current_step = state.get("current_step", 0)
    thought_process = list(state.get("thought_process") or [])
    llm_config = state.get("llm_config") or {}

    # 最后一轮用 auto，允许 LLM 自行判断是否还需要工具
    tool_choice = "auto" if iteration >= max_iter - 1 else "required"

    messages = list(state["messages"])

    # Loop 检测：重复 tool call → 跳过步骤
    if iteration > 0 and _detect_loop(state):
        logger.warning(f"[executor] loop detected at step={current_step}, skipping")
        thought = f"步骤{current_step+1}检测到重复调用，跳过"
        thought_process.append(thought)
        return {
            "messages": [HumanMessage(content=thought)],
            "iterations": max_iter,  # 强制结束循环
            "current_step": current_step + 1,
            "thought_process": thought_process,
            "has_tool_calls": False,
        }

    # 构造当前步骤的提示（让模型感知进度）
    step_hint = plan[current_step] if current_step < len(plan) else plan[-1]
    progress = f"{current_step + 1}/{len(plan)}"

    forced_tool_call = _build_forced_rule_clause_tool_call(state)
    if forced_tool_call is not None:
        scope_hint = _build_scope_hint(state)
        forced_step_hint = f"强制调用 rule_clause_search 下钻条文正文（{scope_hint}）" if scope_hint else "强制调用 rule_clause_search 下钻条文正文"
        thought_process.append(f"步骤{current_step+1}：{forced_step_hint}")
        step_msg = HumanMessage(content=f"[当前进度 {progress}] {forced_step_hint}")
        forced_response = AIMessage(content="", tool_calls=[forced_tool_call])
        logger.info(f"[executor] forced rule_clause_search: {forced_tool_call['args']}")
        return {
            "messages": [step_msg, forced_response],
            "iterations": iteration + 1,
            "current_step": current_step,
            "thought_process": thought_process,
            "has_tool_calls": True,
            "pending_tool_calls": [forced_tool_call],
            "step_number": current_step + 1,
            "total_steps": len(plan),
            "step_hint": forced_step_hint,
            "force_clause_drilldown": False,
            "llm_runtime": state.get("llm_runtime") or {},
        }

    # 如果有章节定位提示，注入到步骤消息中帮助 LLM 精准检索
    category_hints = state.get("category_hints") or []
    scope_hint = _build_scope_hint(state)
    if scope_hint:
        step_content = f"[已锁定检索范围：{scope_hint}]\n[当前进度 {progress}] 请执行：{step_hint}"
    elif category_hints:
        hints_str = "；".join(category_hints[:3])
        step_content = f"[章节定位参考：{hints_str}]\n[当前进度 {progress}] 请执行：{step_hint}"
    else:
        step_content = f"[当前进度 {progress}] 请执行：{step_hint}"

    step_msg = HumanMessage(content=step_content)
    # 防止 dangling tool_calls 导致 HTTP 400：移除末尾没有对应 ToolMessage 的 AIMessage(tool_calls)
    clean_messages = []
    for i, msg in enumerate(messages):
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            if i + 1 < len(messages) and hasattr(messages[i + 1], "tool_call_id"):
                clean_messages.append(msg)
            # 否则跳过：dangling AIMessage(tool_calls) 没有对应 ToolMessage
        else:
            clean_messages.append(msg)
    messages_for_llm = clean_messages + [step_msg]
    if len(clean_messages) != len(messages):
        logger.warning(f"[executor] stripped {len(messages) - len(clean_messages)} dangling tool_call messages")

    logger.info(f"[executor] iter={iteration}/{max_iter} step={progress} tool_choice={tool_choice}")

    try:
        response, runtime = invoke_llm_with_tools(
            messages_for_llm,
            REACT_TOOLS,
            tool_choice=tool_choice,
            thinking=False,
            prefer_strong=False,
            llm_config=llm_config,
        )
    except Exception as e:
        logger.error(f"[executor] LLM failed: {e}")
        response = AIMessage(content="")
        runtime = state.get("llm_runtime") or {}

    if response.tool_calls:
        logger.info(f"[executor] tool calls: {[tc['name'] for tc in response.tool_calls]}")
        return {
            "messages": [step_msg, response],
            "iterations": iteration + 1,
            "current_step": current_step,
            "thought_process": thought_process,
            "has_tool_calls": True,
            "step_number": current_step + 1,
            "total_steps": len(plan),
            "step_hint": step_hint,
            "pending_tool_calls": response.tool_calls,
            "llm_runtime": runtime,
        }
    else:
        # 无工具调用：自省并推进步骤
        thought = _strip_think_tags(response.content or "")
        thought_process.append(f"步骤{current_step+1}：{thought[:120]}")
        logger.info(f"[executor] no tool call at step={current_step}, advancing")
        return {
            "messages": [step_msg, AIMessage(content=thought)],
            "iterations": iteration + 1,
            "current_step": current_step + 1,
            "thought_process": thought_process,
            "has_tool_calls": False,
            "step_number": current_step + 1,
            "total_steps": len(plan),
            "step_hint": step_hint,
            "pending_tool_calls": [],
            "step_summary": thought[:200],
            "llm_runtime": runtime,
        }


_prebuilt_tool_node = ToolNode(REACT_TOOLS)


def tool_node(state: RAGAgentState) -> dict:
    """LangGraph ToolNode 处理工具调用和 ToolMessage 组装；补充 chunk 收集和 fallback 检测。"""
    result = _prebuilt_tool_node.invoke(state)
    previous_chunks = list(state.get("retrieved_chunks") or [])
    all_chunks = list(previous_chunks)
    category_hints = list(state.get("category_hints") or [])
    tool_results = []
    new_chunk_count = 0
    query_entities = state.get("query_entities") or {}

    for msg in result.get("messages", []):
        content_str = str(msg.content)
        before = len(all_chunks)
        all_chunks = _collect_chunks(content_str, all_chunks)
        new_chunk_count += len(all_chunks) - before
        tool_results.append(content_str)

        # 从 category_search 结果中提取章节定位提示
        try:
            cat_data = json.loads(content_str)
            if isinstance(cat_data, list) and cat_data:
                for item in cat_data[:3]:
                    if item.get("source_db") == "concept_search":
                        concept_name = item.get("metadata", {}).get("concept_name", "")
                        concept_type = item.get("metadata", {}).get("concept_type", "")
                        preferred_tool = item.get("metadata", {}).get("preferred_tool", "")
                        structured_hits = item.get("metadata", {}).get("structured_hits", 0)
                        text_hits = item.get("metadata", {}).get("text_hits", 0)
                        hint_str = (
                            f"概念 {concept_name}({concept_type}) → {preferred_tool}; "
                            f"结构化{structured_hits}条, 文本{text_hits}条"
                        )
                        if hint_str not in category_hints:
                            category_hints.append(hint_str)
                        continue
        except Exception:
            pass

    filtered = filter_chunks(all_chunks)
    filtered = _prune_chunks_for_query(
        state["query"],
        state.get("query_type", "semantic"),
        filtered,
        query_entities,
    )
    previous_ids = {chunk.get("chunk_id") for chunk in previous_chunks}
    effective_new_chunk_count = len(
        [chunk for chunk in filtered if chunk.get("chunk_id") not in previous_ids]
    )
    _cache_tool_calls(state, tool_results)
    logger.info(
        f"[tool_node] raw_new_chunks={new_chunk_count} effective_new_chunks={effective_new_chunk_count} "
        f"total={len(filtered)} cat_hints={len(category_hints)}"
    )

    # Fallback 提示：如果本轮工具返回了 0 个新 chunk，注入反馈让 executor 换词重试
    extra_messages = []
    advance_step = state.get("current_step", 0)
    if effective_new_chunk_count == 0:
        last_ai = next(
            (m for m in reversed(result.get("messages", []))
             if hasattr(m, "tool_calls") and m.tool_calls),
            None,
        )
        failed_tools = {tc["name"] for tc in (last_ai.tool_calls if last_ai else [])}

        # 检查是否是因为位置限定词导致的零结果
        fallback_mode = state.get("fallback_mode", False)
        if not fallback_mode and failed_tools & {"text_search", "keyword_search", "vector_search"}:
            # 尝试从失败的工具调用参数中提取查询词并剥离位置限定词
            original_query = ""
            if last_ai:
                for tc in last_ai.tool_calls:
                    if tc["name"] in {"text_search", "keyword_search", "vector_search"}:
                        original_query = tc["args"].get("query", "")
                        break
            stripped_query = extract_quota_search_term(original_query) if original_query else ""
            if stripped_query and stripped_query != original_query:
                hint = (
                    f"检索词『{original_query}』含位置限定词，导致零结果。"
                    f"已识别核心材料关键词：『{stripped_query}』。"
                    f"请改用 category_search('{stripped_query}') 先定位章节，"
                    f"或直接用 text_search('{stripped_query}') 重试。"
                )
                extra_messages = [HumanMessage(content=hint)]
                logger.warning(f"[tool_node] location-word fallback: '{original_query}' → '{stripped_query}'")
                return {
                    **result,
                    "retrieved_chunks": filtered,
                    "category_hints": category_hints,
                    "fallback_mode": True,
                    "messages": result.get("messages", []) + extra_messages,
                }

        # 通用 fallback 提示
        if "price_query" in failed_tools:
            if _looks_like_annual_price_query(state["query"], query_entities):
                annual_period = str(query_entities.get("year_month") or "")
                annual_material = str(query_entities.get("material_name") or "")
                hint = (
                    f"未检索到『{annual_period} 深圳信息价 {annual_material}』的直接价格依据。"
                    "禁止拆分材料名称，也不要继续使用无关材料词扩展搜索。"
                    f"如需复核，只能使用 keyword_search('{annual_period} 深圳 信息价 {annual_material}') "
                    "或 text_search 做精确检索；若仍无命中，请结束并明确说明未检索到直接价格依据。"
                )
                advance_step = min(state.get("current_step", 0) + 1, len(state.get("plan") or []))
            else:
                hint = (
                    "price_query 未查到价格数据（数据库中无该条目），"
                    "请改用 text_search、keyword_search 或 pdf_page_search 搜索相关价格文档和信息价表格。"
                )
        else:
            hint = "上一步工具未检索到相关内容，请更换关键词或切换工具（如用 text_search、pdf_page_search 替代 keyword_search）重新尝试。"
        logger.warning(f"[tool_node] no new chunks, hint: {hint[:60]}")
        extra_messages = [HumanMessage(content=hint)]

    return {
        **result,
        "retrieved_chunks": filtered,
        "category_hints": category_hints,
        "current_step": advance_step,
        "messages": result.get("messages", []) + extra_messages,
    }


def chapter_resolver_node(state: RAGAgentState) -> dict:
    if state.get("query_type") != "standard_ref":
        return {}

    retrieved_chunks = _enrich_chunks_with_filename(list(state.get("retrieved_chunks") or []))
    if any((chunk.get("metadata") or {}).get("evidence_kind") == "rule_clause_chunk" for chunk in retrieved_chunks):
        return {
            "retrieved_chunks": retrieved_chunks,
            "force_clause_drilldown": False,
        }

    catalog_chunks = [chunk for chunk in retrieved_chunks if _is_catalog_evidence(chunk)]
    if not catalog_chunks:
        return {"retrieved_chunks": retrieved_chunks}

    resolved_scope = _resolve_chapter_scope(state["query"], catalog_chunks)
    if not resolved_scope:
        return {"retrieved_chunks": retrieved_chunks}

    logger.info(
        "[chapter_resolver] doc=%s section=%s pages=%s-%s",
        resolved_scope.get("target_doc_filename") or resolved_scope.get("target_doc_id"),
        resolved_scope.get("target_section"),
        resolved_scope.get("target_page_start"),
        resolved_scope.get("target_page_end"),
    )
    return {
        "retrieved_chunks": retrieved_chunks,
        **resolved_scope,
        "force_clause_drilldown": True,
    }


def synthesize_node(state: RAGAgentState) -> dict:
    """
    合成节点：用 messages channel 中积累的全部 chunks 生成最终答案。
    """
    llm_config = state.get("llm_config") or {}
    query = state["query"]
    query_type = state.get("query_type", "semantic")
    all_chunks = state.get("retrieved_chunks", [])
    query_entities = state.get("query_entities") or {}

    all_chunks = [chunk for chunk in all_chunks if chunk.get("source_db") != "concept_search"]
    all_chunks = _enrich_chunks_with_filename(all_chunks)
    all_chunks = _prune_chunks_for_query(query, query_type, all_chunks, query_entities)
    logger.info(f"[synthesize] {len(all_chunks)} chunks, query_type={query_type}")
    synthesis_prompt = _build_synthesis_prompt(query, all_chunks, query_type)
    citations_text = _format_citations(all_chunks)
    presentation = _build_presentation_payload(query, query_type, all_chunks)

    evaluation = _build_answer_evaluation(query_type, "", all_chunks)

    if state.get("stream_response"):
        runtime = state.get("llm_runtime") or {}
        return {
            "messages": [],
            "final_answer": "",
            "evaluation": evaluation,
            "synthesis_prompt": synthesis_prompt,
            "citations_text": citations_text,
            "llm_runtime": runtime,
            "retrieved_chunks": all_chunks,
            "presentation": presentation,
        }

    try:
        response, runtime = invoke_llm(
            [HumanMessage(content=synthesis_prompt)],
            thinking=False,
            prefer_strong=False,
            llm_config=llm_config,
        )
        final_answer = response.content or ""
    except Exception as e:
        logger.error(f"[synthesize] LLM failed: {e}")
        final_answer = state.get("final_answer", "无法生成答案")
        runtime = state.get("llm_runtime") or {}

    from app.rag_pipeline import _strip_latex
    citations_text = refine_citations_for_answer(final_answer, all_chunks, citations_text)
    final_answer = _normalize_final_answer(query, _strip_latex(final_answer), all_chunks, citations_text, query_type)
    evaluation = _build_answer_evaluation(query_type, final_answer, all_chunks)
    presentation = finalize_presentation_payload(
        query=query,
        query_type=query_type,
        final_answer=final_answer,
        chunks=all_chunks,
        citations_text=citations_text,
        existing_presentation=presentation,
    )

    return {
        "messages": [AIMessage(content=final_answer)],
        "final_answer": final_answer,
        "evaluation": evaluation,
        "synthesis_prompt": synthesis_prompt,
        "citations_text": citations_text,
        "llm_runtime": runtime,
        "retrieved_chunks": all_chunks,
        "presentation": presentation,
    }


# ── 路由函数 ────────────────────────────────────────────────────────────────

def after_query_analysis(state: RAGAgentState) -> str:
    qt = state.get("query_type", "")
    return END if qt in ("irrelevant", "chitchat") else "planner_node"


def after_executor(state: RAGAgentState) -> str:
    """executor_node 之后：有 tool_calls → tool_node；否则检查是否继续。"""
    max_iter = state.get("max_iterations", 3)
    plan = state.get("plan") or []
    current_step = state.get("current_step", 0)
    iterations = state.get("iterations", 0)
    has_tool_calls = bool(state.get("has_tool_calls"))

    logger.info(f"[after_executor] iter={iterations}/{max_iter} step={current_step}/{len(plan)} has_tool_calls={has_tool_calls}")

    # 迭代上限优先：即使有 tool_calls 也强制合成，防止 LLM 无限循环调工具。
    # 注意：executor_node 已通过 clean_messages 去除末尾无配对 ToolMessage 的
    # AIMessage(tool_calls=[...])，所以这里跳过 tool_node 不会留下悬挂消息。
    if iterations >= max_iter:
        logger.info(f"[after_executor] max_iter reached, synthesize")
        return "synthesize_node"

    # 有待执行的工具调用
    if has_tool_calls:
        logger.info(f"[after_executor] → tool_node")
        return "tool_node"

    # 无工具调用：若计划步骤还未完成，继续执行下一步
    if current_step < len(plan):
        logger.info(f"[after_executor] no tool, next step {current_step}/{len(plan)}")
        return "executor_node"

    # 所有步骤执行完毕，进入合成
    logger.info("[after_executor] all steps done, synthesize")
    return "synthesize_node"


# ── 构建 Graph ──────────────────────────────────────────────────────────────

def build_agent_graph(checkpointer=None):
    """
    Thought-Plan-Act graph:

    query_analysis → planner_node → executor_node ↔ tool_node  (plan steps loop)
                                 ↓ chapter_resolver
                             chapter_resolver → executor_node
                                 ↓ (all steps done or max iter)
                                    synthesize_node → END
    """
    g = StateGraph(RAGAgentState)

    g.add_node("query_analysis", query_analysis_node)
    g.add_node("planner_node", planner_node)
    g.add_node("executor_node", executor_node)
    g.add_node("tool_node", tool_node)
    g.add_node("chapter_resolver", chapter_resolver_node)
    g.add_node("synthesize_node", synthesize_node)

    g.set_entry_point("query_analysis")

    g.add_conditional_edges(
        "query_analysis",
        after_query_analysis,
        {"planner_node": "planner_node", END: END},
    )

    g.add_edge("planner_node", "executor_node")

    g.add_conditional_edges(
        "executor_node",
        after_executor,
        {
            "tool_node": "tool_node",
            "executor_node": "executor_node",
            "synthesize_node": "synthesize_node",
        },
    )

    g.add_edge("tool_node", "chapter_resolver")
    g.add_edge("chapter_resolver", "executor_node")
    g.add_edge("synthesize_node", END)

    return g.compile(checkpointer=checkpointer)


def get_agent_graph():
    """获取编译后的 Agent Graph（带 MemorySaver Checkpoint）"""
    global _graph, _checkpointer
    if _graph is None:
        _checkpointer = MemorySaver()
        _graph = build_agent_graph(checkpointer=_checkpointer)
        logger.info("[Agent] Enhanced (Forced-RAG + ReAct + QueryAnalysis + RetrievalFilter) Graph compiled with MemorySaver")
    return _graph
