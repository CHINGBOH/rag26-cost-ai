from app.agent.graph import _build_presentation_payload


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
