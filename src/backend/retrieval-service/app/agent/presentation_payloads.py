import ast
import re

from app.agent.prompts import _strip_think_tags
from app.agent.query_analyzer import (
    QueryAnalyzer,
    extract_appendix_standard_terms,
    extract_appendix_standard_title,
    is_appendix_standard_query,
)

_INTERNAL_SOURCES = {"智能体问答", "agent_qa", "eval_qa"}
_analyzer = QueryAnalyzer()


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
        return chunks

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


def _format_citations(chunks: list, allowed_refs: set[tuple[str, str]] | None = None) -> str:
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


_SECTION_LABEL_BY_QUERY_TYPE: dict[str, dict[str, str]] = {
    "standard_ref": {"analysis": "依据说明", "detail": "适用边界"},
    "price": {"analysis": "价格解析", "detail": "数据说明"},
    "trend_chart": {"analysis": "走势分析", "detail": "数据说明"},
    "fee_rate": {"analysis": "费率解析", "detail": "计算依据"},
    "formula": {"analysis": "公式推导", "detail": "计算说明"},
    "comparison": {"analysis": "对比分析", "detail": "数据限制"},
}

_SECTION_BODY_KEYWORDS: list[tuple[list[str], str]] = [
    (["公式", "计算", "算式", "＝", "=", "推导"], "公式推导"),
    (["适用", "范围", "不适用", "仅适用", "情形"], "适用边界"),
    (["注意", "注：", "说明", "限制", "限定", "不含"], "数据限制"),
    (["来源", "依据", "参见", "详见", "规定"], "依据说明"),
    (["对比", "比较", "差异", "增加", "减少", "变化"], "对比分析"),
]


def _derive_section_label(kind: str, query_type: str, body: str) -> str:
    """Derive a semantic label for an answer section, preferring query-type-aware labels."""
    # 1. Try keyword-based label from body
    body_lower = body[:120]
    for keywords, label in _SECTION_BODY_KEYWORDS:
        if any(kw in body_lower for kw in keywords):
            return label
    # 2. Fall back to query_type mapping
    qt_map = _SECTION_LABEL_BY_QUERY_TYPE.get(query_type, {})
    return qt_map.get(kind, "核心说明" if kind == "analysis" else "补充说明")


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
        {
            "kind": "analysis" if idx == 0 else "detail",
            "body": paragraph,
            "label": _derive_section_label(
                "analysis" if idx == 0 else "detail", query_type, paragraph
            ),
        }
        for idx, paragraph in enumerate(analysis_paragraphs[:2])
    ]
    sources = _parse_citation_items(citations_text)[:4]

    note = None
    if len(query) <= 28:
        note = query

    support_label = _derive_section_label("detail", query_type, analysis_text)

    return {
        "type": "answer_sections",
        "query_type": query_type,
        "title": _build_answer_title(query_type),
        "note": note,
        "summary": _build_summary_text(query_type, direct_answer),
        "highlights": highlights,
        "sections": sections,
        "sources": sources,
        "support_label": support_label,
    }


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
    for sentence in candidate_sentences:
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

    return {
        "type": "calculation_steps",
        "title": "计算沙箱",
        "note": query if len(query) <= 40 else None,
        "summary": _build_summary_text("calculation", direct_answer),
        "highlights": _build_highlights("calculation", direct_answer, analysis_text),
        "steps": steps,
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
    answer = _clean_markdown_noise(_strip_think_tags(answer))
    refs = _normalize_reference_section(citations_text)
    answer_without_refs = re.split(r"\n\s*(?:【参考索引】|参考索引[:：])", answer, maxsplit=1)[0].strip()
    answer_without_refs = re.sub(r"(?m)^\s*第[一二三四五六七八九十]段[:：]\s*", "", answer_without_refs)
    answer_without_refs = re.sub(r"(?m)^\s*参考索引[:：]\s*\[1\]\s*暂无可用来源[。.]?\s*$", "", answer_without_refs)
    answer_without_refs = answer_without_refs.strip()

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

    # Only inject "简要分析：" prefix when the answer doesn't already have natural structure.
    # "Natural structure" = multiple non-trivial paragraphs or existing labelled sections.
    has_natural_structure = (
        len([p for p in re.split(r"\n\s*\n", analysis_text) if len(p.strip()) > 20]) >= 2
        or re.search(r"(?m)^[①②③④⑤\-•]\s", analysis_text)
        or re.search(r"(?m)^[一二三四五六七八九十]\s*[、.．]", analysis_text)
        or re.search(r"(?m)^\d+[.．、]\s", analysis_text)
    )

    if analysis_text and not has_natural_structure:
        body = f"{direct_answer}\n\n简要分析：\n{analysis_text}"
    elif analysis_text:
        body = f"{direct_answer}\n\n{analysis_text}"
    else:
        body = direct_answer

    return f"{body}\n\n{refs}".strip()