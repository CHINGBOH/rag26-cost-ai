"""
Unit tests for problem detection and root cause analysis frameworks
"""

import pytest
import asyncio
from datetime import datetime, timedelta

from app.agent.problem_detector import (
    ProblemDetector,
    ProblemReport,
    AggregatedSignals,
    FailureSignal,
    FeedbackSignal,
    ViolationSignal,
    RepeatQuestionSignal,
    TopoAnomalySignal,
    ProblemCategory,
    Severity,
)
from app.agent.root_cause_analyzer import (
    RootCauseAnalyzer,
    RootCauseType,
)


class TestProblemDetectorRules:
    """Test problem detection rules."""

    @pytest.fixture
    def detector(self):
        return ProblemDetector()

    @pytest.fixture
    def signals_base(self):
        now = datetime.now().timestamp()
        return AggregatedSignals(
            window_start=now - 3600,
            window_end=now,
        )

    def test_rule_continuous_failure_detection(self, detector, signals_base):
        """Test that continuous failures are detected."""
        # Create multiple failures on same route
        now = datetime.now().timestamp()
        for i in range(5):
            signals_base.failure_signals.append(
                FailureSignal(
                    signal_id=f"fail_{i}",
                    ts=now - (i * 100),
                    route_id="R1_navigator_dict",
                    error_code="QUERY_ANALYSIS_FAILED",
                    context={
                        "query": f"test query {i}",
                        "tool_name": "navigator",
                        "attempt_count": 2,
                    },
                    latency_ms=1000 + i * 500,
                )
            )

        # Detect problems
        problems = asyncio.run(detector.detect_problems(signals_base))

        # Should find continuous failure problem
        assert len(problems) > 0
        cont_fail = [p for p in problems if p.category == ProblemCategory.TOOL_FAILURE]
        assert len(cont_fail) > 0
        assert cont_fail[0].affected_route == "R1_navigator_dict"
        assert cont_fail[0].severity == Severity.HIGH
        assert cont_fail[0].confidence >= 0.3

    def test_rule_negative_feedback_clustering(self, detector, signals_base):
        """Test that clustered negative feedback is detected."""
        now = datetime.now().timestamp()
        # Create feedback with clustered tag
        for i in range(8):
            signals_base.feedback_signals.append(
                FeedbackSignal(
                    signal_id=f"feedback_{i}",
                    ts=now - (i * 100),
                    overall_score=2.0 + (i % 3),
                    dimensions={
                        "accuracy": 2.5,
                        "relevance": 2.0,
                        "timeliness": 2.0,
                        "completeness": 2.0,
                    },
                    tags=["数据过时", "不相关"],  # Repeated tag
                    text=f"Data is outdated in iteration {i}",
                )
            )

        problems = asyncio.run(detector.detect_problems(signals_base))

        # Should find feedback cluster problems
        low_quality = [p for p in problems if p.category == ProblemCategory.LOW_QUALITY]
        assert len(low_quality) > 0

    def test_rule_repeat_questions_detection(self, detector, signals_base):
        """Test that repeated questions are detected."""
        now = datetime.now().timestamp()
        session_id = "test_session_1"

        # Create multiple repeat signals
        for i in range(4):
            signals_base.repeat_signals.append(
                RepeatQuestionSignal(
                    signal_id=f"repeat_{i}",
                    ts=now - (i * 100),
                    session_id=session_id,
                    original_turn=i,
                    repeat_turn=i + 5,
                    similarity_score=0.88 + (i * 0.01),
                )
            )

        problems = asyncio.run(detector.detect_problems(signals_base))

        # Should find diversity issue
        diversity = [p for p in problems if p.category == ProblemCategory.DIVERSITY_ISSUE]
        assert len(diversity) > 0
        assert diversity[0].affected_route == "R3_planner_examples"

    def test_rule_contract_violation_detection(self, detector, signals_base):
        """Test that contract violations are detected."""
        now = datetime.now().timestamp()

        # Create contract violations
        for i in range(3):
            signals_base.violation_signals.append(
                ViolationSignal(
                    signal_id=f"violation_{i}",
                    ts=now - (i * 100),
                    contract_name="NavigatorContract",
                    violation_code="NAV_ROADMAP_EMPTY",
                    detail="Navigator roadmap was empty on iteration " + str(i),
                )
            )

        problems = asyncio.run(detector.detect_problems(signals_base))

        # Should find contract violation problems
        contracts = [
            p for p in problems if p.category == ProblemCategory.CONTRACT_VIOLATION
        ]
        assert len(contracts) > 0

    def test_rule_topology_anomaly_detection(self, detector, signals_base):
        """Test that topology anomalies are detected."""
        now = datetime.now().timestamp()

        # Create stale edge anomaly
        signals_base.topo_signals.append(
            TopoAnomalySignal(
                signal_id="topo_stale_1",
                ts=now,
                edge_id="query->analyzer",
                anomaly_type="stale",
                metrics={
                    "last_traversed": (now - 86400),  # 1 day ago
                    "traversal_count": 0,
                },
            )
        )

        # Create spike edge anomaly
        signals_base.topo_signals.append(
            TopoAnomalySignal(
                signal_id="topo_spike_1",
                ts=now,
                edge_id="retriever->tool",
                anomaly_type="spike",
                metrics={
                    "traversal_count": 5000,
                    "avg_latency_ms": 2500,
                },
            )
        )

        problems = asyncio.run(detector.detect_problems(signals_base))

        # Should find topology anomaly problems
        topo = [p for p in problems if p.category == ProblemCategory.TOPO_ANOMALY]
        assert len(topo) >= 2

    def test_deduplication_keeps_highest_confidence(self, detector):
        """Test that deduplication keeps highest confidence problem."""
        problems = [
            ProblemReport(
                problem_id="prob_1",
                category=ProblemCategory.TOOL_FAILURE,
                severity=Severity.HIGH,
                affected_route="R1_navigator_dict",
                description="Test problem 1",
                evidence=["Evidence 1"],
                confidence=0.6,
                suggested_gap_id="gap_1",
                ts=datetime.now().timestamp(),
            ),
            ProblemReport(
                problem_id="prob_2",
                category=ProblemCategory.TOOL_FAILURE,
                severity=Severity.HIGH,
                affected_route="R1_navigator_dict",
                description="Test problem 2",
                evidence=["Evidence 2"],
                confidence=0.8,
                suggested_gap_id="gap_2",
                ts=datetime.now().timestamp(),
            ),
        ]

        dedup = detector._deduplicate_problems(problems)

        assert len(dedup) == 1
        assert dedup[0].confidence == 0.8
        assert dedup[0].problem_id == "prob_2"


