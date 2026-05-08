"""Tests for DecisionLogger observability layer — #115."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.observability import Decision, DecisionLogger, DecisionType, log_decision


def setup_function():
    DecisionLogger.clear_buffer()


def teardown_function():
    DecisionLogger.clear_buffer()


# ─── Decision model ───────────────────────────────────────────────────────────

def test_decision_has_id():
    d = Decision(
        decision_type=DecisionType.TOOL_SELECTION,
        context={"query": "test"},
        params_used={},
        outcome="price_query",
        reason="test",
    )
    assert d.decision_id


def test_decision_to_dict():
    d = Decision(
        decision_type=DecisionType.TOOL_SELECTION,
        context={"query": "test"},
        params_used={"top_k": 5},
        outcome="price_query",
        reason="contains material name",
    )
    result = d.to_dict()
    assert result["decision_type"] == DecisionType.TOOL_SELECTION
    assert result["outcome"] == "price_query"
    assert result["reason"] == "contains material name"


def test_decision_to_json_is_string():
    d = Decision(
        decision_type=DecisionType.FOLLOWUP_FILTER,
        context={"question": "Q?", "coverage": 0.45},
        params_used={},
        outcome="rejected",
        reason="below threshold",
    )
    js = d.to_json()
    assert isinstance(js, str)
    assert "followup" in js.lower() or "FOLLOWUP" in js


# ─── DecisionLogger.log ───────────────────────────────────────────────────────

def test_log_adds_to_buffer():
    before = len(DecisionLogger.query())
    DecisionLogger.log(Decision(
        decision_type=DecisionType.TOOL_SELECTION,
        context={},
        params_used={},
        outcome="text_search",
        reason="fallback",
    ))
    after = len(DecisionLogger.query())
    assert after == before + 1


def test_log_multiple_decisions():
    for i in range(3):
        DecisionLogger.log(Decision(
            decision_type=DecisionType.FOLLOWUP_FILTER,
            context={"idx": i},
            params_used={},
            outcome="accepted" if i % 2 == 0 else "rejected",
            reason="test",
        ))
    results = DecisionLogger.query()
    assert len(results) >= 3


# ─── Query / filter ───────────────────────────────────────────────────────────

def test_query_by_decision_type():
    DecisionLogger.log(Decision(
        decision_type=DecisionType.TOOL_SELECTION,
        context={},
        params_used={},
        outcome="price_query",
        reason="test",
    ))
    DecisionLogger.log(Decision(
        decision_type=DecisionType.FOLLOWUP_FILTER,
        context={},
        params_used={},
        outcome="accepted",
        reason="test",
    ))
    tool_results = DecisionLogger.query(decision_type=DecisionType.TOOL_SELECTION)
    assert all(r.decision_type == DecisionType.TOOL_SELECTION for r in tool_results)


# ─── Stats ────────────────────────────────────────────────────────────────────

def test_get_stats_returns_dict():
    stats = DecisionLogger.get_stats()
    assert isinstance(stats, dict)


# ─── log_decision convenience function ───────────────────────────────────────

def test_log_decision_function():
    before = len(DecisionLogger.query())
    log_decision(
        decision_type="knowledge_gap_retest",
        context={"gap_id": "g123"},
        outcome="scheduled",
        reason="timer trigger",
        params_used={"retest_interval": 86400},
    )
    assert len(DecisionLogger.query()) == before + 1


# ─── DecisionType enum ───────────────────────────────────────────────────────

def test_decision_type_enum_values():
    assert DecisionType.TOOL_SELECTION
    assert DecisionType.FOLLOWUP_FILTER
    assert DecisionType.LEARNING_RETEST
