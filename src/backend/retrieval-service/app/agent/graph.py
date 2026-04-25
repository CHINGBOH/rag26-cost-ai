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
    extract_fill_requirement_search_term,
    extract_fee_formula_search_term,
    extract_quota_search_term,
    is_appendix_standard_query,
    is_fill_requirement_query,
    is_fee_formula_query,
)
from app.agent.tools import (
    vector_search,
    keyword_search,
    graph_search,
    hybrid_search,
    price_query,
    text_search,
    calculator,
    python_eval,
    category_search,
    price_trend,
)
from app.agent.evaluator import evaluate_retrieval_quality

logger = logging.getLogger(__name__)

_graph = None
_checkpointer = None
_analyzer = QueryAnalyzer()

# ReAct 补充轮可用的工具（PG 优先，graph_search 已废弃返回空）
REACT_TOOLS = [price_query, price_trend, text_search, vector_search, keyword_search, category_search, calculator, python_eval]

# Executor 节点的系统提示 — 带自省要求
_REACT_SYSTEM = """你是工程造价知识库问答助手，可调用以下工具检索知识库：

工具说明：
- category_search(query, top_k=5)：目录索引检索，先用此工具确认材料/工艺所在章节编号，返回章节号+标题+页码
- text_search(query, top_k=10)：全文+语义混合检索，适合费率标准、定额规范等文档；自动检索 fee_rates 结构化表
- price_query(material_name, year_month=None, specification=None)：精确查询建设工程【材料价格】（SQL），仅用于 price_records 表
- price_trend(material_name, start_month=None, end_month=None)：时序价格走势查询，返回某材料在时间范围内的月度均价列表（走势/趋势分析必用此工具）
- vector_search(query, top_k=10)：向量相似度检索，适合语义相关段落
- keyword_search(query, top_k=10)：关键词全文检索，适合精确名称匹配；自动检索 fee_rates 结构化表
- calculator(expression)：数学表达式计算
- python_eval(code)：Python代码执行（适合复杂计算）

费率标准专用路由规则（重要）：
- 含“推荐系数”、“推荐费率”、“费率标准”、“赶工措施费”、“文明施工费”的问题 → 使用 text_search 或 category_search
- 严禁对费率标准类问题使用 price_query（price_query 只查材料单价，不含费率系数）
- fee_rates 表会被 text_search/keyword_search/category_search 自动检索，无需手动 SQL
- 价格走势/趋势/变化幅度类问题 → 必须使用 price_trend，不得用 price_query 逐期查询
- 费率版本对比（2023版 vs 2025版）→ 使用 keyword_search 并在参数中包含版本年份关键词

工作方式：
1. 执行当前计划步骤，选用最合适的工具（价格类用 price_query，规范文件用 text_search）
2. 在发起新工具调用前，先评价上一步工具结果是否找到核心数据；若未找到，换关键词或换工具
3. 信息已足够时直接停止调用工具（不要重复搜索），由后续合成节点生成答案
4. 如果工具结果为空或不相关，明确说明检索失败，不要强行使用空结果

特殊检索规则（定额子目）：
- 定额文档的子目按材料/工艺命名，楼梯/墙面/柱面/天棚/楼地面等是章节分类词，不是材料名
- 检索定额子目前必须先用 category_search 确认材料所在章节编号，再带章节号做 text_search
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
- 优先使用 price_query 查材料价格，text_search 查定额规范文件
- 含"推荐系数"、"推荐费率"、"费率标准"、"赶工"、"措施费"的问题 → 第一步用 text_search（不用 price_query）
  例："赶工措施费推荐系数" → 步骤1: text_search query="赶工措施费"
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

_INTERNAL_SOURCES = {"智能体问答", "agent_qa", "eval_qa"}

_QUERY_TYPE_INSTRUCTIONS: dict[str, str] = {
    "trend_chart": "4. 先给出趋势结论（涨/跌/平稳，涨跌幅），再列关键时间节点数据；不要仅罗列数字",
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
        return []

    if query_type not in {"price", "comparison", "trend_chart"}:
        return chunks

    analysis_entities = entities or (_analyzer.analyze(query).get("entities", {}))
    material = str(analysis_entities.get("material_name") or "").strip()
    specification = str(analysis_entities.get("specification") or "").strip()
    if not material:
        return chunks

    material_matched = [
        chunk for chunk in chunks
        if material in ((chunk.get("content") or "") + " " + (chunk.get("doc_filename") or ""))
    ]
    if material_matched:
        chunks = material_matched
    elif _looks_like_annual_price_query(query, analysis_entities):
        return []

    if specification:
        spec_matched = [
            chunk for chunk in chunks
            if specification in (chunk.get("content") or "")
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


def _highlight_label(sentence: str, query_type: str) -> str:
    if any(token in sentence for token in ("适用", "适用于", "范围")):
        return "适用范围"
    if any(token in sentence for token in ("不单独计算", "不另计", "已包括", "不单列")):
        return "排除项"
    if any(token in sentence for token in ("按“", "按\"", "按", "计量单位", "为单位计算")) and "计算" in sentence:
        return "计量/计算"
    if "人工费" in sentence:
        return "人工费"
    if "材料费" in sentence:
        return "材料费"
    if "机械费" in sentence:
        return "机械费"
    if any(token in sentence for token in ("价格", "单价", "均价", "差值", "涨幅", "跌幅")):
        return "关键数值"
    if any(token in sentence for token in ("建议", "注意", "无法", "未单独列出", "缺失")):
        return "提示"
    if query_type == "standard_ref":
        return "规则要点"
    return "关键信息"


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
                "label": _highlight_label(normalized, query_type),
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
        {"label": "关键说明" if idx == 0 else "补充说明", "body": paragraph}
        for idx, paragraph in enumerate(analysis_paragraphs[:2])
    ]
    sources = _parse_citation_items(citations_text)[:4]

    note = None
    if len(query) <= 28:
        note = query

    return {
        "type": "answer_sections",
        "title": _build_answer_title(query_type),
        "note": note,
        "summary": _build_summary_text(query_type, direct_answer),
        "highlights": highlights,
        "sections": sections,
        "sources": sources,
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
    answer = _clean_markdown_noise(_strip_think_tags(answer))
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
        display = doc_name.replace(".pdf", "").replace(".xlsx", "").replace(".docx", "")
        display = display.strip("《》")
        ref_label = f"《{display}》P{page}" if doc_name else f"来源[{i}]"
        chunks_text += f"\n证据{i}：来源 {ref_label}，相关度 {score:.4f}\n内容：{content}\n"

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

    # 如果有章节定位提示，注入到步骤消息中帮助 LLM 精准检索
    category_hints = state.get("category_hints") or []
    if category_hints:
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
                    sec = item.get("section", "")
                    page = item.get("page_number", "")
                    snippet = item.get("content", "")[:60]
                    if sec or snippet:
                        hint_str = f"{sec} P{page}: {snippet}" if sec else snippet
                        if hint_str not in category_hints:
                            category_hints.append(hint_str)
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
                    "请改用 text_search 或 keyword_search 搜索相关价格文档和信息价表格。"
                )
        else:
            hint = "上一步工具未检索到相关内容，请更换关键词或切换工具（如用 text_search 替代 keyword_search）重新尝试。"
        logger.warning(f"[tool_node] no new chunks, hint: {hint[:60]}")
        extra_messages = [HumanMessage(content=hint)]

    return {
        **result,
        "retrieved_chunks": filtered,
        "category_hints": category_hints,
        "current_step": advance_step,
        "messages": result.get("messages", []) + extra_messages,
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

    all_chunks = _enrich_chunks_with_filename(all_chunks)
    all_chunks = _prune_chunks_for_query(query, query_type, all_chunks, query_entities)
    logger.info(f"[synthesize] {len(all_chunks)} chunks, query_type={query_type}")
    synthesis_prompt = _build_synthesis_prompt(query, all_chunks, query_type)
    citations_text = _format_citations(all_chunks)
    presentation = _build_presentation_payload(query, query_type, all_chunks)

    # 简单置信度估算（供 SSE eval_scores 事件用）
    n = len(all_chunks)
    confidence = min(0.95, 0.5 + n * 0.05) if n > 0 else 0.3
    evaluation = {
        "passed": True,
        "confidence": confidence,
        "completeness": min(1.0, n / 8),
        "consistency": 0.85,
        "information_gain": 0.8,
        "source_diversity": min(1.0, len({c.get("source", "") for c in all_chunks}) / 3),
        "fact_consistency": 0.85,
        "coverage_estimate": min(1.0, n / 5),
        "feedback": "ok",
    }

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
                                         ↓ (all steps done or max iter)
                                    synthesize_node → END
    """
    g = StateGraph(RAGAgentState)

    g.add_node("query_analysis", query_analysis_node)
    g.add_node("planner_node", planner_node)
    g.add_node("executor_node", executor_node)
    g.add_node("tool_node", tool_node)
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

    g.add_edge("tool_node", "executor_node")
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