class TestRootCauseAnalyzer:
    """Test root cause analysis."""

    @pytest.fixture
    def analyzer(self):
        return RootCauseAnalyzer()

    def test_root_cause_inference_from_problem(self, analyzer):
        """Test that root causes are correctly inferred."""
        problem = ProblemReport(
            problem_id="test_prob",
            category=ProblemCategory.LOW_QUALITY,
            severity=Severity.HIGH,
            affected_route="R4_rerank_weights",
            description="Mean score is low due to stale data",
            evidence=["Score distribution shows degradation"],
            confidence=0.8,
            suggested_gap_id="gap_quality",
            ts=datetime.now().timestamp(),
            additional_context={"mean_score": 2.5},
        )

        report = asyncio.run(analyzer.analyze_root_cause(problem))

        assert report.problem_id == problem.problem_id
        assert report.affected_route == problem.affected_route
        assert report.confidence > 0.0
        assert len(report.repair_suggestions) > 0
        assert report.root_cause_type in [
            RootCauseType.DATA_STALE,
            RootCauseType.SUBOPTIMAL_RANKING,
        ]

    def test_repair_suggestions_generated(self, analyzer):
        """Test that repair suggestions are generated for each route."""
        for route in [
            "R1_navigator_dict",
            "R2_path_default",
            "R3_planner_examples",
            "R4_rerank_weights",
            "R5_tool_priority",
        ]:
            problem = ProblemReport(
                problem_id=f"test_{route}",
                category=ProblemCategory.TOOL_FAILURE,
                severity=Severity.MEDIUM,
                affected_route=route,  # type: ignore
                description=f"Test problem on {route}",
                evidence=["Test evidence"],
                confidence=0.7,
                suggested_gap_id="gap_test",
                ts=datetime.now().timestamp(),
            )

            report = asyncio.run(analyzer.analyze_root_cause(problem))

            assert len(report.repair_suggestions) > 0
            for suggestion in report.repair_suggestions:
                assert len(suggestion) > 0

    def test_confidence_calculation(self, analyzer):
        """Test that confidence is properly calculated."""
        problem_high_evidence = ProblemReport(
            problem_id="prob_high",
            category=ProblemCategory.TOOL_FAILURE,
            severity=Severity.HIGH,
            affected_route="R1_navigator_dict",
            description="Multiple evidence pieces",
            evidence=["E1", "E2", "E3", "E4", "E5"],
            confidence=0.9,
            suggested_gap_id="gap",
            ts=datetime.now().timestamp(),
        )

        problem_low_evidence = ProblemReport(
            problem_id="prob_low",
            category=ProblemCategory.TOOL_FAILURE,
            severity=Severity.LOW,
            affected_route="R1_navigator_dict",
            description="Single evidence piece",
            evidence=["E1"],
            confidence=0.3,
            suggested_gap_id="gap",
            ts=datetime.now().timestamp(),
        )

        report_high = asyncio.run(analyzer.analyze_root_cause(problem_high_evidence))
        report_low = asyncio.run(analyzer.analyze_root_cause(problem_low_evidence))

        # High evidence should have higher confidence
        assert report_high.confidence >= report_low.confidence

    def test_priority_determination(self, analyzer):
        """Test that repair priority is correctly determined."""
        problem_urgent = ProblemReport(
            problem_id="urgent",
            category=ProblemCategory.TOOL_FAILURE,
            severity=Severity.HIGH,
            affected_route="R1_navigator_dict",
            description="Urgent issue",
            evidence=["Evidence"],
            confidence=0.9,
            suggested_gap_id="gap",
            ts=datetime.now().timestamp(),
        )

        report = asyncio.run(analyzer.analyze_root_cause(problem_urgent))
        assert report.repair_priority == "urgent"

    def test_contributing_factors_extraction(self, analyzer):
        """Test that contributing factors are identified."""
        problem = ProblemReport(
            problem_id="test",
            category=ProblemCategory.TOOL_FAILURE,
            severity=Severity.MEDIUM,
            affected_route="R5_tool_priority",
            description="Tool failure with high latency",
            evidence=["E1", "E2", "E3"],
            confidence=0.7,
            suggested_gap_id="gap",
            ts=datetime.now().timestamp(),
            additional_context={
                "failure_count": 10,
                "p95_latency_ms": 5000,
                "affected_sessions": 5,
            },
        )

        factors = analyzer._identify_contributing_factors(problem)

        assert len(factors) > 0
        assert any("latency" in f.lower() for f in factors)


class TestIntegration:
    """Integration tests for the full detection + analysis flow."""

    def test_end_to_end_problem_detection_and_analysis(self):
        """Test full flow: detect problems, then analyze root causes."""
        detector = ProblemDetector()
        analyzer = RootCauseAnalyzer()

        # Create signals
        now = datetime.now().timestamp()
        signals = AggregatedSignals(
            window_start=now - 3600,
            window_end=now,
        )

        # Add continuous failures
        for i in range(5):
            signals.failure_signals.append(
                FailureSignal(
                    signal_id=f"fail_{i}",
                    ts=now - (i * 100),
                    route_id="R1_navigator_dict",
                    error_code="NAV_ERROR",
                    context={"query": f"test {i}"},
                    latency_ms=1000,
                )
            )

        # Detect problems
        problems = asyncio.run(detector.detect_problems(signals))
        assert len(problems) > 0

        # Analyze root causes for each problem
        reports = []
        for problem in problems:
            report = asyncio.run(analyzer.analyze_root_cause(problem))
            reports.append(report)

        assert len(reports) > 0
        for report in reports:
            assert report.confidence > 0.0
            assert len(report.repair_suggestions) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
