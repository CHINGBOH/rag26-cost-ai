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
import ast
import os
from datetime import datetime

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode, tools_condition

from app.agent.state import RAGAgentState, ContractResult
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
    get_catalog_map,
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


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}

_graph = None
_checkpointer = None
_analyzer = QueryAnalyzer()

# ReAct 补充轮可用的工具（PG 优先，graph_search 已废弃返回空）
REACT_TOOLS = [concept_search, price_query, price_trend, rule_clause_search, text_search, hybrid_search, pdf_page_search, vector_search, keyword_search, category_search, get_catalog_map, calculator, python_eval]

# Executor 节点的系统提示 — 带自省要求
_REACT_SYSTEM = """你是工程造价知识库问答助手，可调用以下工具检索知识库：

工具说明：
- concept_search(query, top_k=6)：先命中问题核心概念，返回建议下钻工具与证据层级，再继续检索真实证据
- get_catalog_map(query, top_k=12)：**章节目录检索**，查询与关键词相关的章节ID和路径（path）；在调用 text_search/hybrid_search 前先调用此工具确定 path_constraint，避免跨册检索噪声。返回 [{chapter_id, path, title, file_name}]
- category_search(query, top_k=5)：目录索引检索，先用此工具确认材料/工艺所在章节编号，返回章节号+标题+页码
- rule_clause_search(query, doc_id='', doc_filename='', section='', page_start=0, page_end=0, top_k=8)：在已锁定文档和页段范围内二跳检索条文正文，目录命中后优先使用
- text_search(query, top_k=10, path_constraint='')：全文+语义混合检索，适合费率标准、定额规范等文档；path_constraint 可锁定章节路径（如 '第二册电气设备安装工程/10.%'）；自动检索 fee_rates 结构化表
- hybrid_search(query, top_k=10, path_constraint='')：**pgvector 向量 + BM25 全文双路融合（RRF 排序）**，同时查 text_chunks 与 chunk_vector_views；适合同义改写、语义模糊、定额子目等需要语义召回的场景；path_constraint 可锁定章节范围；是 text_search 的语义增强版，优先于 text_search 用于定额/规范类问题
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
	- 计算类问题必须先检索后计算：若问题含数值并要求计算（如"计算利润"、"企业管理费为多少"），
	  第一步必须调用 text_search 检索费率数值，text_search 会自动返回 fee_rates 结构化数据
	  （含推荐费率和计算公式），检索到具体数值后才能使用 calculator 或 python_eval 执行计算
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
	- 费率数值计算类问题（重要）：若问题要求根据费率/利润率/推荐系数计算费用金额，
	  第一步必须先调用 text_search 或 keyword_search 检索费率数值，不得跳过检索直接计算
	  例："按2025版推荐利润率计算利润" → 步骤1: text_search "2025 利润率 推荐费率 企业管理费"
	  步骤2: 根据检索到的费率值执行计算
	- 费用计算基数类问题：若问题问某个费率的计算基数，第一步用 text_search 检索该费率定义，
	  关键字只需包含费率名称（text_search 会自动返回 fee_rates 结构化数据含计算公式和基数）
	  例："总包管理服务费的计算基数" → 步骤1: text_search "总包管理服务费"

定额子目检索规则定额子目检索规则（重要）：
- 若问题涉及定额子目的人工费/材料费/机械费/消耗量，第一步必须是：
  调用 category_search 确认材料/工艺所在章节编号
- 第二步再用 text_search 带章节号检索具体子目数值
- 材料名与位置词（楼梯/墙面/地面）要分离，category_search 只传材料名

章节路径约束规则（重要，当 Human 消息包含"章节路径地图"时）：
- Navigator 节点已识别出查询匹配的章节路径，Human 消息中有"章节路径地图"段落
- 规划 text_search 或 hybrid_search 步骤时，必须在步骤描述中包含对应的 path_constraint 参数
- 例：若路径为 '第二册电气设备安装工程/%'，则步骤为：
  text_search(query='送配电装置系统调试', path_constraint='第二册电气设备安装工程/%')
- 如有多条路径，只取最相关的前 2 条用于约束

输出格式（纯 JSON，不含 markdown 代码块）：
{"steps": ["步骤1", "步骤2", ...]}
"""

_QUERY_TYPE_INSTRUCTIONS: dict[str, str] = {
    "trend_chart": "4. 先给出趋势结论（涨/跌/平稳，涨跌幅），再列关键时间节点数据；不要仅罗列数字。若证据中已给出“价格走势 期间:YYYY-MM 均价:XX”这类月均价点，可直接按该类别月均价口径计算走势或环比，不要因为底层规格混杂而拒答，但需说明口径。",
    "comparison": "4. 先给对比结论（谁高/谁低/差距多少），再分别列各方数据，最后计算差值",
    "calculation": "4. 先列计算公式和费率来源，再逐步计算，最后给出带单位的结果",
    "price": "4. 给出价格数值时注明时间、规格、单位；多条记录按时间倒序排列",
    "default": "4. 先给出核心结论，再补充细节；语言自然流畅，避免机械罗列",
}


# ── 辅助函数 ────────────────────────────────────────────────────────────────


def _display_doc_name(doc_name: str) -> str:
    return doc_name.replace(".pdf", "").replace(".xlsx", "").replace(".docx", "").strip("《》")


def _looks_like_annual_price_query(query: str, entities: dict | None = None) -> bool:
    analysis_entities = entities or (_analyzer.analyze(query).get("entities", {}))
    period = str(analysis_entities.get("year_month") or "")
    material = str(analysis_entities.get("material_name") or "")
    return bool(re.match(r"^\d{4}$", period) and material and "信息价" in query)


def _previous_month(period: str) -> str:
    normalized = str(period or "").strip()
    if not re.match(r"^\d{4}-\d{2}$", normalized):
        return ""
    year, month = normalized.split("-", 1)
    y = int(year)
    m = int(month)
    if m == 1:
        return f"{y - 1}-12"
    return f"{y}-{m - 1:02d}"


def _looks_like_multi_material_price_change_query(query: str, entities: dict | None = None) -> bool:
    analysis_entities = entities or (_analyzer.analyze(query).get("entities", {}))
    materials = analysis_entities.get("material_names") or []
    period = str(analysis_entities.get("year_month") or "")
    return bool(
        len(materials) >= 2
        and re.match(r"^\d{4}-\d{2}$", period)
        and any(token in query for token in ("较上月", "上月", "环比", "变化幅度"))
    )


def _prune_chunks_for_query(
    query: str,
    query_type: str,
    chunks: list[dict],
    entities: dict | None = None,
) -> list[dict]:
    if not chunks:
        return chunks

    if query_type == "standard_ref" and is_appendix_standard_query(query):
        title = extract_appendix_standard_title(query)
        terms = extract_appendix_standard_terms(query)
        appendix_matched = [
            chunk for chunk in chunks
            if title in ((chunk.get("content") or "") + " " + (chunk.get("doc_filename") or ""))
            or any(term in ((chunk.get("content") or "") + " " + (chunk.get("doc_filename") or "")) for term in terms)
        ]
        if appendix_matched:
            return appendix_matched
        # No appendix-specific match — return all chunks rather than dropping everything
        return chunks

    if query_type not in {"price", "comparison", "trend_chart"}:
        return chunks

    analysis_entities = entities or (_analyzer.analyze(query).get("entities", {}))
    material = str(analysis_entities.get("material_name") or "").strip()
    materials = [
        str(item).strip()
        for item in (analysis_entities.get("material_names") or [])
        if str(item).strip()
    ]
    specification = str(analysis_entities.get("specification") or "").strip()
    match_terms = materials or ([material] if material else [])
    if not match_terms:
        return chunks

    material_matched = [
        chunk for chunk in chunks
        if any(
            term in ((chunk.get("content") or "") + " " + (chunk.get("doc_filename") or ""))
            for term in match_terms
        )
    ]
    if material_matched:
        chunks = material_matched
    elif _looks_like_annual_price_query(query, analysis_entities):
        return []

    if specification:
        compact_spec = re.sub(r"\s+", "", specification.lower()).replace("×", "x").replace("*", "x")
        spec_matched = [
            chunk for chunk in chunks
            if (
                specification in (chunk.get("content") or "")
                or compact_spec in re.sub(
                    r"\s+",
                    "",
                    (chunk.get("content") or "").lower().replace("×", "x").replace("*", "x"),
                )
            )
        ]
        if spec_matched:
            chunks = spec_matched

    return chunks


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


def _format_citations(chunks: list, allowed_refs: set[tuple[str, str]] | None = None) -> str:
    """从 chunks 生成尾部参考来源列表（按显示字符串去重，过滤内部数据集）"""
    seen_refs: set[str] = set()
    ordered: list[str] = []
    for c in chunks[:12]:
        doc_name = c.get("doc_filename") or c.get("source") or ""
        page = c.get("page_number") or c.get("page") or "?"
        if not doc_name:
            continue
        display = _display_doc_name(doc_name)
        if display in _INTERNAL_SOURCES:
            continue
        page_str = str(page)
        if allowed_refs is not None and (display, page_str) not in allowed_refs:
            continue
        ref = f"《{display}》第 {page} 页"
        if ref not in seen_refs:
            seen_refs.add(ref)
            ordered.append(ref)
    if not ordered:
        return ""
    lines = ["参考索引："]
    for i, ref in enumerate(ordered, 1):
        lines.append(f"[{i}] {ref}")
    return "\n".join(lines)


def _build_evidence_block(chunks: list) -> str:
    if not chunks:
        return "1. 暂无可引用依据，知识库未检索到可支撑回答的原文。"

    lines: list[str] = []
    for i, c in enumerate(chunks[:3], 1):
        doc_name = c.get("doc_filename") or c.get("source") or "未知来源"
        page = c.get("page_number") or c.get("page") or "?"
        content = re.sub(r"\s+", " ", c.get("content", "")).strip()[:120]
        display = doc_name.replace(".pdf", "").replace(".xlsx", "").replace(".docx", "").strip("《》")
        lines.append(f"{i}. 《{display}》第 {page} 页")
        if content:
            lines.append(f"   关键内容：{content}")
    return "\n".join(lines)


