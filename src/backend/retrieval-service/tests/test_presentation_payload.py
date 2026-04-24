from app.agent.graph import (
    _build_presentation_payload,
    finalize_presentation_payload,
    refine_citations_for_answer,
)


def test_build_comparison_presentation_groups_same_month_rows():
    chunks = [
        {
            "content": "电力电缆 0.6/1KV YJV 5×120 单位:m 价格:605.73元 期间:2025-12 类别:电缆",
            "doc_filename": "深圳市2025年12月工程建设信息价.pdf",
            "page_number": 36,
            "metadata": {"unit": "m"},
        },
        {
            "content": "电力电缆 0.6/1KV YJV 5×120 单位:m 价格:609.82元 期间:2025-12 类别:电缆",
            "doc_filename": "深圳市2025年12月工程建设信息价.pdf",
            "page_number": 37,
            "metadata": {"unit": "m"},
        },
        {
            "content": "电力电缆 0.6/1KV YJV 5×120 单位:m 价格:488.98元 期间:2023-12 类别:电缆",
            "doc_filename": "深圳市2023年12月工程建设信息价.pdf",
            "page_number": 27,
            "metadata": {"unit": "m"},
        },
    ]

    presentation = _build_presentation_payload(
        "对比深圳市2025年12月和2023年12月工程建设信息价中，电力电缆规格型号为0.6/1KV YJV 5×120的价格差异",
        "comparison",
        chunks,
    )

    assert presentation is not None
    assert presentation["type"] == "price_comparison"
    assert [point["label"] for point in presentation["points"]] == ["2023-12", "2025-12"]
    assert presentation["points"][1]["count"] == 2
    assert presentation["points"][1]["min_value"] == 605.73
    assert presentation["points"][1]["max_value"] == 609.82
    assert presentation["delta"] > 0


def test_build_trend_presentation_from_trend_chunks():
    chunks = [
        {
            "content": "中砂 价格走势 期间:2025-10 均价:180.00元/m³",
            "metadata": {"year_month": "2025-10", "avg_price": 180.0, "unit": "m³"},
        },
        {
            "content": "中砂 价格走势 期间:2025-11 均价:185.00元/m³",
            "metadata": {"year_month": "2025-11", "avg_price": 185.0, "unit": "m³"},
        },
        {
            "content": "中砂 价格走势 期间:2025-12 均价:192.00元/m³",
            "metadata": {"year_month": "2025-12", "avg_price": 192.0, "unit": "m³"},
        },
    ]

    presentation = _build_presentation_payload("中砂从2025年10月到12月的价格走势", "trend_chart", chunks)

    assert presentation is not None
    assert presentation["type"] == "price_trend"
    assert len(presentation["points"]) == 3
    assert presentation["delta"] == 12.0
    assert presentation["delta_percent"] == 6.67


def test_refine_citations_keeps_only_explicit_references():
    chunks = [
        {"doc_filename": "第二册电气设备安装工程.pdf", "page_number": 314, "content": "10.1.7"},
        {"doc_filename": "第二册电气设备安装工程.pdf", "page_number": 327, "content": "系统调试"},
        {"doc_filename": "第二册电气设备安装工程.pdf", "page_number": 9, "content": "目录"},
    ]
    citations_text = (
        "参考索引：\n"
        "[1] 《第二册电气设备安装工程》第 9 页\n"
        "[2] 《第二册电气设备安装工程》第 314 页\n"
        "[3] 《第二册电气设备安装工程》第 327 页"
    )
    answer = (
        "送配电装置系统调试适用于10kV以下送配电回路【《第二册电气设备安装工程》P314】。"
        "计量单位按系统计算【《第二册电气设备安装工程》P327】。"
    )

    refined = refine_citations_for_answer(answer, chunks, citations_text)

    assert "第 314 页" in refined
    assert "第 327 页" in refined
    assert "第 9 页" not in refined


def test_finalize_presentation_builds_answer_sections_for_rule_query():
    chunks = [
        {"doc_filename": "第二册电气设备安装工程.pdf", "page_number": 314, "content": "适用于10kV以下送配电回路"},
        {"doc_filename": "第二册电气设备安装工程.pdf", "page_number": 327, "content": "按系统为单位计算"},
    ]
    final_answer = (
        "送配电装置系统调试适用于10kV以下送配电回路，按系统计算，不包括配电箱至电动机回路。"
        "\n\n简要分析：\n"
        "核心规则来自10.1.7条，明确了适用范围、排除项和调试内容。"
        "\n\n参考索引：\n"
        "[1] 《第二册电气设备安装工程》第 314 页\n"
        "[2] 《第二册电气设备安装工程》第 327 页"
    )
    citations_text = (
        "参考索引：\n"
        "[1] 《第二册电气设备安装工程》第 314 页\n"
        "[2] 《第二册电气设备安装工程》第 327 页"
    )

    presentation = finalize_presentation_payload(
        query="安装工程消耗量标准中送配电装置系统调试的计算规则是什么?",
        query_type="standard_ref",
        final_answer=final_answer,
        chunks=chunks,
        citations_text=citations_text,
        existing_presentation=None,
    )

    assert presentation is not None
    assert presentation["type"] == "answer_sections"
    assert presentation["title"] == "规则说明"
    assert presentation["summary"].startswith("送配电装置系统调试适用于10kV以下")
    assert len(presentation["highlights"]) >= 2
    assert presentation["sources"][0]["page"] == "314"
