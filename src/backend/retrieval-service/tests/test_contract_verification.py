"""Unit tests for node contract verification functions (Phase 1-2).

Covers C1-C4 contracts: pass, fail, and edge case scenarios.
"""
import sys
import pytest

# Ensure retrieval-service is on path
sys.path.insert(0, "src/backend/retrieval-service")

from app.agent.graph import (
    verify_query_analysis_contract,
    verify_navigator_contract,
    verify_tool_contract,
    verify_synthesize_contract,
    trace_root_cause,
    _compute_price_cv_from_chunks,
)


# ── C1: query_analysis ────────────────────────────────────────────────────────


class TestQueryAnalysisContract:
    def test_valid_price_query(self):
        cr = verify_query_analysis_contract({
            "query_type": "price",
            "query_entities": {"material_name": "商品混凝土", "year_month": "2025-12"},
        })
        assert cr["passed"]
        assert cr["violations"] == []

    def test_valid_semantic_query(self):
        cr = verify_query_analysis_contract({
            "query_type": "semantic",
            "query_entities": {},
        })
        assert cr["passed"]

    @pytest.mark.parametrize("qt", ["price", "semantic", "calculation", "comparison", "trend_chart", "standard_ref"])
    def test_all_valid_query_types(self, qt):
        entities = {"material_name": "水泥", "year_month": "2025-01"} if qt in ("price", "trend_chart") else {}
        cr = verify_query_analysis_contract({"query_type": qt, "query_entities": entities})
        assert cr["passed"]

    def test_invalid_query_type(self):
        cr = verify_query_analysis_contract({"query_type": "unknown_xyz", "query_entities": {}})
        assert not cr["passed"]
        assert any(v[0] == "invalid_intent" for v in cr["violations"])

    def test_price_missing_material(self):
        cr = verify_query_analysis_contract({"query_type": "price", "query_entities": {}})
        assert not cr["passed"]
        assert any(v[0] == "missing_material" for v in cr["violations"])

    def test_price_missing_year_month(self):
        cr = verify_query_analysis_contract({
            "query_type": "price",
            "query_entities": {"material_name": "水泥"},
        })
        assert not cr["passed"]
        assert any(v[0] == "missing_year_month" for v in cr["violations"])

    def test_both_missing(self):
        cr = verify_query_analysis_contract({"query_type": "price", "query_entities": {}})
        assert not cr["passed"]
        codes = {v[0] for v in cr["violations"]}
        assert "missing_material" in codes
        assert "missing_year_month" in codes


# ── C2: navigator ─────────────────────────────────────────────────────────────


class TestNavigatorContract:
    def test_price_query_skips_navigator(self):
        """Navigator is not required for price/trend queries."""
        cr = verify_navigator_contract({"query_type": "price", "roadmap": []})
        assert cr["passed"]

    def test_trend_chart_skips_navigator(self):
        cr = verify_navigator_contract({"query_type": "trend_chart", "roadmap": []})
        assert cr["passed"]

    def test_semantic_with_roadmap(self):
        cr = verify_navigator_contract({
            "query_type": "semantic",
            "roadmap": [{"chapter_id": "10.2", "path": "test/10.2", "file_name": "test.pdf", "title": "test", "reason": "relevant"}],
        })
        assert cr["passed"]

    def test_semantic_empty_roadmap(self):
        cr = verify_navigator_contract({"query_type": "semantic", "roadmap": []})
        assert not cr["passed"]
        assert any(v[0] == "empty_roadmap" for v in cr["violations"])

    def test_calculation_empty_roadmap(self):
        cr = verify_navigator_contract({"query_type": "calculation", "roadmap": []})
        assert not cr["passed"]


# ── C3: tool_node ─────────────────────────────────────────────────────────────


class TestToolContract:
    def test_usable_chunks(self):
        cr = verify_tool_contract({
            "retrieved_chunks": [{"source_db": "hybrid_search", "content": "test"}],
            "fallback_mode": False,
        })
        assert cr["passed"]

    def test_zero_results(self):
        cr = verify_tool_contract({"retrieved_chunks": [], "fallback_mode": False})
        assert not cr["passed"]
        assert any(v[0] == "zero_results" for v in cr["violations"])

    def test_zero_results_after_fallback(self):
        cr = verify_tool_contract({"retrieved_chunks": [], "fallback_mode": True})
        assert not cr["passed"]
        assert any(v[0] == "zero_results_after_fallback" for v in cr["violations"])

    def test_catalog_only_chunks(self):
        """Catalog-only evidence should not count as usable."""
        cr = verify_tool_contract({
            "retrieved_chunks": [{"source_db": "concept_search", "metadata": {"evidence_kind": "pdf_catalog_chunk"}}],
            "fallback_mode": False,
        })
        assert not cr["passed"]


# ── C4: synthesize ────────────────────────────────────────────────────────────


