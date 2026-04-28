"""Integration tests for the iterative convergence outer loop (Phase 2-3).

End-to-end scenarios exercising contract_verifier → corrective_action → replay.
No real LLM or DB calls — all state is constructed to test routing logic.
"""
import sys
import pytest

sys.path.insert(0, "src/backend/retrieval-service")

from app.agent.graph import (
    contract_verifier_node,
    corrective_action_node,
    after_contract_verifier,
    after_corrective_action,
    trace_root_cause,
    verify_query_analysis_contract,
    verify_navigator_contract,
    verify_tool_contract,
    verify_synthesize_contract,
)


def _base_state(query_type="price", **overrides):
    """Minimal valid state that passes all contracts."""
    s = {
        "query": "深圳2025-12 C30商品混凝土信息价",
        "query_type": query_type,
        "query_entities": {"material_name": "商品混凝土", "year_month": "2025-12"},
        "roadmap": [],
        "retrieved_chunks": [
            {"source_db": "price_query", "content": "C30 520元/m³", "metadata": {"price_tax_included": 520}},
        ],
        "evaluation": None,
        "final_answer": "",
        "fallback_mode": False,
        "outer_iteration": 0,
        "max_outer_iterations": 3,
        "contract_results": [],
        "corrective_actions": [],
        "llm_config": {},
        "used_tool_categories": [],
        "tool_fallback_level": 0,
        "has_tool_calls": False,
        "messages": [],
    }
    s.update(overrides)
    return s


# ── Scenario 1: Normal golden path ────────────────────────────────────────────


def test_normal_path_all_contracts_pass():
    """A well-formed price query should pass all 4 contracts in a single pass."""
    state = _base_state(
        evaluation={"passed": True, "feedback": "ok", "confidence": 0.9},
        final_answer="2025年12月深圳市C30商品混凝土信息价为520元/m³",
    )
    result = contract_verifier_node(state)

    assert result["quality_converged"] is True
    assert all(cr["passed"] for cr in result["contract_results"])
    assert after_contract_verifier({**state, **result}) == "presentation_policy_node"


# ── Scenario 2: Missing material → LLM extraction replay ──────────────────────


def test_missing_material_replay_loop():
    """When query_analysis fails to extract material, corrective action should
    attempt LLM re-extraction and replay from query_analysis."""
    state = _base_state(
        query_entities={},  # missing material and year_month
        evaluation={"passed": True, "feedback": "ok"},
        final_answer="2025年12月信息价为520元/m³",
    )

    # Step 1: contract_verifier detects failures
    cv_result = contract_verifier_node(state)
    assert cv_result["quality_converged"] is False
    assert cv_result["root_cause_node"] == "query_analysis"
    assert cv_result["outer_iteration"] == 1

    # Step 2: route to corrective_action
    assert after_contract_verifier({**state, **cv_result}) == "corrective_action_node"

    # Step 3: corrective_action dispatches (note: _llm_extract_material needs real LLM,
    # so in test context material extraction may not fire; other violations still dispatch)
    ca_result = corrective_action_node({**state, **cv_result})
    # Without real LLM, the material/year_month inject may not fire, but other
    # violations (zero_results, eval_not_passed) still dispatch corrective actions.
    assert len(ca_result["corrective_actions"]) > 0
    assert ca_result["retrieved_chunks"] == []
    assert ca_result["evaluation"] is None

    # Step 4: route back to query_analysis for replay
    assert after_corrective_action({**state, **ca_result}) == "query_analysis"


# ── Scenario 3: Zero results → fallback → escalation ──────────────────────────


def test_zero_results_fallback_escalation():
    """Zero retrieval results should trigger fallback, then escalation."""
    state = _base_state(
        query_type="semantic",
        query="防火涂料施工规范",
        query_entities={},
        retrieved_chunks=[],
        roadmap=[{
            "chapter_id": "5.1", "path": "test/5.1", "file_name": "test.pdf",
            "title": "防火涂料", "reason": "relevant",
        }],
        evaluation={"passed": False, "feedback": "insufficient_evidence"},
        final_answer="未找到相关信息",
    )

    # Round 1: should fail on tool_node (zero results)
    cv1 = contract_verifier_node(state)
    assert cv1["quality_converged"] is False
    assert not any(cr["passed"] and cr["node"] == "tool_node" for cr in cv1["contract_results"])
    assert cv1["outer_iteration"] == 1

    # Round 1 corrective: enables fallback_mode
    ca1 = corrective_action_node({**state, **cv1})
    assert "enable_fallback" in ca1["corrective_actions"]

    # Simulate replay (fallback mode, still zero results)
    state_r2 = {**state, **ca1, "outer_iteration": 1, "contract_results": cv1["contract_results"]}
    cv2 = contract_verifier_node(state_r2)
    # Should now show zero_results_after_fallback
    tool_cr = next(cr for cr in cv2["contract_results"] if cr["node"] == "tool_node")
    assert not tool_cr["passed"]

    # Round 2 corrective: escalates fallback level + expands aliases
    ca2 = corrective_action_node({**state_r2, **cv2})
    assert any("escalate_fallback" in a for a in ca2["corrective_actions"])


