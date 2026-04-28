import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.query_analyzer import (
    QueryAnalyzer,
    extract_fee_standard_comparison_queries,
    extract_fill_requirement_search_term,
    is_appendix_standard_query,
    is_fee_standard_comparison_query,
)


def test_query_analyzer_routes_fee_formula_to_standard_ref() -> None:
    analysis = QueryAnalyzer().analyze("2025版费率标准中企业管理费的计算公式是什么？")

    assert analysis["intent"] == "standard_ref"
    assert analysis["entities"]["year_month"] == "2025"


def test_query_analyzer_routes_fee_range_comparison_to_comparison() -> None:
    query = "2023版与2025版费率标准中，利润率的参考范围是否一致？"

    analysis = QueryAnalyzer().analyze(query)

    assert analysis["intent"] == "comparison"
    assert is_fee_standard_comparison_query(query) is True
    assert extract_fee_standard_comparison_queries(query) == ["2023 利润率 参考范围", "2025 利润率 参考范围"]


def test_query_analyzer_routes_monthly_material_price_to_price() -> None:
    analysis = QueryAnalyzer().analyze("2026年1月，中砂的价格是多少元/m³？")

    assert analysis["intent"] == "price"
    assert analysis["entities"]["year_month"] == "2026-01"
    assert analysis["entities"]["material_name"] == "中砂"


def test_query_analyzer_routes_trend_question_to_trend_chart() -> None:
    analysis = QueryAnalyzer().analyze("中砂从2026年1月到2月的价格走势如何？")

    assert analysis["intent"] == "trend_chart"


def test_query_analyzer_decomposes_multi_material_month_over_month_price_change() -> None:
    analysis = QueryAnalyzer().analyze("2026年1月，电线、电缆价格较上月的变化幅度是多少？")

    assert analysis["intent"] == "trend_chart"
    assert analysis["entities"]["year_month"] == "2026-01"
    assert analysis["entities"]["material_names"] == ["电线", "电缆"]
    assert "2025-12 电线 价格" in analysis["sub_queries"]
    assert "2026-01 电缆 价格" in analysis["sub_queries"]
    assert "计算 电线 2026-01 较 2025-12 变化幅度" in analysis["sub_queries"]


def test_query_analyzer_extracts_fill_requirement_field() -> None:
    query = "工程概况表中的施工地点应按什么要求填写？"

    analysis = QueryAnalyzer().analyze(query)

    assert analysis["intent"] == "standard_ref"
    assert extract_fill_requirement_search_term(query) == "施工地点"


def test_query_analyzer_detects_appendix_standard_query() -> None:
    query = "《深圳市装配式建筑评价标准》适用范围是什么？"

    assert is_appendix_standard_query(query) is True


def test_query_analyzer_ignores_question_prefix_and_extracts_cable_spec() -> None:
    analysis = QueryAnalyzer().analyze(
        "03. 对比深圳市2025年12月和2023年12月工程建设信息价中，电力电缆规格型号为0.6/1KV YJV 5×120的价格差异"
    )

    assert analysis["intent"] == "comparison"
    assert analysis["entities"]["material_name"] == "电力电缆"
    assert analysis["entities"]["specification"] == "0.6/1KV YJV 5×120"


def test_query_analyzer_extracts_compound_trend_material_and_shorthand_year() -> None:
    analysis = QueryAnalyzer().analyze("04. 根据深圳信息价分析下从25年开始至今的装配式混凝土预制构件价格走势")

    assert analysis["intent"] == "trend_chart"
    assert analysis["entities"]["year_month"] == "2025"
    assert analysis["entities"]["material_name"] == "装配式混凝土预制构件"