class TestSynthesizeContract:
    def test_valid_price_answer(self):
        cr = verify_synthesize_contract({
            "evaluation": {"passed": True},
            "final_answer": "C30混凝土信息价为520元/m³",
            "query_type": "price",
            "retrieved_chunks": [
                {"metadata": {"price_tax_included": 520}},
                {"metadata": {"price_tax_included": 530}},
            ],
        })
        assert cr["passed"]

    def test_eval_not_passed(self):
        cr = verify_synthesize_contract({
            "evaluation": {"passed": False, "feedback": "catalog_only_refusal"},
            "final_answer": "未找到相关价格信息",
            "query_type": "price",
            "retrieved_chunks": [],
        })
        assert not cr["passed"]
        assert any(v[0] == "eval_not_passed" for v in cr["violations"])

    def test_no_price_number_in_answer(self):
        cr = verify_synthesize_contract({
            "evaluation": {"passed": True},
            "final_answer": "暂无该材料价格数据",
            "query_type": "price",
            "retrieved_chunks": [{"metadata": {"price_tax_included": 500}}],
        })
        assert not cr["passed"]
        assert any(v[0] == "no_price_number" for v in cr["violations"])

    def test_source_conflict(self):
        """Price CV > 0.15 should trigger source_conflict violation."""
        cr = verify_synthesize_contract({
            "evaluation": {"passed": True},
            "final_answer": "C30混凝土价格为500元/m³",
            "query_type": "price",
            "retrieved_chunks": [
                {"metadata": {"price_tax_included": 400}},
                {"metadata": {"price_tax_included": 600}},
            ],
        })
        assert not cr["passed"]
        assert any(v[0] == "source_conflict" for v in cr["violations"])

    def test_low_cv_no_conflict(self):
        """Price CV <= 0.15 should NOT trigger conflict."""
        cr = verify_synthesize_contract({
            "evaluation": {"passed": True},
            "final_answer": "C30混凝土价格为500元/m³",
            "query_type": "price",
            "retrieved_chunks": [
                {"metadata": {"price_tax_included": 500}},
                {"metadata": {"price_tax_included": 510}},
            ],
        })
        assert cr["passed"]

    def test_single_price_no_cv(self):
        """Single price point can't compute CV — no conflict."""
        cr = verify_synthesize_contract({
            "evaluation": {"passed": True},
            "final_answer": "C30混凝土价格为500元/m³",
            "query_type": "price",
            "retrieved_chunks": [
                {"metadata": {"price_tax_included": 500}},
            ],
        })
        assert cr["passed"]

    def test_non_price_query_skips_number_check(self):
        cr = verify_synthesize_contract({
            "evaluation": {"passed": True},
            "final_answer": "根据规范要求...",
            "query_type": "standard_ref",
            "retrieved_chunks": [{"source_db": "hybrid_search", "content": "test"}],
        })
        assert cr["passed"]


# ── trace_root_cause ──────────────────────────────────────────────────────────


class TestTraceRootCause:
    def test_returns_first_failure(self):
        results = [
            {"node": "query_analysis", "passed": True, "violations": []},
            {"node": "navigator_node", "passed": False, "violations": [("empty_roadmap", "")]},
            {"node": "tool_node", "passed": False, "violations": [("zero_results", "")]},
            {"node": "synthesize_node", "passed": False, "violations": [("no_price_number", "")]},
        ]
        assert trace_root_cause({"contract_results": results}) == "navigator_node"

    def test_all_pass_returns_default(self):
        results = [
            {"node": "query_analysis", "passed": True, "violations": []},
            {"node": "navigator_node", "passed": True, "violations": []},
        ]
        assert trace_root_cause({"contract_results": results}) == "query_analysis"

    def test_empty_returns_default(self):
        assert trace_root_cause({"contract_results": []}) == "query_analysis"


# ── _compute_price_cv_from_chunks ─────────────────────────────────────────────


class TestPriceCV:
    def test_identical_prices_zero_cv(self):
        chunks = [
            {"metadata": {"price_tax_included": 500}},
            {"metadata": {"price_tax_included": 500}},
            {"metadata": {"price_tax_included": 500}},
        ]
        cv = _compute_price_cv_from_chunks(chunks)
        assert cv == 0.0

    def test_varied_prices(self):
        chunks = [
            {"metadata": {"price_tax_included": 400}},
            {"metadata": {"price_tax_included": 500}},
            {"metadata": {"price_tax_included": 600}},
        ]
        cv = _compute_price_cv_from_chunks(chunks)
        # mean=500, std=81.65, CV=0.163
        assert 0.15 < cv < 0.18

    def test_single_price_returns_none(self):
        cv = _compute_price_cv_from_chunks([{"metadata": {"price_tax_included": 500}}])
        assert cv is None

    def test_no_prices_returns_none(self):
        cv = _compute_price_cv_from_chunks([{"content": "no metadata"}])
        assert cv is None

    def test_empty_chunks_returns_none(self):
        cv = _compute_price_cv_from_chunks([])
        assert cv is None

    def test_zero_mean_returns_none(self):
        cv = _compute_price_cv_from_chunks([
            {"metadata": {"price_tax_included": 0}},
            {"metadata": {"price_tax_included": 0}},
        ])
        assert cv is None