# ── Scenario 4: Max iteration hard stop ───────────────────────────────────────


def test_max_iterations_forces_output():
    """At outer_iteration >= max_outer_iterations, MUST converge regardless of failures."""
    state = _base_state(
        query_entities={},
        retrieved_chunks=[],
        evaluation={"passed": False, "feedback": "insufficient_evidence"},
        final_answer="",
        outer_iteration=3,
        max_outer_iterations=3,
    )

    result = contract_verifier_node(state)
    assert result["quality_converged"] is True  # forced
    assert after_contract_verifier({**state, **result}) == "presentation_policy_node"


# ── Scenario 5: Source conflict → annotation ──────────────────────────────────


def test_source_conflict_annotation():
    """High price CV should trigger conflict annotation in corrective action."""
    state = _base_state(
        evaluation={"passed": True, "feedback": "ok"},
        final_answer="C30混凝土价格为500元/m³",
        retrieved_chunks=[
            {"source_db": "price_query", "metadata": {"price_tax_included": 300}},
            {"source_db": "text_search", "metadata": {"price_tax_included": 700}},
        ],
    )

    cv = contract_verifier_node(state)
    assert cv["quality_converged"] is False
    syn_cr = next(cr for cr in cv["contract_results"] if cr["node"] == "synthesize_node")
    assert any(v[0] == "source_conflict" for v in syn_cr["violations"])

    ca = corrective_action_node({**state, **cv})
    assert "annotate_source_conflict" in ca["corrective_actions"]


# ── Scenario 6: Empty roadmap for calculation query ───────────────────────────


def test_empty_roadmap_replay_navigator():
    """Semantic/calculation queries with empty roadmap should replay navigator."""
    state = _base_state(
        query_type="calculation",
        query="土方工程量计算",
        query_entities={},
        roadmap=[],
        evaluation={"passed": False, "feedback": "insufficient_evidence"},
    )

    cv = contract_verifier_node(state)
    assert cv["quality_converged"] is False
    assert cv["root_cause_node"] == "navigator_node"

    ca = corrective_action_node({**state, **cv})
    assert "expand_navigator_keywords" in ca["corrective_actions"]
    # root_cause_node is set by contract_verifier_node, must carry it through
    assert after_corrective_action({**state, **cv, **ca}) == "navigator_node"


# ── Scenario 7: Corrective action dedup ───────────────────────────────────────


def test_corrective_actions_accumulate_no_duplicates():
    """Actions should accumulate across iterations without full duplicates."""
    state = _base_state(
        query_entities={},
        retrieved_chunks=[],
        evaluation={"passed": False, "feedback": "insufficient_evidence"},
        corrective_actions=["enable_fallback"],
        outer_iteration=1,
        fallback_mode=True,
    )

    cv = contract_verifier_node(state)
    # Should now have zero_results_after_fallback
    ca = corrective_action_node({**state, **cv})
    # Should include both actions
    actions = ca["corrective_actions"]
    assert "enable_fallback" in actions  # from prior round
    assert any("escalate_fallback" in a for a in actions)  # new
    assert "force_drilldown" in actions


# ── Scenario 8: price_query forced when no_price_number ───────────────────────


def test_no_price_number_forces_price_query():
    """When answer has no price number, corrective action should force price_query."""
    state = _base_state(
        evaluation={"passed": True, "feedback": "ok"},
        final_answer="该材料暂无价格数据，请联系供应商确认。",
        retrieved_chunks=[
            {"source_db": "hybrid_search", "content": "no price data", "metadata": {}},
        ],
    )

    cv = contract_verifier_node(state)
    syn_cr = next(cr for cr in cv["contract_results"] if cr["node"] == "synthesize_node")
    assert any(v[0] == "no_price_number" for v in syn_cr["violations"])

    ca = corrective_action_node({**state, **cv})
    assert "force_price_query" in ca["corrective_actions"]
    assert "price_query" in ca["used_tool_categories"]
