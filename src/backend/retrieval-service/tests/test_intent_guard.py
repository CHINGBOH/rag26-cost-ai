import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import app.agent.graph as graph_module


def test_resolve_guarded_intent_prefers_llm_high_confidence() -> None:
    result = graph_module._resolve_guarded_intent(
        query="按2025版标准，如果机械费为0，企业管理费的计算基数是什么？",
        current_intent="price",
        decision={"intent": "standard_ref", "confidence": 0.92},
    )
    assert result == "standard_ref"


def test_resolve_guarded_intent_accepts_low_confidence_on_fee_rule_boundary() -> None:
    result = graph_module._resolve_guarded_intent(
        query="按2025版标准，如果机械费为0，企业管理费的计算基数是什么？",
        current_intent="price",
        decision={"intent": "standard_ref", "confidence": 0.31},
    )
    assert result == "standard_ref"


def test_resolve_guarded_intent_keeps_price_for_plain_material_query() -> None:
    result = graph_module._resolve_guarded_intent(
        query="2026年1月，中砂的价格是多少元/m³？",
        current_intent="price",
        decision={"intent": "standard_ref", "confidence": 0.2},
    )
    assert result == "price"


def test_intent_guard_node_fallbacks_to_standard_ref_when_llm_unavailable(monkeypatch) -> None:
    def _raise(*args, **kwargs):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(graph_module, "invoke_llm", _raise)
    state = {
        "query": "按2025版标准，如果机械费为0，企业管理费的计算基数是什么？",
        "query_type": "price",
        "query_entities": {"year_month": "2025"},
        "llm_config": {},
        "llm_runtime": {},
    }

    result = graph_module.intent_guard_node(state)
    assert result["query_type"] == "standard_ref"


def test_planner_uses_fee_rule_override_for_standard_ref_boundary_query(monkeypatch) -> None:
    class _Resp:
        content = '{"steps":["先做通用检索"]}'

    def _fake_invoke(*args, **kwargs):
        return _Resp(), {"provider": "mock"}

    monkeypatch.setattr(graph_module, "invoke_llm", _fake_invoke)
    state = {
        "query": "按2025版标准，如果机械费为0，企业管理费的计算基数是什么？",
        "query_type": "standard_ref",
        "query_entities": {"year_month": "2025"},
        "llm_config": {},
    }

    result = graph_module.planner_node(state)
    assert "text_search" in result["plan"][0]
    assert "2025 企业管理费 计算公式" in result["plan"][0]


def test_executor_fallback_tool_call_targets_fee_formula_for_standard_ref() -> None:
    state = {
        "query": "按2025版标准，如果机械费为0，企业管理费的计算基数是什么？",
        "query_type": "standard_ref",
        "query_entities": {"year_month": "2025"},
    }

    tool_call = graph_module._build_executor_fallback_tool_call(state)
    assert tool_call is not None
    assert tool_call["name"] == "text_search"
    assert "2025 企业管理费 计算公式" in tool_call["args"]["query"]


def test_rule_based_fallback_answer_returns_manual_conclusion_for_zero_machine_cost() -> None:
    chunks = [
        {
            "doc_filename": "深圳市建设工程计价费率标准（2025）.pdf",
            "page_number": 1,
            "content": "企业管理费＝（人工费＋机械费×0.1）×企业管理费费率",
        }
    ]
    answer = graph_module._build_rule_based_fallback_answer(
        "按2025版标准，如果机械费为0，企业管理费的计算基数是什么？",
        chunks,
    )

    assert "计算基数为人工费" in answer
    assert "P1" in answer