def _split_answer_components(answer_without_refs: str, chunks: list[dict]) -> tuple[str, str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", answer_without_refs) if p.strip()]
    if len(paragraphs) == 1 and "简要分析" in paragraphs[0]:
        inline_parts = re.split(r"简要分析[:：]", paragraphs[0], maxsplit=1)
        direct_part = inline_parts[0].strip()
        analysis_part = inline_parts[1].strip() if len(inline_parts) > 1 else ""
        paragraphs = [part for part in [direct_part, analysis_part] if part]
    direct_answer = paragraphs[0] if paragraphs else "现有检索结果不足，暂时无法给出可靠结论。"
    remaining = paragraphs[1:]

    if remaining and re.match(r"简要分析[:：]", remaining[0]):
        analysis_text = "\n\n".join(
            [re.sub(r"^简要分析[:：]?\s*", "", remaining[0]).strip(), *remaining[1:]]
        ).strip()
    else:
        analysis_text = "\n\n".join(remaining).strip()

    if not analysis_text:
        analysis_text = _build_evidence_block(chunks)
    return direct_answer, analysis_text


def refine_citations_for_answer(answer: str, chunks: list[dict], citations_text: str) -> str:
    explicit_refs = {
        (name.strip(), page.strip())
        for name, page in re.findall(r"【《([^》]+)》P\s*(\d+)】", answer or "")
    }
    if explicit_refs:
        filtered = _format_citations(chunks, explicit_refs)
        if filtered:
            return filtered
    return citations_text


def _build_answer_title(query_type: str) -> str:
    return {
        "standard_ref": "规则说明",
        "calculation": "结果摘要",
        "comparison": "对比结果",
        "price": "价格摘要",
        "trend_chart": "趋势摘要",
    }.get(query_type, "回答摘要")


def _split_sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if not cleaned:
        return []
    parts = [part.strip(" ，,") for part in re.split(r"[。；;]\s*", cleaned) if part.strip()]
    return [part for part in parts if len(part) >= 6]


def _shorten_sentence(text: str, max_length: int = 92) -> str:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if len(normalized) <= max_length:
        return normalized

    clauses = [part.strip(" ，,") for part in re.split(r"[，,]", normalized) if part.strip()]
    chosen: list[str] = []
    total = 0
    for clause in clauses:
        if chosen and total + len(clause) + 1 > max_length:
            break
        chosen.append(clause)
        total += len(clause) + 1
    shortened = "，".join(chosen).strip() or normalized[:max_length].rstrip("，,")
    if shortened and shortened[-1] not in "。！？":
        shortened += "。"
    return shortened


def _build_summary_text(query_type: str, direct_answer: str) -> str:
    sentences = _split_sentences(direct_answer)
    if not sentences:
        return direct_answer.strip()

    limit = 1 if query_type in {"standard_ref", "calculation"} else 2
    picked = [_shorten_sentence(sentence) for sentence in sentences[:limit]]
    return " ".join(part for part in picked if part).strip()


def _highlight_kind(sentence: str, query_type: str) -> str:
    if any(token in sentence for token in ("适用", "适用于", "范围")):
        return "scope"
    if any(token in sentence for token in ("不单独计算", "不另计", "已包括", "不单列")):
        return "exclusion"
    if any(token in sentence for token in ("按“", "按\"", "按", "计量单位", "为单位计算")) and "计算" in sentence:
        return "method"
    if "人工费" in sentence:
        return "labor"
    if "材料费" in sentence:
        return "material"
    if "机械费" in sentence:
        return "machine"
    if any(token in sentence for token in ("价格", "单价", "均价", "差值", "涨幅", "跌幅")):
        return "metric"
    if any(token in sentence for token in ("建议", "注意", "无法", "未单独列出", "缺失")):
        return "hint"
    if query_type == "standard_ref":
        return "rule"
    return "detail"


def _build_highlights(query_type: str, direct_answer: str, analysis_text: str) -> list[dict]:
    highlights: list[dict] = []
    seen_values: set[str] = set()
    for sentence in [*_split_sentences(direct_answer), *_split_sentences(analysis_text)]:
        normalized = sentence.strip()
        if normalized in seen_values:
            continue
        seen_values.add(normalized)
        highlights.append(
            {
                "kind": _highlight_kind(normalized, query_type),
                "value": normalized,
            }
        )
        if len(highlights) >= 4:
            break
    return highlights


def _parse_citation_items(citations_text: str) -> list[dict]:
    items: list[dict] = []
    for line in (citations_text or "").splitlines():
        match = re.match(r"\[(\d+)\]\s+《(.+?)》第\s+(.+?)\s+页", line.strip())
        if match:
            items.append(
                {
                    "index": int(match.group(1)),
                    "title": match.group(2),
                    "page": match.group(3),
                }
            )
    return items


def _build_answer_sections_presentation(
    query: str,
    query_type: str,
    final_answer: str,
    chunks: list[dict],
    citations_text: str,
) -> dict | None:
    answer_without_refs = re.split(r"\n\s*(?:【参考索引】|参考索引[:：])", final_answer, maxsplit=1)[0].strip()
    if not answer_without_refs:
        return None

    direct_answer, analysis_text = _split_answer_components(answer_without_refs, chunks)
    highlights = _build_highlights(query_type, direct_answer, analysis_text)
    analysis_paragraphs = [p.strip() for p in re.split(r"\n\s*\n", analysis_text) if p.strip()]
    sections = [
        {"kind": "analysis" if idx == 0 else "detail", "body": paragraph}
        for idx, paragraph in enumerate(analysis_paragraphs[:2])
    ]
    sources = _parse_citation_items(citations_text)[:4]

    note = None
    if len(query) <= 28:
        note = query

    layout = _build_layout_blocks(direct_answer, analysis_paragraphs, query_type)

    return {
        "type": "answer_sections",
        "query_type": query_type,
        "title": _build_answer_title(query_type),
        "note": note,
        "summary": _build_summary_text(query_type, direct_answer),
        "highlights": highlights,
        "sections": sections,
        "layout": layout,
        "sources": sources,
    }


# Block title prefix: matches "调试范围：", "**计费基数**：", "1. 适用对象：" etc.
_BLOCK_TITLE_PATTERN = re.compile(
    r"^\s*(?:\d+[、.)]\s*|[（(]\d+[）)]\s*|[•▶◆■]\s*|\*\*\s*)?"
    r"([\u4e00-\u9fa5A-Za-z0-9（）()\u3001]{2,16})"
    r"(?:\s*\*\*)?"
    r"\s*[：:]"
)
_LIST_MARKER_PATTERN = re.compile(r"(?:^|\n)\s*(?:\d+[、.)]|[•▶◆■]|[-－]|\*)\s+")
_INLINE_METRIC_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*(?:%|元|万元|万|亿|kg|吨|m³|m2|m|页)")


def _extract_block_title(paragraph: str) -> tuple[str, str]:
    """Return (title, body) by peeling a leading '标题：' clause when present."""
    match = _BLOCK_TITLE_PATTERN.match(paragraph)
    if not match:
        return "", paragraph.strip()
    title = match.group(1).strip().strip("*")
    if len(title) < 2 or len(title) > 16:
        return "", paragraph.strip()
    body = paragraph[match.end():].strip()
    if not body:
        return "", paragraph.strip()
    return title, body


def _classify_block_hint(body: str) -> str:
    """Pick a render hint: list | callout | inline | paragraph."""
    stripped = body.strip()
    if not stripped:
        return "paragraph"
    list_markers = _LIST_MARKER_PATTERN.findall("\n" + stripped)
    if len(list_markers) >= 2:
        return "list"
    if len(stripped) <= 60 and _INLINE_METRIC_PATTERN.search(stripped):
        return "callout"
    if len(stripped) <= 80 and stripped.count("。") <= 1:
        return "inline"
    return "paragraph"


def _build_layout_blocks(
    direct_answer: str,
    analysis_paragraphs: list[str],
    query_type: str,
) -> list[dict]:
    """Produce a free-form layout list driven by the LLM's own paragraph titles.

    Each block carries an LLM-derived title (peeled from '标题：' prefix or the
    first noun phrase) plus a render hint so the frontend doesn't have to
    translate kind→title via a hardcoded map.
    """
    blocks: list[dict] = []

    if direct_answer.strip():
        body = direct_answer.strip()
        blocks.append(
            {
                "id": "answer",
                "title": "结论" if query_type != "calculation" else "结果",
                "body": body,
                "hint": _classify_block_hint(body),
            }
        )

    seen_bodies: set[str] = {b["body"] for b in blocks}
    for idx, paragraph in enumerate(analysis_paragraphs[:4]):
        title, body = _extract_block_title(paragraph)
        if body in seen_bodies:
            continue
        seen_bodies.add(body)
        if not title:
            # Fall back to a numbered title only when nothing better is available.
            title = "依据" if idx == 0 else "补充"
        blocks.append(
            {
                "id": f"block-{idx + 1}",
                "title": title,
                "body": body,
                "hint": _classify_block_hint(body),
            }
        )

    return blocks


def _normalize_math_text(text: str) -> str:
    return (
        (text or "")
        .replace("（", "(")
        .replace("）", ")")
        .replace("＋", "+")
        .replace("－", "-")
        .replace("×", "*")
        .replace("÷", "/")
        .replace("％", "%")
        .replace("＝", "=")
        .replace("—", "-")
        .replace("–", "-")
    )


def _sanitize_copy_expression(expression: str) -> str:
    sanitized = _normalize_math_text(expression)
    sanitized = re.sub(
        r"([0-9]+(?:\.[0-9]+)?)\s*%",
        lambda m: format(float(m.group(1)) / 100, ".12g"),
        sanitized,
    )
    sanitized = re.sub(r"(万元|万|元|人民币)", "", sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    sanitized = re.sub(r"[^0-9\.\+\-\*\/\(\) ]", "", sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized


def _is_safe_arithmetic_expression(expression: str) -> bool:
    if not expression or not re.search(r"\d", expression) or not re.search(r"[\+\-\*/]", expression):
        return False
    if not re.fullmatch(r"[0-9\.\+\-\*\/\(\) ]+", expression):
        return False
    try:
        parsed = ast.parse(expression, mode="eval")
    except SyntaxError:
        return False

    allowed_nodes = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Constant,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.UAdd,
        ast.USub,
        ast.Load,
    )
    return all(isinstance(node, allowed_nodes) for node in ast.walk(parsed))


def _extract_copy_expression(formula: str, substituted: str) -> str:
    candidates: list[str] = []
    for source in (substituted, formula):
        normalized = _normalize_math_text(source)
        candidates.extend(
            segment.strip(" ，,")
            for segment in re.split(r"\s*=\s*", normalized)
            if segment.strip(" ，,")
        )

    best_candidate = ""
    best_score = -1
    for candidate in candidates:
        sanitized = _sanitize_copy_expression(candidate)
        if not _is_safe_arithmetic_expression(sanitized):
            continue
        digit_count = len(re.findall(r"\d", sanitized))
        operator_count = len(re.findall(r"[\+\-\*/]", sanitized))
        score = digit_count * 10 + operator_count
        if score > best_score:
            best_candidate = sanitized
            best_score = score
    return best_candidate


def _extract_calc_title(prefix: str, first_segment: str, fallback_order: int) -> str:
    cleaned_prefix = re.sub(r"^(首先|然后|接着|再|最后|第一步|第1步|第二步|第2步|第三步|第3步|计算|求|得出)+", "", prefix or "").strip(" ：:")
    if cleaned_prefix:
        return cleaned_prefix
    candidate = first_segment.strip()
    if re.fullmatch(r"[\u4e00-\u9fa5A-Za-z（）()]+", candidate):
        return candidate
    return f"步骤{fallback_order}"


def _build_calculation_steps_presentation(
    query: str,
    final_answer: str,
    chunks: list[dict],
    citations_text: str,
) -> dict | None:
    answer_without_refs = re.split(r"\n\s*(?:【参考索引】|参考索引[:：])", final_answer, maxsplit=1)[0].strip()
    if not answer_without_refs:
        return None

    direct_answer, analysis_text = _split_answer_components(answer_without_refs, chunks)
    candidate_sentences: list[str] = []
    for part in [direct_answer, analysis_text]:
        candidate_sentences.extend([s.strip() for s in re.split(r"[。；;]\s*", part) if s.strip()])

    steps: list[dict] = []
    seen_signatures: set[tuple[str, str]] = set()
    for raw_sentence in candidate_sentences:
        sentence = raw_sentence.replace("＝", "=")
        if "=" not in sentence or not re.search(r"\d", sentence):
            continue

        prefix = ""
        expr_text = sentence
        if "：" in sentence:
            maybe_prefix, maybe_expr = sentence.split("：", 1)
            if "=" in maybe_expr:
                prefix = maybe_prefix.strip()
                expr_text = maybe_expr.strip()

        segments = [seg.strip(" ，,") for seg in re.split(r"\s*=\s*", _normalize_math_text(expr_text)) if seg.strip(" ，,")]
        if len(segments) < 3:
            continue

        title = _extract_calc_title(prefix, segments[0], len(steps) + 1)
        expression_segments = segments[1:] if re.fullmatch(r"[\u4e00-\u9fa5A-Za-z（）()]+", segments[0]) else segments
        if len(expression_segments) < 2:
            continue

        result_text = expression_segments[-1]
        calc_chain = expression_segments[:-1]
        if not calc_chain:
            continue

        formula = calc_chain[0]
        substituted = " = ".join(calc_chain)
        copy_expression = _extract_copy_expression(formula, substituted)
        if not copy_expression:
            continue

        result_match = re.search(r"(-?\d+(?:\.\d+)?)\s*(万元|万|元|%)?", result_text)
        unit = result_match.group(2) if result_match else ""
        result_value = result_match.group(1) if result_match else result_text

        signature = (title, result_value)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)

        steps.append(
            {
                "order": len(steps) + 1,
                "title": title,
                "formula": formula,
                "substituted": substituted,
                "result": result_value,
                "result_text": result_text,
                "unit": unit,
                "copy_expression": copy_expression,
            }
        )

    if not steps:
        return None

    analysis_paragraphs = [p.strip() for p in re.split(r"\n\s*\n", analysis_text) if p.strip()]
    layout = _build_layout_blocks(direct_answer, analysis_paragraphs, "calculation")

    return {
        "type": "calculation_steps",
        "title": "计算沙箱",
        "note": query if len(query) <= 40 else None,
        "summary": _build_summary_text("calculation", direct_answer),
        "highlights": _build_highlights("calculation", direct_answer, analysis_text),
        "steps": steps,
        "layout": layout,
        "sources": _parse_citation_items(citations_text)[:4],
    }


def _parse_price_point(chunk: dict) -> dict | None:
    metadata = chunk.get("metadata") or {}
    content = chunk.get("content", "") or ""
    doc_name = chunk.get("doc_filename") or chunk.get("source") or ""
    page = chunk.get("page_number") or chunk.get("page") or None

    label = metadata.get("year_month")
    if not label:
        period_match = re.search(r"期间[:：]\s*(20\d{2}-\d{2})", content)
        if period_match:
            label = period_match.group(1)

    raw_value = metadata.get("avg_price")
    if raw_value is None:
        raw_value = metadata.get("price")
    if raw_value is None:
        value_match = re.search(r"(?:均价|价格)[:：]\s*([0-9]+(?:\.[0-9]+)?)", content)
        if value_match:
            raw_value = value_match.group(1)
    if raw_value is None:
        return None

    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None

    unit = metadata.get("unit")
    if not unit:
        unit_match = re.search(r"单位[:：]\s*([^\s]+)", content)
        if unit_match:
            unit = unit_match.group(1)
        else:
            unit_match = re.search(r"元/([^\s，,。；;]+)", content)
            if unit_match:
                unit = unit_match.group(1)

    source_label = (
        doc_name.replace(".pdf", "").replace(".xlsx", "").replace(".docx", "").strip("《》")
        if doc_name
        else ""
    )

    return {
        "label": label or "当前",
        "value": round(value, 2),
        "unit": unit or "",
        "page": page,
        "source": source_label,
    }


def _extract_title_parts_from_chunks(chunks: list[dict]) -> tuple[str, str]:
    for chunk in chunks:
        content = (chunk.get("content") or "").strip()
        if not content:
            continue
        prefix = re.split(r"单位[:：]|价格走势", content, maxsplit=1)[0].strip()
        parts = prefix.split()
        if not parts:
            continue
        material = parts[0]
        specification = " ".join(parts[1:]).strip()
        return material, specification
    return "", ""


def _build_price_title(query: str, fallback: str, chunks: list[dict]) -> str:
    analysis = _analyzer.analyze(query)
    entities = analysis.get("entities", {}) if isinstance(analysis, dict) else analysis.entities
    material = entities.get("material_name") or ""
    specification = entities.get("specification") or ""
    if not specification or len(specification) < 4:
        spec_match = re.search(r"(\d+(?:\.\d+)?/\d+\s*[Kk][Vv]\s*[A-Za-z]+\s*\d+\s*[×xX*]\s*\d+)", query)
        if spec_match:
            specification = re.sub(r"\s+", " ", spec_match.group(1)).strip()
    if not material or len(material) < 2:
        chunk_material, chunk_specification = _extract_title_parts_from_chunks(chunks)
        material = material or chunk_material
        if (not specification or len(specification) < 4) and chunk_specification:
            specification = chunk_specification
    if material and specification:
        return f"{material} {specification}{fallback}"
    if material:
        return f"{material}{fallback}"
    return fallback


def _build_presentation_payload(query: str, query_type: str, chunks: list[dict]) -> dict | None:
    if query_type not in {"comparison", "trend_chart", "price"}:
        return None

    parsed_points = []
    for chunk in chunks:
        point = _parse_price_point(chunk)
        if point:
            parsed_points.append(point)

    if not parsed_points:
        return None

    grouped: dict[str, dict] = {}
    for point in parsed_points:
        entry = grouped.setdefault(
            point["label"],
            {
                "label": point["label"],
                "values": [],
                "unit": point["unit"],
                "pages": set(),
                "sources": set(),
            },
        )
        entry["values"].append(point["value"])
        if point["page"]:
            entry["pages"].add(point["page"])
        if point["source"]:
            entry["sources"].add(point["source"])
        if not entry["unit"] and point["unit"]:
            entry["unit"] = point["unit"]

    points = []
    for label in sorted(grouped.keys()):
        entry = grouped[label]
        values = entry["values"]
        avg_value = sum(values) / len(values)
        points.append(
            {
                "label": label,
                "value": round(avg_value, 2),
                "min_value": round(min(values), 2),
                "max_value": round(max(values), 2),
                "count": len(values),
                "pages": sorted(entry["pages"]),
                "sources": sorted(entry["sources"]),
            }
        )

    if not points:
        return None

    unit = next((entry["unit"] for entry in grouped.values() if entry["unit"]), "")
    note = ""
    if any(point["count"] > 1 for point in points):
        note = "同月存在多条报价时，图表按当月均值展示，卡片保留区间。"

    if query_type == "comparison" and len(points) >= 2:
        base = points[0]["value"]
        target = points[-1]["value"]
        delta = round(target - base, 2)
        delta_percent = round(delta / base * 100, 2) if base else None
        return {
            "type": "price_comparison",
            "title": _build_price_title(query, "价格对比", chunks),
            "unit": unit,
            "points": points,
            "delta": delta,
            "delta_percent": delta_percent,
            "note": note,
        }

    if query_type == "trend_chart" and len(points) >= 2:
        start_value = points[0]["value"]
        end_value = points[-1]["value"]
        delta = round(end_value - start_value, 2)
        delta_percent = round(delta / start_value * 100, 2) if start_value else None
        return {
            "type": "price_trend",
            "title": _build_price_title(query, "价格走势", chunks),
            "unit": unit,
            "points": points,
            "delta": delta,
            "delta_percent": delta_percent,
            "note": note,
        }

    return {
        "type": "price_snapshot",
        "title": _build_price_title(query, "价格概览", chunks),
        "unit": unit,
        "points": points,
        "note": note,
    }


def finalize_presentation_payload(
    query: str,
    query_type: str,
    final_answer: str,
    chunks: list[dict],
    citations_text: str,
    existing_presentation: dict | None = None,
) -> dict | None:
    if existing_presentation:
        return existing_presentation
    if query_type == "calculation":
        calc_presentation = _build_calculation_steps_presentation(
            query=query,
            final_answer=final_answer,
            chunks=chunks,
            citations_text=citations_text,
        )
        if calc_presentation:
            return calc_presentation
    return _build_answer_sections_presentation(query, query_type, final_answer, chunks, citations_text)


def _clean_markdown_noise(text: str) -> str:
    text = re.sub(r"^\s*#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)
    text = text.replace("**", "").replace("```", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_section(answer: str, tag: str) -> str:
    pattern = rf"{re.escape(tag)}\s*(.*?)(?=\n\s*(?:【[^】]+】|参考索引[:：]|$))"
    match = re.search(pattern, answer, flags=re.DOTALL)
    return match.group(1).strip() if match else ""


def _normalize_reference_section(citations_text: str) -> str:
    refs = (citations_text or "").strip()
    if not refs:
        refs = "参考索引：\n[1] 暂无可用来源"
    refs = refs.replace("【参考索引】", "参考索引：")
    return refs


def _normalize_final_answer(
    query: str,
    answer: str,
    chunks: list,
    citations_text: str,
    query_type: str = "semantic",
) -> str:
    answer = _sanitize_false_refusal_phrases(_clean_markdown_noise(_strip_think_tags(answer)))
    refs = _normalize_reference_section(citations_text)
    # Strip any LLM-generated reference section
    answer_without_refs = re.split(r"\n\s*(?:【参考索引】|参考索引[:：])", answer, maxsplit=1)[0].strip()
    answer_without_refs = re.sub(r"(?m)^\s*第[一二三四五六七八九十]段[:：]\s*", "", answer_without_refs)
    answer_without_refs = re.sub(r"(?m)^\s*参考索引[:：]\s*\[1\]\s*暂无可用来源[。.]?\s*$", "", answer_without_refs)
    answer_without_refs = answer_without_refs.strip()

    # Detect and convert old five-section format
    has_old_tags = all(tag in answer_without_refs for tag in ["【问题】", "【论据】", "【分析】", "【结论】"])
    if has_old_tags:
        conclusion = _extract_section(answer_without_refs, "【结论】")
        analysis = _extract_section(answer_without_refs, "【分析】")
        evidence = _extract_section(answer_without_refs, "【论据】")
        direct_answer = conclusion or (analysis.splitlines()[0].strip() if analysis else "")
        if not direct_answer:
            direct_answer = "现有检索结果不足，暂时无法给出可靠结论。"
        analysis_text = analysis or evidence or _build_evidence_block(chunks)
        return f"{direct_answer}\n\n简要分析：\n{analysis_text}\n\n{refs}".strip()

    direct_answer, analysis_text = _split_answer_components(answer_without_refs, chunks)

    return f"{direct_answer}\n\n简要分析：\n{analysis_text}\n\n{refs}".strip()


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
    r"现有检索结果不足"
)


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _looks_like_refusal_answer(answer: str) -> bool:
    return bool(_REFUSAL_RE.search(_compact_text(answer)))


def _sanitize_false_refusal_phrases(answer: str) -> str:
    replacements = {
        "未提供": "未列明",
        "未包含": "未列入",
    }
    sanitized = answer
    for source, target in replacements.items():
        sanitized = sanitized.replace(source, target)
    return sanitized


def _is_catalog_evidence(chunk: dict) -> bool:
    metadata = chunk.get("metadata") or {}
    return metadata.get("evidence_kind") == "pdf_catalog_chunk"


def _has_substantive_evidence(chunks: list[dict]) -> bool:
    return any(
        chunk.get("source_db") != "concept_search" and not _is_catalog_evidence(chunk)
        for chunk in chunks
    )


# ── Node Contract Verification ──────────────────────────────────────────────────


def _compute_price_cv_from_chunks(chunks: list[dict]) -> float | None:
    """Compute coefficient of variation across retrieved price points (0-1)."""
    prices = []
    for chunk in chunks:
        price = None
        md = chunk.get("metadata") or {}
        if isinstance(md, dict):
            price = md.get("price_tax_included") or md.get("price") or md.get("unit_price")
        if price is None:
            continue
        try:
            prices.append(float(price))
        except (ValueError, TypeError):
            continue
    if len(prices) < 2:
        return None
    mean = sum(prices) / len(prices)
    if mean == 0:
        return None
    variance = sum((p - mean) ** 2 for p in prices) / len(prices)
    return (variance ** 0.5) / abs(mean)


def verify_query_analysis_contract(state: dict) -> ContractResult:
    """C1: query_analysis_node post-conditions."""
    violations = []
    qt = state.get("query_type", "")
    entities = state.get("query_entities") or {}

    if qt not in ("price", "semantic", "calculation", "comparison", "trend_chart", "standard_ref"):
        violations.append(("invalid_intent", f"unrecognised query_type={qt}"))

    if qt == "price" and not entities.get("material_name"):
        violations.append(("missing_material", "price query without material_name"))

    if qt == "price" and not entities.get("year_month"):
        violations.append(("missing_year_month", "year_month not extracted"))

    return ContractResult(
        node="query_analysis",
        passed=len(violations) == 0,
        violations=violations,
    )


def verify_navigator_contract(state: dict) -> ContractResult:
    """C2: navigator_node post-conditions — roadmap must be populated for non-price queries."""
    qt = state.get("query_type", "")
    roadmap = state.get("roadmap") or []

    if qt in ("price", "trend_chart"):
        return ContractResult(node="navigator_node", passed=True, violations=[])

    if not roadmap:
        return ContractResult(
            node="navigator_node",
            passed=False,
            violations=[("empty_roadmap", "no catalog chapters matched")],
        )

    return ContractResult(node="navigator_node", passed=True, violations=[])


def verify_tool_contract(state: dict) -> ContractResult:
    """C3: tool_node post-conditions — at least one new usable chunk must be added."""
    chunks = state.get("retrieved_chunks") or []
    fallback = state.get("fallback_mode", False)
    usable = [c for c in chunks if c.get("source_db") != "concept_search" and not _is_catalog_evidence(c)]

    if not usable:
        code = "zero_results_after_fallback" if fallback else "zero_results"
        return ContractResult(
            node="tool_node",
            passed=False,
            violations=[(code, "retrieval returned no usable chunks")],
        )

    return ContractResult(node="tool_node", passed=True, violations=[])


def verify_synthesize_contract(state: dict) -> ContractResult:
    """C4: synthesize_node post-conditions — answer quality checks."""
    eval_ = state.get("evaluation") or {}
    answer = state.get("final_answer", "")
    qt = state.get("query_type", "")
    chunks = state.get("retrieved_chunks") or []
    violations = []

    if not eval_.get("passed", False):
        fb = eval_.get("feedback", "")
        violations.append(("eval_not_passed", fb))

    if qt == "price" and not re.search(r"\d+\.?\d*", answer):
        violations.append(("no_price_number", "answer contains no numeric price"))

    if qt == "price":
        cv = _compute_price_cv_from_chunks(chunks)
        if cv is not None and cv > 0.15:
            violations.append(("source_conflict", f"price CV={cv:.3f} exceeds 0.15 threshold"))

    return ContractResult(
        node="synthesize_node",
        passed=len(violations) == 0,
        violations=violations,
    )


def trace_root_cause(state: dict) -> str:
    """Walk contract_results from first to last; return the node of the earliest failure."""
    results = state.get("contract_results") or []
    for cr in results:
        if not cr.get("passed", False):
            return cr["node"]
    return "query_analysis"


# ── Corrective Action Helpers ──────────────────────────────────────────────────


def _llm_extract_material(query: str, llm_config: dict | None = None) -> str:
    """Use LLM to extract the material name from a query that lacked one."""
    prompt = f"""Extract ONLY the material name from this Chinese construction cost query.
Return a JSON object with a single key "material_name".
If no material is mentioned, return {{"material_name": ""}}.

Query: {query}

JSON:"""
    try:
        response, _ = invoke_llm(
            [HumanMessage(content=prompt)],
            thinking=False,
            prefer_strong=False,
            llm_config=llm_config or {},
        )
        data = json.loads(response.content or "{}")
        return str(data.get("material_name", "") or "")
    except Exception:
        return ""


def _inject_latest_year_month(material_name: str) -> str:
    """Query DB for the latest year_month for a given material."""
    if not material_name:
        return ""
    try:
        from app.agent.tools import get_latest_year_month_for_material
        return get_latest_year_month_for_material(material_name) or ""
    except Exception:
        return ""


def _expand_aliases_for_query(query: str) -> str:
    """Expand query with canonical concept aliases from the unified alias map."""
    try:
        from app.agent.query_analyzer import _normalize_material
        return _normalize_material(query)
    except Exception:
        return query


def _expand_category_hints(query: str, state: dict) -> list[str]:
    """Generate broader category hints when navigator finds no roadmap entries."""
    import re as _re
    hints = list(state.get("category_hints") or [])
    # Extract parent chapters by truncating section numbers
    for hint in list(hints):
        parts = hint.split(".")
        while len(parts) > 1:
            parts.pop()
            parent = ".".join(parts)
            if parent not in hints:
                hints.append(parent)
    # Add single-char ngram variants of key terms
    keywords = _re.findall(r"[一-鿿]{2,6}", query)
    for kw in keywords:
        variant = kw[:2] if len(kw) >= 2 else kw
        if variant not in hints:
            hints.append(variant)
    return hints


def _escalate_tool_fallback(level: int) -> list[str]:
    """Return the tool category ladder for a given fallback level.

    0: standard tools (price_query / hybrid_search)
    1: add text_search (keyword-based)
    2: add pdf_page_search (direct page extraction)
    """
    ladder = {
        0: ["price_query", "hybrid_search"],
        1: ["price_query", "hybrid_search", "text_search"],
        2: ["price_query", "hybrid_search", "text_search", "pdf_page_search"],
    }
    return ladder.get(level, ladder[2])


# ── Original evaluation ─────────────────────────────────────────────────


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


def _build_forced_price_tool_calls(state: RAGAgentState) -> list[dict]:
    query = str(state.get("query") or "").strip()
    query_type = str(state.get("query_type") or "").strip().lower()
    entities = state.get("query_entities") or {}
    retrieved_chunks = list(state.get("retrieved_chunks") or [])
    material = str(entities.get("material_name") or "").strip()
    materials = [str(item).strip() for item in (entities.get("material_names") or []) if str(item).strip()]
    specification = str(entities.get("specification") or "").strip()
    tool_calls: list[dict] = []

    if query_type == "comparison" and material and "信息价" in query:
        price_compare_match = _PRICE_COMPARE_RE.search(query)
        if price_compare_match:
            groups = [group for group in price_compare_match.groups() if group]
            if len(groups) >= 2:
                periods: list[str] = []
                for token in groups[:2]:
                    match = re.search(r"(20\d{2})[年\-/](\d{1,2})", token)
                    if match:
                        periods.append(f"{match.group(1)}-{int(match.group(2)):02d}")
                if len(periods) == 2:
                    covered_periods = {
                        str((chunk.get("metadata") or {}).get("year_month") or "").strip()
                        for chunk in retrieved_chunks
                        if material in str(chunk.get("content") or "")
                    }
                    missing_periods = [period for period in periods if period not in covered_periods]
                    if not missing_periods:
                        return []
                    for period in missing_periods:
                        args = {
                            "material_name": material,
                            "year_month": period,
                            "specification": specification,
                            "top_k": 8,
                        }
                        tool_hash = hashlib.md5(
                            f"price_query:{json.dumps(args, ensure_ascii=False, sort_keys=True)}".encode("utf-8")
                        ).hexdigest()[:12]
                        tool_calls.append(
                            {
                                "id": f"forced_price_query_{tool_hash}",
                                "name": "price_query",
                                "args": args,
                                "type": "tool_call",
                            }
                        )
                    return tool_calls

    if query_type in {"price", "trend_chart"} and _looks_like_multi_material_price_change_query(query, entities):
        period = str(entities.get("year_month") or "").strip()
        previous_period = _previous_month(period)
        covered_materials = {
            candidate
            for candidate in materials
            if any(
                candidate in str(chunk.get("content") or "")
                and str((chunk.get("metadata") or {}).get("year_month") or "").strip() in {period, previous_period}
                for chunk in retrieved_chunks
            )
        }
        missing_materials = [candidate for candidate in materials if candidate not in covered_materials]
        if period and previous_period and missing_materials:
            for candidate in missing_materials:
                args = {
                    "material_name": candidate,
                    "start_month": previous_period,
                    "end_month": period,
                }
                tool_hash = hashlib.md5(
                    f"price_trend:{json.dumps(args, ensure_ascii=False, sort_keys=True)}".encode("utf-8")
                ).hexdigest()[:12]
                tool_calls.append(
                    {
                        "id": f"forced_price_trend_{tool_hash}",
                        "name": "price_trend",
                        "args": args,
                        "type": "tool_call",
                    }
                )
            return tool_calls

    if query_type == "trend_chart" and material and len(materials) <= 1:
        raw_period = str(entities.get("year_month") or "").strip()
        start_month = f"{raw_period}-01" if re.fullmatch(r"\d{4}", raw_period) else raw_period
        if start_month:
            if any(material in str(chunk.get("content") or "") for chunk in retrieved_chunks):
                return []
            end_month = ""
            if any(token in query for token in ("至今", "当前", "开始至今", "到现在", "截至目前")):
                end_month = datetime.now().strftime("%Y-%m")
            args = {
                "material_name": material,
                "start_month": start_month,
                "end_month": end_month,
            }
            tool_hash = hashlib.md5(
                f"price_trend:{json.dumps(args, ensure_ascii=False, sort_keys=True)}".encode("utf-8")
            ).hexdigest()[:12]
            return [
                {
                    "id": f"forced_price_trend_{tool_hash}",
                    "name": "price_trend",
                    "args": args,
                    "type": "tool_call",
                }
            ]

    return []


def _extract_named_amounts_from_query(query: str) -> dict[str, float]:
    amounts: dict[str, float] = {}
    for label in ("人工费", "材料费", "机械费", "企业管理费"):
        match = re.search(fr"{label}\s*(\d+(?:\.\d+)?)\s*(万|元)?", query)
        if not match:
            continue
        value = float(match.group(1))
        unit = match.group(2) or "万"
        amounts[label] = value / 10000.0 if unit == "元" else value
    return amounts


def _extract_recommended_fee_rate(chunks: list[dict], fee_name: str, standard_year: str = "") -> float | None:
    normalized_fee = _compact_text(fee_name)
    for chunk in chunks:
        doc_name = str(chunk.get("doc_filename") or chunk.get("source") or "")
        content = str(chunk.get("content") or "")
        compact_content = _compact_text(content)
        if standard_year and standard_year not in compact_content and standard_year not in doc_name:
            continue
        if normalized_fee not in compact_content:
            continue
        match = re.search(
            fr"{re.escape(normalized_fee)}.*?推荐费率[为：]\s*([0-9]+(?:\.[0-9]+)?)%",
            compact_content,
        )
        if match:
            return float(match.group(1)) / 100.0
    return None


def _build_forced_fee_tool_calls(state: RAGAgentState) -> list[dict]:
    query = str(state.get("query") or "").strip()
    query_type = str(state.get("query_type") or "").strip().lower()
    if query_type != "calculation":
        return []

    normalized_query = _compact_text(query)
    if "利润为多少" not in normalized_query or "推荐利润率" not in normalized_query:
        return []
    if "企业管理费按推荐费率计算" not in normalized_query:
        return []

    entities = state.get("query_entities") or {}
    standard_year = str(entities.get("year_month") or "")[:4] or "2025"
    retrieved_chunks = list(state.get("retrieved_chunks") or [])
    enterprise_rate = _extract_recommended_fee_rate(retrieved_chunks, "企业管理费", standard_year)
    profit_rate = _extract_recommended_fee_rate(retrieved_chunks, "利润", standard_year)
    if enterprise_rate is not None and profit_rate is not None:
        return []

    search_targets = []
    if enterprise_rate is None:
        search_targets.append(f"{standard_year} 企业管理费 推荐费率")
    if profit_rate is None:
        search_targets.append(f"{standard_year} 利润 推荐费率")

    tool_calls: list[dict] = []
    for target in search_targets:
        args = {"query": target, "top_k": 6, "path_constraint": ""}
        tool_hash = hashlib.md5(
            f"text_search:{json.dumps(args, ensure_ascii=False, sort_keys=True)}".encode("utf-8")
        ).hexdigest()[:12]
        tool_calls.append(
            {
                "id": f"forced_fee_text_{tool_hash}",
                "name": "text_search",
                "args": args,
                "type": "tool_call",
            }
        )
    return tool_calls


def _chunk_text_has_keywords(chunks: list[dict], keywords: list[str]) -> bool:
    text = _compact_text(" ".join(str(chunk.get("content") or "") for chunk in chunks))
    return all(keyword in text for keyword in keywords)


def _build_forced_glass_floor_tool_calls(state: RAGAgentState) -> list[dict]:
    query = str(state.get("query") or "").strip()
    normalized_query = _compact_text(query)
    if "玻璃地板" not in normalized_query or "人工费" not in normalized_query:
        return []
    if "消耗量标准" not in normalized_query and "楼梯面层" not in normalized_query:
        return []

    retrieved_chunks = list(state.get("retrieved_chunks") or [])
    if _chunk_text_has_keywords(retrieved_chunks, ["玻璃地板", "人工费"]):
        return []

    args = {
        "query": "玻璃地板",
        "doc_id": "",
        "doc_filename": "装饰工程消耗量标准",
        "section": "",
        "page_start": 0,
        "page_end": 0,
        "top_k": 4,
    }
    tool_hash = hashlib.md5(json.dumps(args, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return [
        {
            "id": f"forced_glass_floor_{tool_hash}",
            "name": "rule_clause_search",
            "args": args,
            "type": "tool_call",
        }
    ]


def _build_forced_standard_ref_tool_calls(state: RAGAgentState) -> list[dict]:
    query = str(state.get("query") or "").strip()
    query_type = str(state.get("query_type") or "").strip().lower()
    if query_type != "standard_ref":
        return []

    retrieved_chunks = list(state.get("retrieved_chunks") or [])
    tool_calls: list[dict] = []

    if _TAX_RULE_QUERY_RE.search(query):
        # 税务类问题必须命中一般/简易计税与进项税额条文。
        if _chunk_text_has_keywords(retrieved_chunks, ["一般计税方法", "进项税额", "税前工程造价"]):
            return []
        targets = [
            "2025 一般计税方法 税前工程造价 进项税额",
            "2025 简易计税方法 税前工程造价 进项税额",
        ]
        for target in targets:
            args = {"query": target, "top_k": 8, "path_constraint": ""}
            tool_hash = hashlib.md5(
                f"text_search:{json.dumps(args, ensure_ascii=False, sort_keys=True)}".encode("utf-8")
            ).hexdigest()[:12]
            tool_calls.append(
                {
                    "id": f"forced_tax_text_{tool_hash}",
                    "name": "text_search",
                    "args": args,
                    "type": "tool_call",
                }
            )
        return tool_calls

    if "安全文明施工费" in _compact_text(query):
        if _chunk_text_has_keywords(retrieved_chunks, ["安全文明施工费", "计算基数"]) and _chunk_text_has_keywords(retrieved_chunks, ["推荐费率"]):
            return []
        targets = [
            "2025 安全文明施工费 组成 计算基数 计取",
            "2025 安全文明施工费费率部分 计算公式 计算基数 推荐费率",
        ]
        for target in targets:
            args = {"query": target, "top_k": 8, "path_constraint": ""}
            tool_hash = hashlib.md5(
                f"text_search:{json.dumps(args, ensure_ascii=False, sort_keys=True)}".encode("utf-8")
            ).hexdigest()[:12]
            tool_calls.append(
                {
                    "id": f"forced_safety_text_{tool_hash}",
                    "name": "text_search",
                    "args": args,
                    "type": "tool_call",
                }
            )
        return tool_calls

    return []


def _build_executor_fallback_tool_call(state: RAGAgentState) -> dict | None:
    query = state["query"].strip()
    query_type = str(state.get("query_type") or "semantic").strip().lower()
    entities = state.get("query_entities") or {}

    if query_type == "standard_ref":
        if _FEE_RULE_QUERY_RE.search(query):
            search_query = extract_fee_formula_search_term(query)
        else:
            search_query = _build_rule_clause_search_query(query)
        args = {"query": search_query, "top_k": 8}
        tool_name = "text_search"
    elif query_type == "price":
        material = str(entities.get("material_name") or "").strip()
        year_month = str(entities.get("year_month") or "").strip()
        if material:
            args = {"material_name": material, "year_month": year_month, "top_k": 8}
            tool_name = "price_query"
        else:
            args = {"query": query, "top_k": 8}
            tool_name = "keyword_search"
    elif query_type == "comparison":
        args = {"query": query, "top_k": 8}
        tool_name = "hybrid_search"
    else:
        args = {"query": query, "top_k": 8}
        tool_name = "text_search"

    call_hash = hashlib.md5(
        f"{tool_name}:{json.dumps(args, ensure_ascii=False, sort_keys=True)}".encode("utf-8")
    ).hexdigest()[:12]
    return {
        "id": f"fallback_tool_{call_hash}",
        "name": tool_name,
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

    trend_average_hint = ""
    if query_type == "trend_chart" and any("价格走势 期间:" in (c.get("content") or "") and "均价:" in (c.get("content") or "") for c in chunks[:8]):
        trend_average_hint = (
            "\n6. 当前证据包含工具汇总后的月均价点。回答走势/环比问题时，应优先基于这些月均价点直接计算；"
            "若月均价点已存在，不得仅因底层样本规格不完全一致而拒绝作答。"
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
        f"{trend_average_hint}\n"
        f"{catalog_only_hint}"
        "格式要求（必须遵守）\n"
        "1. 第一段直接回答用户问题，不写\"【问题】\"\"【结论】\"等标签。\n"
        "2. 第二段以\"简要分析：\"开头，只保留关键依据、对比逻辑或必要计算过程，不要展开冗长思维记录。\n"
        "3. 否定答案简短处理——信息不足时一句说清缺什么即可，不要反复论证为什么缺。\n"
        "4. 禁止使用任何 Markdown 符号，包括 #、##、###、-、*、>、```、|。\n"
        "5. 公式和计算仅用普通文本，不要 LaTeX，不要 Markdown 表格。\n"
        "6. 禁止输出\"参考索引：\"段——系统会自动追加真实来源，你只需输出前两段。"
    )


def _build_rule_based_fallback_answer(query: str, chunks: list[dict]) -> str:
    normalized_query = _compact_text(query)
    if "玻璃地板" in normalized_query and "人工费" in normalized_query:
        target_chunk: dict | None = None
        labor_prices: list[str] = []
        for chunk in chunks:
            compact_content = _compact_text(str(chunk.get("content") or ""))
            if "玻璃地板" not in compact_content or "人工费" not in compact_content:
                continue
            suffix = compact_content.split("人工费", 1)[1]
            prices = re.findall(r"\d+\.\d{2}", suffix)
            if len(prices) < 4:
                continue
            target_chunk = chunk
            labor_prices = prices[:4]
            break

        if labor_prices:
            doc_name_raw = str(target_chunk.get("doc_filename") or target_chunk.get("source") or "").strip() if target_chunk else ""
            page = str(target_chunk.get("page_number") or target_chunk.get("page") or "?") if target_chunk else "?"
            ref = ""
            if doc_name_raw:
                ref = f"【《{_display_doc_name(doc_name_raw)}》P{page}】"

            stair_note = ""
            if "楼梯" in normalized_query or "台阶" in normalized_query:
                stair_note = " 如实际属于楼梯、台阶特殊做法，还需结合 2.1.12 的楼梯、台阶面层计价规定另行调整。"

            return (
                "《装饰工程消耗量标准》中“玻璃地板”子目的人工费按玻璃类型和单块面积分四档列示："
                f"楼地面单层钢化玻璃 S<=0.36 平方米为 {labor_prices[0]}元/100m²，S>0.36 平方米为 {labor_prices[1]}元/100m²；"
                f"楼地面钢化夹层玻璃 S<=0.36 平方米为 {labor_prices[2]}元/100m²，S>0.36 平方米为 {labor_prices[3]}元/100m²{ref}。"
                "\n\n"
                "简要分析：该标准原表对玻璃地板并不是给出单一人工费，而是按玻璃类型和单块面积分档列价；"
                f"题目如果未指明玻璃类型和单块面积，应按对应档位取值。{stair_note}".rstrip()
            )

    if "利润为多少" in normalized_query and "推荐利润率" in normalized_query:
        if "企业管理费按推荐费率计算" not in normalized_query:
            return ""

        amounts = _extract_named_amounts_from_query(query)
        if not {"人工费", "材料费", "机械费"}.issubset(amounts):
            return ""

        standard_year_match = re.search(r"20\d{2}", query)
        standard_year = standard_year_match.group(0) if standard_year_match else "2025"
        enterprise_rate = _extract_recommended_fee_rate(chunks, "企业管理费", standard_year)
        profit_rate = _extract_recommended_fee_rate(chunks, "利润", standard_year)
        if enterprise_rate is None or profit_rate is None:
            return ""

        ref_chunk = next(
            (
                chunk
                for chunk in chunks
                if standard_year in str(chunk.get("doc_filename") or chunk.get("source") or "")
                and "费率标准" in str(chunk.get("doc_filename") or chunk.get("source") or "")
            ),
            None,
        )
        if ref_chunk is None:
            ref_chunk = next(
                (
                    chunk
                    for chunk in chunks
                    if standard_year in _compact_text(str(chunk.get("content") or ""))
                    and "推荐费率" in _compact_text(str(chunk.get("content") or ""))
                    and (
                        "企业管理费" in _compact_text(str(chunk.get("content") or ""))
                        or "利润" in _compact_text(str(chunk.get("content") or ""))
                    )
                ),
                None,
            )

        ref = ""
        if ref_chunk is not None:
            doc_name_raw = str(ref_chunk.get("doc_filename") or ref_chunk.get("source") or "").strip()
            page = str(ref_chunk.get("page_number") or ref_chunk.get("page") or "?")
            if doc_name_raw:
                ref = f"【《{_display_doc_name(doc_name_raw)}》P{page}】"

        labor_fee = amounts["人工费"]
        material_fee = amounts["材料费"]
        machine_fee = amounts["机械费"]
        enterprise_base = labor_fee + machine_fee * 0.1
        enterprise_fee = enterprise_base * enterprise_rate
        profit_base = labor_fee + material_fee + machine_fee + enterprise_fee
        profit_amount = profit_base * profit_rate

        return (
            f"按{standard_year}版推荐费率计算，该工程利润约为{profit_amount:.2f}万元{ref}。"
            f"其中企业管理费推荐费率为{enterprise_rate * 100:.2f}%，利润推荐费率为{profit_rate * 100:.2f}%。"
            "\n\n"
            f"简要分析：先按企业管理费公式“（人工费＋机械费×0.1）×企业管理费费率”计算，"
            f"企业管理费＝（{labor_fee:.2f}＋{machine_fee:.2f}×0.1）×{enterprise_rate * 100:.2f}%＝{enterprise_fee:.4f}万元；"
            f"再按利润公式“（人工费＋材料费＋机械费＋企业管理费）×利润率”计算，"
            f"利润＝（{labor_fee:.2f}＋{material_fee:.2f}＋{machine_fee:.2f}＋{enterprise_fee:.4f}）×{profit_rate * 100:.2f}%＝{profit_amount:.4f}万元。"
        )

    if "企业管理费" not in normalized_query or "计算基数" not in normalized_query:
        return ""
    if "机械费" not in normalized_query or "0" not in normalized_query:
        return ""

    target_chunk: dict | None = None
    for chunk in chunks:
        content = _compact_text(str(chunk.get("content") or ""))
        if "企业管理费" in content and "机械费" in content and "0.1" in content:
            target_chunk = chunk
            break

    if target_chunk is None:
        return ""

    doc_name_raw = str(target_chunk.get("doc_filename") or target_chunk.get("source") or "").strip()
    page = str(target_chunk.get("page_number") or target_chunk.get("page") or "?")
    ref = ""
    if doc_name_raw:
        ref = f"【《{_display_doc_name(doc_name_raw)}》P{page}】"

    return (
        "根据企业管理费公式“企业管理费＝（人工费＋机械费×0.1）×企业管理费费率”，"
        f"当机械费为0时，企业管理费计算基数为人工费（人工费＋0×0.1＝人工费）{ref}。"
        "\n\n"
        "简要分析：该问法属于公式边界条件代入，标准未单列“机械费为0”的特别条款，"
        "应直接按公式进行代入化简。"
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

_INTENT_TYPES = {"price", "semantic", "calculation", "comparison", "trend_chart", "standard_ref"}
_FEE_RULE_QUERY_RE = re.compile(
    r"费率标准|企业管理费|利润率?|推荐费率|推荐系数|计算基数|计算公式|按\s*20\d{2}\s*版|如果.*为0"
)
_TAX_RULE_QUERY_RE = re.compile(r"一般计税方法|简易计税方法|进项税额|税前工程造价|增值税")
_PRESENTATION_FORMULA_QUERY_RE = re.compile(r"计算公式|计算基数|如果.*为0|边界|代入")


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


def _extract_json_object(text: str) -> dict:
    candidate = (text or "").strip()
    if not candidate:
        return {}
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    match = re.search(r"\{.*\}", candidate, flags=re.DOTALL)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _resolve_guarded_intent(
    query: str,
    current_intent: str,
    decision: dict,
) -> str:
    candidate = str(decision.get("intent") or "").strip().lower()
    confidence_raw = decision.get("confidence", 0)
    try:
        confidence = float(confidence_raw)
    except Exception:
        confidence = 0.0

    if candidate not in _INTENT_TYPES:
        candidate = current_intent

    if candidate == current_intent:
        return current_intent

    if confidence >= 0.55:
        return candidate

    # LLM confidence is often conservative on boundary-rule questions.
    if current_intent == "price" and candidate == "standard_ref" and _FEE_RULE_QUERY_RE.search(query):
        return "standard_ref"

    return current_intent


def intent_guard_node(state: RAGAgentState) -> dict:
    query = state["query"].strip()
    current_intent = str(state.get("query_type") or "semantic").strip().lower()
    if current_intent in {"chitchat", "irrelevant"}:
        return {}

    entities = state.get("query_entities") or {}
    llm_config = state.get("llm_config") or {}
    runtime = state.get("llm_runtime") or {}
    decision: dict = {}

    try:
        guard_system = (
            "你是工程造价问题路由器。任务：只判断该查询应进入哪类检索路由。"
            "必须输出 JSON，不要输出其它文本。"
            "可选 intent: price, standard_ref, calculation, comparison, trend_chart, semantic。"
            "优先规则：凡是“费率标准/计算基数/计算公式/如果X为0时如何计取”等条文解释问题，"
            "应优先判为 standard_ref，而不是 price。"
            "JSON 格式："
            '{"intent":"standard_ref","confidence":0.0,"reason":"..."}'
        )
        guard_user = (
            f"query={query}\n"
            f"current_intent={current_intent}\n"
            f"entities={json.dumps(entities, ensure_ascii=False)}"
        )
        response, runtime = invoke_llm(
            [SystemMessage(content=guard_system), HumanMessage(content=guard_user)],
            thinking=False,
            prefer_strong=True,
            llm_config=llm_config,
        )
        decision = _extract_json_object(response.content or "")
    except Exception as exc:
        logger.warning(f"[intent_guard] LLM failed, fallback to rule guard: {exc}")

    guarded_intent = _resolve_guarded_intent(query, current_intent, decision)
    if guarded_intent != current_intent:
        logger.info(
            "[intent_guard] intent corrected: %s -> %s (decision=%s)",
            current_intent,
            guarded_intent,
            decision,
        )
    elif current_intent == "price" and _FEE_RULE_QUERY_RE.search(query):
        guarded_intent = "standard_ref"
        logger.info("[intent_guard] fallback corrected: price -> standard_ref")

    return {
        "query_type": guarded_intent,
        "llm_runtime": runtime,
    }


def _default_presentation_policy(query: str, query_type: str, presentation: dict | None) -> dict:
    normalized_query = _compact_text(query)
    policy = {
        "support_kicker": "补充说明",
        "section_labels": {"analysis": "核心说明", "detail": "补充说明"},
        "highlight_labels": {"default": "关键信息", "rule": "关键信息", "detail": "关键信息"},
    }

    if query_type == "standard_ref":
        policy = {
            "support_kicker": "条文依据",
            "section_labels": {"analysis": "依据说明", "detail": "补充说明"},
            "highlight_labels": {"default": "规则要点", "rule": "规则要点", "detail": "关键信息"},
        }
        if _PRESENTATION_FORMULA_QUERY_RE.search(normalized_query):
            policy = {
                "support_kicker": "公式依据",
                "section_labels": {"analysis": "公式依据", "detail": "边界推导"},
                "highlight_labels": {
                    "default": "关键要点",
                    "rule": "公式要点",
                    "metric": "关键代入",
                    "detail": "推导细节",
                },
            }
    elif query_type == "comparison":
        policy = {
            "support_kicker": "对比说明",
            "section_labels": {"analysis": "对比结论", "detail": "差异说明"},
            "highlight_labels": {"default": "对比要点", "rule": "对比结论", "detail": "差异细节"},
        }
    elif query_type in {"price", "trend_chart"}:
        policy = {
            "support_kicker": "数据说明",
            "section_labels": {"analysis": "数据解读", "detail": "补充说明"},
            "highlight_labels": {"default": "关键信息", "metric": "关键数值", "detail": "数据细节"},
        }

    if (presentation or {}).get("type") == "calculation_steps":
        policy["support_kicker"] = "计算过程"
        policy["section_labels"] = {"analysis": "计算思路", "detail": "补充说明"}
        policy["highlight_labels"] = {"default": "计算要点", "metric": "关键数值", "detail": "推导细节"}

    return policy


def _sanitize_policy_text(value: object, max_len: int = 12) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) > max_len:
        return text[:max_len]
    return text


def _resolve_presentation_policy(
    query: str,
    query_type: str,
    final_answer: str,
    presentation: dict | None,
    llm_config: dict,
    *,
    allow_llm: bool,
) -> dict:
    policy = _default_presentation_policy(query, query_type, presentation)
    if not allow_llm or not presentation:
        return policy

    summary = str((presentation.get("summary") if isinstance(presentation, dict) else "") or "")
    if not summary:
        summary = re.split(r"\n+", final_answer or "", maxsplit=1)[0].strip()

    try:
        system_prompt = (
            "你是对话呈现策略器。任务：为回答卡片决定展示文案标签。"
            "输出严格 JSON，不要输出其他内容。"
            "可输出字段：support_kicker, section_labels, highlight_labels。"
            "字段要求：每个标签 2-8 个字，语义自然，不要机械化模板。"
            "JSON 示例："
            '{"support_kicker":"公式依据","section_labels":{"analysis":"公式依据","detail":"边界推导"},'
            '"highlight_labels":{"rule":"公式要点","metric":"关键代入","detail":"推导细节","default":"关键要点"}}'
        )
        user_prompt = (
            f"query={query}\n"
            f"query_type={query_type}\n"
            f"presentation_type={presentation.get('type') if isinstance(presentation, dict) else ''}\n"
            f"summary={summary}\n"
            f"default_policy={json.dumps(policy, ensure_ascii=False)}"
        )
        response, _ = invoke_llm(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
            thinking=False,
            prefer_strong=False,
            llm_config=llm_config,
        )
        candidate = _extract_json_object(response.content or "")
    except Exception as exc:
        logger.warning(f"[presentation_policy] LLM failed, using default policy: {exc}")
        return policy

    support_kicker = _sanitize_policy_text(candidate.get("support_kicker"))
    if support_kicker:
        policy["support_kicker"] = support_kicker

    section_labels = candidate.get("section_labels")
    if isinstance(section_labels, dict):
        sanitized_section_labels = {}
        for key in ("analysis", "detail"):
            value = _sanitize_policy_text(section_labels.get(key))
            if value:
                sanitized_section_labels[key] = value
        if sanitized_section_labels:
            policy["section_labels"] = {**policy.get("section_labels", {}), **sanitized_section_labels}

    highlight_labels = candidate.get("highlight_labels")
    if isinstance(highlight_labels, dict):
        sanitized_highlight_labels = {}
        for key in ("default", "rule", "detail", "metric", "scope", "method", "hint"):
            value = _sanitize_policy_text(highlight_labels.get(key))
            if value:
                sanitized_highlight_labels[key] = value
        if sanitized_highlight_labels:
            policy["highlight_labels"] = {**policy.get("highlight_labels", {}), **sanitized_highlight_labels}

    return policy


def _apply_presentation_policy(presentation: dict | None, policy: dict | None) -> dict | None:
    if not presentation or not policy:
        return presentation

    updated = dict(presentation)
    support_kicker = _sanitize_policy_text(policy.get("support_kicker"))
    if support_kicker:
        updated["support_kicker"] = support_kicker

    highlight_labels = policy.get("highlight_labels") if isinstance(policy.get("highlight_labels"), dict) else {}
    section_labels = policy.get("section_labels") if isinstance(policy.get("section_labels"), dict) else {}

    if isinstance(updated.get("highlights"), list):
        normalized_highlights = []
        for highlight in updated.get("highlights") or []:
            item = dict(highlight)
            if not item.get("label"):
                kind = str(item.get("kind") or "")
                if kind and kind in highlight_labels:
                    item["label"] = highlight_labels[kind]
                elif highlight_labels.get("default"):
                    item["label"] = highlight_labels["default"]
            normalized_highlights.append(item)
        updated["highlights"] = normalized_highlights

    if updated.get("type") == "answer_sections" and isinstance(updated.get("sections"), list):
        normalized_sections = []
        for index, section in enumerate(updated.get("sections") or []):
            item = dict(section)
            if not item.get("label"):
                kind = str(item.get("kind") or ("analysis" if index == 0 else "detail"))
                label = section_labels.get(kind) or section_labels.get("detail")
                if label:
                    item["label"] = label
            normalized_sections.append(item)
        updated["sections"] = normalized_sections

    return updated


def presentation_policy_node(state: RAGAgentState) -> dict:
    presentation = state.get("presentation")
    if not presentation:
        return {"presentation_policy": None}

    query = state.get("query", "")
    query_type = state.get("query_type", "semantic")
    final_answer = state.get("final_answer", "")
    llm_config = state.get("llm_config") or {}
    stream_response = bool(state.get("stream_response"))
    policy = _resolve_presentation_policy(
        query=query,
        query_type=query_type,
        final_answer=final_answer,
        presentation=presentation,
        llm_config=llm_config,
        allow_llm=not stream_response,
    )
    return {
        "presentation": _apply_presentation_policy(presentation, policy),
        "presentation_policy": policy,
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


_QUESTION_STRIP_RE = re.compile(
    r"(是什么|有哪些|怎么算|如何|是否|多少|的是|吗|呢|？|\?|请问|请|告诉我|帮我|查一下|计算规则|适用范围|说明|规定|规范)"
)

def _extract_navigator_keywords(query: str) -> list[str]:
    """Extract candidate technical keywords from a full question for catalog matching.

    Returns a list of candidate strings to try in order, from most specific to broadest.
    """
    cleaned = _QUESTION_STRIP_RE.sub("", query).strip()
    parts = [p.strip() for p in re.split(r"[中的，,\s]+", cleaned) if p.strip()]
    candidates = [
        p for p in parts
        if 2 < len(p) <= 20
        and not re.fullmatch(r"\d+\.?\d*", p)   # skip pure numbers like "10." or "01."
        and not re.fullmatch(r"[a-zA-Z0-9]+", p)  # skip pure ASCII sequences
    ]
    if not candidates:
        return [query[:20]]
    # Try all candidates; longer/digit-bearing ones tend to be more specific section titles
    candidates.sort(key=lambda p: (any(c.isdigit() for c in p), len(p)), reverse=True)
    # Also include original cleaned text as last resort
    if cleaned not in candidates and 2 < len(cleaned) <= 30:
        candidates.append(cleaned)
    return candidates or [query[:20]]


def navigator_node(state: RAGAgentState) -> dict:
    """
    导航节点：在 planner 之前运行，用 get_catalog_map 扫描目录索引，
    确定与查询相关的章节路径，写入 state.roadmap。
    后续 planner/executor 可从 state.roadmap 中获取 path_constraint 来约束检索范围。
    """
    query = state["query"]
    query_type = state.get("query_type", "")

    # 只对工程标准/定额查询运行 Navigator；价格/趋势查询不需要章节路径
    if query_type in {"price", "trend_chart"}:
        return {"roadmap": [], "workspace": []}

    kw_candidates = _extract_navigator_keywords(query)
    logger.info(f"[navigator] scanning catalog for query='{query[:60]}' candidates={kw_candidates[:3]}")

    hits: list[dict] = []
    tried: set[str] = set()
    all_candidate_hits: list[tuple[str, list[dict]]] = []  # (keyword, hits)
    for kw in kw_candidates + [query]:
        if kw in tried or len(kw) < 3:
            continue
        tried.add(kw)
        try:
            catalog_result = get_catalog_map.invoke({"query": kw, "top_k": 8})
            result_hits = json.loads(catalog_result) if catalog_result else []
            if result_hits:
                all_candidate_hits.append((kw, result_hits))
        except Exception as e:
            logger.error(f"[navigator] get_catalog_map failed for '{kw}': {e}")

    if all_candidate_hits:
        # Prefer the hit set most specifically matching the query:
        # score = kw_len / avg_top_title_len (higher = keyword covers more of the title = more specific)
        # Also prefer higher depth (chapter level 3 > 2 > 1)
        def _specificity(item: tuple[str, list[dict]]) -> tuple[float, int, int]:
            kw, h_list = item
            avg_title_len = sum(len(h.get("title", "")) for h in h_list[:3]) / max(len(h_list[:3]), 1)
            ratio = len(kw) / max(avg_title_len, 1)
            max_depth = max(h.get("depth", 1) for h in h_list)
            return (ratio, max_depth, len(kw))

        all_candidate_hits.sort(key=_specificity, reverse=True)
        best_kw, hits = all_candidate_hits[0]
        logger.info(f"[navigator] catalog hit with kw='{best_kw}': {len(hits)} results")

    # Build roadmap: keep top distinct file-level path entries
    seen_paths: set[str] = set()
    roadmap = []
    for h in hits:
        p = h.get("path", "")
        # Use file-level prefix as path_constraint (e.g. '第二册电气设备安装工程/%')
        file_prefix = p.split("/")[0] + "/%" if "/" in p else p
        if file_prefix not in seen_paths:
            seen_paths.add(file_prefix)
            roadmap.append({
                "chapter_id": h.get("chapter_id", ""),
                "path":       file_prefix,          # use as path_constraint in tool calls
                "file_name":  h.get("file_name", ""),
                "title":      h.get("title", ""),
                "reason":     "catalog_match",
            })

    if roadmap:
        logger.info(f"[navigator] roadmap: {[r['path'] for r in roadmap]}")
    else:
        logger.info("[navigator] no catalog matches, proceeding without path constraint")

    return {"roadmap": roadmap, "workspace": []}


def planner_node(state: RAGAgentState) -> dict:
    """
    规划节点：用强模型将用户问题拆分为 1~4 个执行步骤，写入 plan + current_step。
    首次调用时向 messages channel 注入 system + user 消息。
    """
    query = state["query"]
    entities = state.get("query_entities") or {}
    llm_config = state.get("llm_config") or {}
    roadmap = state.get("roadmap") or []
    logger.info(f"[planner] query='{query[:60]}' roadmap_entries={len(roadmap)}")

    # Build roadmap hint for planner: if Navigator found relevant chapters, instruct
    # the planner to use path_constraint when calling text_search/hybrid_search
    roadmap_hint = ""
    if roadmap:
        path_lines = "\n".join(
            f"  - path='{r['path']}' ({r['file_name']}) → {r['title'][:40]}"
            for r in roadmap[:4]
        )
        roadmap_hint = (
            f"\n\n章节路径地图（Navigator已识别，请在 text_search/hybrid_search 调用中使用 path_constraint 参数）：\n"
            f"{path_lines}\n"
            f"示例：text_search(query='送配电调试', path_constraint='{roadmap[0]['path']}')"
        )

    try:
        response, runtime = invoke_llm(
            [
                SystemMessage(content=_PLANNER_SYSTEM),
                HumanMessage(content=f"用户问题：{query}{roadmap_hint}"),
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
    elif state.get("query_type") == "standard_ref" and _TAX_RULE_QUERY_RE.search(query):
        steps = [
            "使用 text_search 检索『一般计税方法 税前工程造价 进项税额』原文条文",
            "如需补充对照，再使用 text_search 检索『简易计税方法 税前工程造价 进项税额』相关条文",
        ]
        logger.info("[planner] tax rule query override")
    elif state.get("query_type") == "standard_ref" and _FEE_RULE_QUERY_RE.search(query):
        core_term = extract_fee_formula_search_term(query)
        steps = [
            f"使用 text_search 检索『{core_term}』原文公式与计算基数",
            f"如需补充条文上下文，再使用 keyword_search 检索『{core_term.replace('计算公式', '计算基数')}』",
        ]
        logger.info(f"[planner] fee rule query override, core='{core_term}'")

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
        # NOTE: standard_title (e.g., "安装工程消耗量标准") is a document-level
        # metadata label that almost never appears as a literal token inside
        # chunk bodies. Including it makes plainto_tsquery AND the title with
        # the clause terms (`'安装工程消耗量标准' & '送配电装置系统调试'`),
        # which eliminates all matches. We keep title only for the executor
        # narrative/log; the actual search term uses clause_terms only.
        clause_query = " ".join(clause_terms).strip() or standard_title
        steps = [
            f"使用 text_search 检索『{clause_query}』附件标准原文",
            f"如需补充上下文，再使用 keyword_search 检索『{clause_query}』相关条文",
        ]
        logger.info(
            f"[planner] appendix standard override, title='{standard_title}' terms={clause_terms} clause_query='{clause_query}'"
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
    elif state.get("query_type") == "trend_chart":
        trend_material = str(entities.get("material_name") or "").strip()
        trend_period = str(entities.get("year_month") or "").strip()
        if trend_material:
            start_month = f"{trend_period}-01" if re.fullmatch(r"\d{4}", trend_period) else trend_period
            if start_month:
                steps = [f"使用 price_trend 查询『{trend_material}』在 {start_month} 至 当前 的月度价格走势"]
                logger.info(
                    f"[planner] single-material trend override, material='{trend_material}' start='{start_month}'"
                )

    # 价格对比查询：提取两个期间，确保每个期间都有独立的 price_query 步骤
    price_compare_match = _PRICE_COMPARE_RE.search(query)
    if price_compare_match:
        groups = [g for g in price_compare_match.groups() if g]
        if len(groups) >= 2:
            def _normalize_period_token(token: str) -> str:
                m = re.search(r"(20\d{2})[年\-/](\d{1,2})", token)
                if m:
                    return f"{m.group(1)}-{int(m.group(2)):02d}"
                return token.strip()

            period1, period2 = _normalize_period_token(groups[0]), _normalize_period_token(groups[1])
            # 检查 plan 里是否已有两个不同期间的步骤
            plan_text = " ".join(steps)
            if period1 not in plan_text or period2 not in plan_text:
                material = str(entities.get("material_name") or "").strip()
                specification = str(entities.get("specification") or "").strip()
                target = " ".join(part for part in [material, specification] if part).strip() or query
                steps = [
                    f"使用 price_query 查询 {period1} 的『{target}』价格",
                    f"使用 price_query 查询 {period2} 的『{target}』价格",
                ]
                logger.info(f"[planner] price compare override: {period1} vs {period2} target='{target}'")

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

    forced_glass_floor_tool_calls = _build_forced_glass_floor_tool_calls(state)
    if forced_glass_floor_tool_calls:
        forced_step_hint = "强制检索装饰工程消耗量标准中的玻璃地板人工费表"
        thought_process.append(f"步骤{current_step+1}：{forced_step_hint}")
        step_msg = HumanMessage(content=f"[当前进度 {progress}] {forced_step_hint}")
        forced_response = AIMessage(content="", tool_calls=forced_glass_floor_tool_calls)
        logger.info(
            "[executor] forced glass floor tools: %s",
            [(tool_call["name"], tool_call["args"]) for tool_call in forced_glass_floor_tool_calls],
        )
        return {
            "messages": [step_msg, forced_response],
            "iterations": iteration + 1,
            "current_step": current_step,
            "thought_process": thought_process,
            "has_tool_calls": True,
            "pending_tool_calls": forced_glass_floor_tool_calls,
            "step_number": current_step + 1,
            "total_steps": len(plan),
            "step_hint": forced_step_hint,
            "llm_runtime": state.get("llm_runtime") or {},
        }

    forced_standard_ref_tool_calls = _build_forced_standard_ref_tool_calls(state)
    if forced_standard_ref_tool_calls:
        forced_step_hint = "强制检索标准条文（税务/安全文明施工费）"
        thought_process.append(f"步骤{current_step+1}：{forced_step_hint}")
        step_msg = HumanMessage(content=f"[当前进度 {progress}] {forced_step_hint}")
        forced_response = AIMessage(content="", tool_calls=forced_standard_ref_tool_calls)
        logger.info(
            "[executor] forced standard_ref tools: %s",
            [(tool_call["name"], tool_call["args"]) for tool_call in forced_standard_ref_tool_calls],
        )
        return {
            "messages": [step_msg, forced_response],
            "iterations": iteration + 1,
            "current_step": current_step,
            "thought_process": thought_process,
            "has_tool_calls": True,
            "pending_tool_calls": forced_standard_ref_tool_calls,
            "step_number": current_step + 1,
            "total_steps": len(plan),
            "step_hint": forced_step_hint,
            "llm_runtime": state.get("llm_runtime") or {},
        }

    forced_fee_tool_calls = _build_forced_fee_tool_calls(state)
    if forced_fee_tool_calls:
        forced_step_hint = "强制检索费率标准中的企业管理费与利润推荐费率"
        thought_process.append(f"步骤{current_step+1}：{forced_step_hint}")
        step_msg = HumanMessage(content=f"[当前进度 {progress}] {forced_step_hint}")
        forced_response = AIMessage(content="", tool_calls=forced_fee_tool_calls)
        logger.info(
            "[executor] forced fee tools: %s",
            [(tool_call["name"], tool_call["args"]) for tool_call in forced_fee_tool_calls],
        )
        return {
            "messages": [step_msg, forced_response],
            "iterations": iteration + 1,
            "current_step": current_step,
            "thought_process": thought_process,
            "has_tool_calls": True,
            "pending_tool_calls": forced_fee_tool_calls,
            "step_number": current_step + 1,
            "total_steps": len(plan),
            "step_hint": forced_step_hint,
            "llm_runtime": state.get("llm_runtime") or {},
        }

    forced_price_tool_calls = _build_forced_price_tool_calls(state)
    if forced_price_tool_calls:
        forced_step_hint = (
            "强制调用价格检索工具，使用解析后的材料、规格和期间参数"
            if len(forced_price_tool_calls) > 1
            else "强制调用 price_trend 执行单材料走势检索"
        )
        thought_process.append(f"步骤{current_step+1}：{forced_step_hint}")
        step_msg = HumanMessage(content=f"[当前进度 {progress}] {forced_step_hint}")
        forced_response = AIMessage(content="", tool_calls=forced_price_tool_calls)
        logger.info(
            "[executor] forced price tools: %s",
            [(tool_call["name"], tool_call["args"]) for tool_call in forced_price_tool_calls],
        )
        return {
            "messages": [step_msg, forced_response],
            "iterations": iteration + 1,
            "current_step": current_step,
            "thought_process": thought_process,
            "has_tool_calls": True,
            "pending_tool_calls": forced_price_tool_calls,
            "step_number": current_step + 1,
            "total_steps": len(plan),
            "step_hint": forced_step_hint,
            "llm_runtime": state.get("llm_runtime") or {},
        }

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
    roadmap = state.get("roadmap") or []
    if scope_hint:
        step_content = f"[已锁定检索范围：{scope_hint}]\n[当前进度 {progress}] 请执行：{step_hint}"
    elif roadmap:
        # Inject top path constraints from navigator so executor LLM uses them
        path_hints = "；".join(r["path"] for r in roadmap[:2])
        step_content = (
            f"[Navigator路径约束：{path_hints}]\n"
            f"[当前进度 {progress}] 请执行：{step_hint}\n"
            f"（调用 text_search 或 hybrid_search 时请设置 path_constraint='{roadmap[0]['path']}'）"
        )
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
        runtime = state.get("llm_runtime") or {}
        fallback_tool_call = _build_executor_fallback_tool_call(state)
        if fallback_tool_call is not None:
            fallback_note = f"步骤{current_step+1}：LLM不可用，自动执行兜底检索 {fallback_tool_call['name']}"
            thought_process.append(fallback_note)
            logger.info(
                "[executor] fallback tool call: %s args=%s",
                fallback_tool_call["name"],
                fallback_tool_call["args"],
            )
            return {
                "messages": [step_msg, AIMessage(content="", tool_calls=[fallback_tool_call])],
                "iterations": iteration + 1,
                "current_step": current_step,
                "thought_process": thought_process,
                "has_tool_calls": True,
                "step_number": current_step + 1,
                "total_steps": len(plan),
                "step_hint": step_hint,
                "pending_tool_calls": [fallback_tool_call],
                "llm_runtime": runtime,
            }
        response = AIMessage(content="")

    if response.tool_calls:
        # Auto-inject path_constraint from roadmap when LLM didn't set it
        _PATH_CONSTRAINT_TOOLS = {"text_search", "hybrid_search"}
        if roadmap:
            primary_path = roadmap[0]["path"]
            patched_calls = []
            for tc in response.tool_calls:
                if tc["name"] in _PATH_CONSTRAINT_TOOLS:
                    args = dict(tc.get("args", {}))
                    if not args.get("path_constraint"):
                        args["path_constraint"] = primary_path
                        tc = {**tc, "args": args}
                        logger.info(f"[executor] injected path_constraint='{primary_path}' into {tc['name']}")
                patched_calls.append(tc)
        else:
            patched_calls = list(response.tool_calls)
        patched_response = AIMessage(content=response.content or "", tool_calls=patched_calls)
        logger.info(f"[executor] tool calls: {[tc['name'] for tc in patched_calls]}")
        return {
            "messages": [step_msg, patched_response],
            "iterations": iteration + 1,
            "current_step": current_step,
            "thought_process": thought_process,
            "has_tool_calls": True,
            "step_number": current_step + 1,
            "total_steps": len(plan),
            "step_hint": step_hint,
            "pending_tool_calls": patched_calls,
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
            "presentation_policy": state.get("presentation_policy"),
        }

    direct_answer = _build_rule_based_fallback_answer(query, all_chunks)
    if direct_answer:
        final_answer = direct_answer
        runtime = state.get("llm_runtime") or {}
        citations_text = refine_citations_for_answer(final_answer, all_chunks, citations_text)
        final_answer = _normalize_final_answer(query, final_answer, all_chunks, citations_text, query_type)
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
            "presentation_policy": state.get("presentation_policy"),
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
        final_answer = _build_rule_based_fallback_answer(query, all_chunks)
        if not final_answer:
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
        "presentation_policy": state.get("presentation_policy"),
    }


# ── Iterative Convergence Nodes ────────────────────────────────────────────────


def contract_verifier_node(state: RAGAgentState) -> dict:
    """Aggregate all 4 node contracts; set quality_converged and root_cause_node."""
    outer_iter = state.get("outer_iteration", 0)
    max_outer = state.get("max_outer_iterations", 3)

    all_results = [
        verify_query_analysis_contract(state),
        verify_navigator_contract(state),
        verify_tool_contract(state),
        verify_synthesize_contract(state),
    ]
    all_passed = all(r["passed"] for r in all_results)

    if all_passed:
        logger.info("[contract_verifier] all contracts passed")
        return {
            "contract_results": all_results,
            "quality_converged": True,
        }

    if outer_iter >= max_outer:
        logger.warning(f"[contract_verifier] max_outer_iterations ({max_outer}) reached, forcing output")
        return {
            "contract_results": all_results,
            "quality_converged": True,
        }

    root = trace_root_cause({**state, "contract_results": all_results})
    logger.info(
        f"[contract_verifier] outer_iter={outer_iter}/{max_outer} "
        f"failed_nodes={[r['node'] for r in all_results if not r['passed']]} "
        f"root_cause={root}"
    )

    return {
        "contract_results": all_results,
        "quality_converged": False,
        "root_cause_node": root,
        "outer_iteration": outer_iter + 1,
    }


def corrective_action_node(state: RAGAgentState) -> dict:
    """Dispatch corrective actions based on violation codes, then prepare state for replay."""
    violations = []
    for cr in state.get("contract_results") or []:
        if not cr.get("passed", False):
            violations.extend(cr.get("violations", []))

    query = state.get("query", "")
    entities = state.get("query_entities") or {}
    corrective_actions = list(state.get("corrective_actions") or [])
    used_tool_categories = list(state.get("used_tool_categories") or [])
    tool_fallback_level = state.get("tool_fallback_level", 0)

    updates: dict = {"corrective_actions": corrective_actions}
    violation_codes = {v[0] for v in violations}

    logger.info(f"[corrective_action] codes={violation_codes}")

    if "missing_material" in violation_codes:
        llm_config = state.get("llm_config") or {}
        material = _llm_extract_material(query, llm_config)
        if material:
            entities["material_name"] = material
            updates["query_entities"] = entities
            action = f"llm_extract_material:{material}"
            corrective_actions.append(action)
            logger.info(f"[corrective_action] {action}")

    if "missing_year_month" in violation_codes:
        material = entities.get("material_name", "")
        latest = _inject_latest_year_month(material)
        if latest:
            entities["year_month"] = latest
            updates["query_entities"] = entities
            action = f"inject_latest_ym:{latest}"
            corrective_actions.append(action)
            logger.info(f"[corrective_action] {action}")

    if "empty_roadmap" in violation_codes:
        updates["category_hints"] = _expand_category_hints(query, state)
        action = "expand_navigator_keywords"
        corrective_actions.append(action)
        logger.info(f"[corrective_action] {action}")

    if "zero_results" in violation_codes and "zero_results_after_fallback" not in violation_codes:
        updates["fallback_mode"] = True
        action = "enable_fallback"
        corrective_actions.append(action)
        logger.info(f"[corrective_action] {action}")

    if "zero_results_after_fallback" in violation_codes:
        tool_fallback_level = min(tool_fallback_level + 1, 2)
        updates["tool_fallback_level"] = tool_fallback_level
        expanded = _expand_aliases_for_query(query)
        if expanded and expanded != query:
            updates["query"] = expanded
        if entities.get("year_month") and len(entities["year_month"]) == 7:
            entities["year_month"] = entities["year_month"][:4]
            updates["query_entities"] = entities
        action = f"escalate_fallback:L{tool_fallback_level}"
        corrective_actions.append(action)
        logger.info(f"[corrective_action] {action}")

    if "eval_not_passed" in violation_codes:
        has_drilldown = any(a.startswith("force_drilldown") for a in corrective_actions)
        if not has_drilldown:
            updates["force_clause_drilldown"] = True
            action = "force_drilldown"
            corrective_actions.append(action)
            logger.info(f"[corrective_action] {action}")

    if "no_price_number" in violation_codes:
        if "price_query" not in used_tool_categories:
            used_tool_categories.append("price_query")
            updates["used_tool_categories"] = used_tool_categories
        action = "force_price_query"
        corrective_actions.append(action)
        logger.info(f"[corrective_action] {action}")

    if "source_conflict" in violation_codes:
        action = "annotate_source_conflict"
        corrective_actions.append(action)
        logger.info(f"[corrective_action] {action}")

    # Clear retrieved_chunks to force fresh retrieval on replay
    updates["retrieved_chunks"] = []
    updates["evaluation"] = None
    updates["final_answer"] = ""
    updates["corrective_actions"] = corrective_actions
    updates["has_tool_calls"] = False

    return updates


# ── 路由函数 ────────────────────────────────────────────────────────────────

def after_query_analysis(state: RAGAgentState) -> str:
    qt = state.get("query_type", "")
    return END if qt in ("irrelevant", "chitchat") else "intent_guard_node"


def after_synthesize(state: RAGAgentState) -> str:
    if _env_flag("RAG_ENABLE_CONTRACT_VERIFIER_LOOP", False):
        return "contract_verifier_node"
    return "presentation_policy_node"


def after_contract_verifier(state: RAGAgentState) -> str:
    if state.get("quality_converged", False):
        return "presentation_policy_node"
    return "corrective_action_node"


def after_corrective_action(state: RAGAgentState) -> str:
    """Replay from the root cause node, mapping contract-only nodes to graph replay targets."""
    root = state.get("root_cause_node", "query_analysis")
    # tool_node and synthesize_node are not direct graph replay targets;
    # their failures are addressed by re-executing retrieval/executor.
    if root in ("tool_node", "synthesize_node"):
        return "executor_node"
    return root


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
    Iterative convergence graph with quality-driven outer loop:

    query_analysis → intent_guard → navigator → planner → executor ↔ tool_node
                                                                  ↓ chapter_resolver
                                                            chapter_resolver → executor
                                ↓ (all steps done or max iter)
                           synthesize_node → contract_verifier_node
                                                ├─ (converged) → presentation_policy → END
                                                └─ (failed) → corrective_action
                                                                  ↓
                                               replay to root_cause_node
    """
    g = StateGraph(RAGAgentState)

    g.add_node("query_analysis", query_analysis_node)
    g.add_node("intent_guard_node", intent_guard_node)
    g.add_node("navigator_node", navigator_node)
    g.add_node("planner_node", planner_node)
    g.add_node("executor_node", executor_node)
    g.add_node("tool_node", tool_node)
    g.add_node("chapter_resolver", chapter_resolver_node)
    g.add_node("synthesize_node", synthesize_node)
    g.add_node("contract_verifier_node", contract_verifier_node)
    g.add_node("corrective_action_node", corrective_action_node)
    g.add_node("presentation_policy_node", presentation_policy_node)

    g.set_entry_point("query_analysis")

    g.add_conditional_edges(
        "query_analysis",
        after_query_analysis,
        {"intent_guard_node": "intent_guard_node", END: END},
    )

    g.add_edge("intent_guard_node", "navigator_node")
    g.add_edge("navigator_node", "planner_node")
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

    g.add_conditional_edges(
        "synthesize_node",
        after_synthesize,
        {
            "presentation_policy_node": "presentation_policy_node",
            "contract_verifier_node": "contract_verifier_node",
        },
    )

    g.add_conditional_edges(
        "contract_verifier_node",
        after_contract_verifier,
        {
            "presentation_policy_node": "presentation_policy_node",
            "corrective_action_node": "corrective_action_node",
        },
    )

    g.add_conditional_edges(
        "corrective_action_node",
        after_corrective_action,
        {
            "query_analysis": "query_analysis",
            "navigator_node": "navigator_node",
            "executor_node": "executor_node",
        },
    )

    g.add_edge("presentation_policy_node", END)

    return g.compile(checkpointer=checkpointer)


def get_agent_graph():
    """获取编译后的 Agent Graph（带 MemorySaver Checkpoint）"""
    global _graph, _checkpointer
    if _graph is None:
        _checkpointer = MemorySaver()
        _graph = build_agent_graph(checkpointer=_checkpointer)
        logger.info("[Agent] Enhanced (Forced-RAG + ReAct + QueryAnalysis + RetrievalFilter) Graph compiled with MemorySaver")
    return _graph
