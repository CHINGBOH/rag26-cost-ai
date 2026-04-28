import sys

import pytest

sys.path.insert(0, "src/backend/retrieval-service")

from app.agent import graph


def test_build_forced_fee_tool_calls_for_profit_query() -> None:
    state = {
        "query": "某工程人工费100万、材料费200万、机械费50万、企业管理费按推荐费率计算，按2025版推荐利润率计算，利润为多少？",
        "query_type": "calculation",
        "query_entities": {"year_month": "2025"},
        "retrieved_chunks": [],
    }

    tool_calls = graph._build_forced_fee_tool_calls(state)

    assert len(tool_calls) == 2
    assert {tool_call["name"] for tool_call in tool_calls} == {"text_search"}
    queries = {tool_call["args"]["query"] for tool_call in tool_calls}
    assert queries == {"2025 企业管理费 推荐费率", "2025 利润 推荐费率"}


def test_rule_based_fallback_calculates_profit_from_fee_rate_chunks() -> None:
    query = "某工程人工费100万、材料费200万、机械费50万、企业管理费按推荐费率计算，按2025版推荐利润率计算，利润为多少？"
    chunks = [
        {
            "chunk_id": "tc_24_1",
            "doc_filename": "深圳市建设工程计价费率标准（2025）.pdf",
            "page_number": 1,
            "content": "【2025版费率标准】企业管理费（企业管理费）\n费率参考范围：14%～26%，推荐费率：20.44%（单位：%，使用时÷100）\n计算公式：企业管理费＝（人工费+机械费×0.1）×企业管理费费率\n【2025版费率标准】利润（利润）\n费率参考范围：3%～7%，推荐费率：5%（单位：%，使用时÷100）\n计算公式：利润＝（人工费+材料费+机械费+企业管理费）×利润率",
        }
    ]

    answer = graph._build_rule_based_fallback_answer(query, chunks)

    assert "18.57万元" in answer
    assert "20.44%" in answer
    assert "5.00%" in answer
    assert "企业管理费＝（100.00＋50.00×0.1）×20.44%＝21.4620万元" in answer


def test_after_synthesize_skips_contract_verifier_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAG_ENABLE_CONTRACT_VERIFIER_LOOP", raising=False)

    assert graph.after_synthesize({}) == "presentation_policy_node"


def test_after_synthesize_allows_contract_verifier_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_ENABLE_CONTRACT_VERIFIER_LOOP", "1")

    assert graph.after_synthesize({}) == "contract_verifier_node"


def test_build_forced_standard_ref_tool_calls_for_tax_query() -> None:
    state = {
        "query": "一般计税方法下，税前工程造价中的费用是否包含进项税额？",
        "query_type": "standard_ref",
        "retrieved_chunks": [],
    }

    tool_calls = graph._build_forced_standard_ref_tool_calls(state)

    assert len(tool_calls) == 2
    assert {tool_call["name"] for tool_call in tool_calls} == {"text_search"}
    queries = {tool_call["args"]["query"] for tool_call in tool_calls}
    assert queries == {
        "2025 一般计税方法 税前工程造价 进项税额",
        "2025 简易计税方法 税前工程造价 进项税额",
    }


def test_build_forced_standard_ref_tool_calls_for_safety_fee_query() -> None:
    state = {
        "query": "详细说明深圳市工程建设地方标准中，关于安全文明施工费的组成内容、计算基数以及计取规定",
        "query_type": "standard_ref",
        "retrieved_chunks": [],
    }

    tool_calls = graph._build_forced_standard_ref_tool_calls(state)

    assert len(tool_calls) == 2
    assert {tool_call["name"] for tool_call in tool_calls} == {"text_search"}
    queries = {tool_call["args"]["query"] for tool_call in tool_calls}
    assert queries == {
        "2025 安全文明施工费 组成 计算基数 计取",
        "2025 安全文明施工费费率部分 计算公式 计算基数 推荐费率",
    }


def test_build_forced_glass_floor_tool_calls_for_quota_price_query() -> None:
    state = {
        "query": "25版装饰工程消耗量标准中，楼梯面层中玻璃地板的人工费是多少？",
        "query_type": "standard_ref",
        "retrieved_chunks": [],
    }

    tool_calls = graph._build_forced_glass_floor_tool_calls(state)

    assert len(tool_calls) == 1
    assert tool_calls[0]["name"] == "rule_clause_search"
    assert tool_calls[0]["args"] == {
        "query": "玻璃地板",
        "doc_id": "",
        "doc_filename": "装饰工程消耗量标准",
        "section": "",
        "page_start": 0,
        "page_end": 0,
        "top_k": 4,
    }


def test_rule_based_fallback_answers_glass_floor_labor_prices() -> None:
    query = "25版装饰工程消耗量标准中，楼梯面层中玻璃地板的人工费是多少？"
    chunks = [
        {
            "chunk_id": "tc_glass_floor",
            "doc_filename": "装饰工程消耗量标准.pdf",
            "page_number": 101,
            "content": (
                "（5）玻璃地板 工作内容：清理基层、试排弹线、铺贴饰面、清理净面等。 单位：100m² "
                "楼地面单层钢化玻璃 楼地面钢化夹层玻璃 人工费 元 4653.50 4705.51 4395.13 4485.69"
            ),
        }
    ]

    answer = graph._build_rule_based_fallback_answer(query, chunks)

    assert "4653.50元/100m²" in answer
    assert "4705.51元/100m²" in answer
    assert "4395.13元/100m²" in answer
    assert "4485.69元/100m²" in answer
    assert "楼梯、台阶面层计价规定另行调整" in answer


def test_placeholder_reference_text_is_not_marked_as_refusal() -> None:
    answer = "根据当前证据给出结论。\n\n参考索引：\n[1] 暂无可用来源"

    assert graph._looks_like_refusal_answer(answer) is False