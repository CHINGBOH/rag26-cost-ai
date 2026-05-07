"""
Root cause analysis framework — deep dive into detected problems.

Traces execution chains, extracts failure patterns, and synthesizes root causes.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
import asyncio
import re
from enum import Enum

from app.agent.problem_detector import (
    ProblemReport,
    FailureSignal,
    FeedbackSignal,
    ViolationSignal,
    TopoAnomalySignal,
)


class RootCauseType(str, Enum):
    """Categories of root causes."""
    DATA_STALE = "data_stale"
    POOR_QUERY_UNDERSTANDING = "poor_query_understanding"
    SUBOPTIMAL_RANKING = "suboptimal_ranking"
    TOOL_FAILURE = "tool_failure"
    INSUFFICIENT_DIVERSITY = "insufficient_diversity"
    ARCHITECTURE_FLAW = "architecture_flaw"
    CONFIGURATION_ERROR = "configuration_error"
    EXTERNAL_DEPENDENCY = "external_dependency"


@dataclass
class RootCauseReport:
    """Analysis result: likely root cause(s) for a problem."""
    problem_id: str
    affected_route: str
    root_cause_hypothesis: str  # Most likely cause
    root_cause_type: RootCauseType
    contributing_factors: List[str]  # Secondary factors
    evidence_chain: Dict[str, Any]  # Trace through signals
    confidence: float  # 0-1 certainty of root cause
    repair_suggestions: List[str]  # Actionable fixes
    repair_priority: str  # 'urgent' | 'high' | 'medium' | 'low'
    ts: float

    def to_dict(self) -> Dict:
        """Convert to dict for persistence."""
        return {
            "problem_id": self.problem_id,
            "affected_route": self.affected_route,
            "root_cause_hypothesis": self.root_cause_hypothesis,
            "root_cause_type": self.root_cause_type.value,
            "contributing_factors": self.contributing_factors,
            "evidence_chain": self.evidence_chain,
            "confidence": self.confidence,
            "repair_suggestions": self.repair_suggestions,
            "repair_priority": self.repair_priority,
            "ts": self.ts,
        }


@dataclass
class ExecutionTrace:
    """A trace of a single query execution through the system."""
    run_id: str
    session_id: str
    query: str
    steps: List[Dict] = field(default_factory=list)  # Each step: {node, input, output, latency_ms, error}
    final_output: Optional[str] = None
    overall_success: bool = False
    overall_latency_ms: int = 0


class RootCauseAnalyzer:
    """
    Analyzes problems to find root causes.
    Combines execution traces, feedback patterns, and topology info.
    """

    def __init__(self):
        """Initialize analyzer."""
        self.failure_pattern_keywords = {
            "数据": "data_stale",
            "outdated": "data_stale",
            "过时": "data_stale",
            "逻辑": "poor_query_understanding",
            "logic": "poor_query_understanding",
            "理解": "poor_query_understanding",
            "排序": "suboptimal_ranking",
            "ranking": "suboptimal_ranking",
            "工具": "tool_failure",
            "tool": "tool_failure",
            "崩溃": "tool_failure",
            "crash": "tool_failure",
            "超时": "tool_failure",
            "timeout": "tool_failure",
            "多样性": "insufficient_diversity",
            "重复": "insufficient_diversity",
            "diversity": "insufficient_diversity",
        }

    async def analyze_root_cause(
        self, problem: ProblemReport, signals_context: Optional[Dict] = None
    ) -> RootCauseReport:
        """
        Analyze a detected problem to find its root cause.

        Args:
            problem: The detected problem
            signals_context: Optional dict with aggregated signals for context

        Returns:
            RootCauseReport with hypothesis and suggestions
        """
        # For this mock implementation, we'll derive root cause from:
        # 1. Problem category
        # 2. Problem description keywords
        # 3. Affected route
        # 4. Confidence scoring

        root_cause_type = self._infer_root_cause_type(problem)
        contributing_factors = self._identify_contributing_factors(problem)
        evidence_chain = self._build_evidence_chain(problem, signals_context or {})
        repair_suggestions = self._generate_repair_suggestions(problem, root_cause_type)
        confidence = self._calculate_confidence(problem, evidence_chain)
        repair_priority = self._determine_priority(problem, root_cause_type)

        hypothesis = self._formulate_hypothesis(
            problem, root_cause_type, contributing_factors
        )

        report = RootCauseReport(
            problem_id=problem.problem_id,
            affected_route=problem.affected_route,
            root_cause_hypothesis=hypothesis,
            root_cause_type=root_cause_type,
            contributing_factors=contributing_factors,
            evidence_chain=evidence_chain,
            confidence=confidence,
            repair_suggestions=repair_suggestions,
            repair_priority=repair_priority,
            ts=problem.ts,
        )

        return report

    async def trace_execution_chain(
        self, problem: ProblemReport, run_ids: Optional[List[str]] = None
    ) -> List[ExecutionTrace]:
        """
        Trace execution chains for failures related to this problem.

        In a real implementation, this would query conversation_turns
        and agent_runs tables to reconstruct the execution flow.

        Args:
            problem: The problem to trace
            run_ids: Optional specific run IDs to trace

        Returns:
            List of execution traces
        """
        if run_ids is not None:
            # Placeholder until trace reconstruction wires to concrete run tables.
            run_ids = [run_id for run_id in run_ids if run_id]
        traces = []

        # Mock: In real implementation, this would:
        # SELECT * FROM conversation_turns WHERE affected_route = ?
        # JOIN agent_runs to get detailed step info
        # Reconstruct the execution chain

        # For now, return empty list to indicate no traces found
        return traces

    async def extract_failure_patterns(
        self, problem: ProblemReport, feedback_signals: List[FeedbackSignal]
    ) -> Dict[str, Any]:
        """
        Extract failure patterns from problem evidence and feedback.

        Uses NLP-like keyword extraction to identify failure modes.

        Args:
            problem: The problem being analyzed
            feedback_signals: Feedback signals for context

        Returns:
            Dict of extracted patterns
        """
        patterns = {
            "keywords": [],
            "inferred_causes": [],
            "confidence_by_cause": {},
        }

        # Extract keywords from problem description and evidence
        feedback_text = " ".join(signal.text for signal in feedback_signals if signal.text)
        feedback_tags = " ".join(tag for signal in feedback_signals for tag in signal.tags)
        all_text = " ".join(part for part in [problem.description, *problem.evidence, feedback_text, feedback_tags] if part)
        keywords = self._extract_keywords(all_text)
        patterns["keywords"] = keywords

        # Map keywords to failure causes
        for keyword in keywords:
            for pattern, cause_type in self.failure_pattern_keywords.items():
                if pattern in keyword.lower():
                    patterns["inferred_causes"].append(cause_type)
                    patterns["confidence_by_cause"][cause_type] = (
                        patterns["confidence_by_cause"].get(cause_type, 0) + 1
                    )

        # Normalize confidence scores
        total = sum(patterns["confidence_by_cause"].values()) or 1
        for cause in patterns["confidence_by_cause"]:
            patterns["confidence_by_cause"][cause] /= total

        return patterns

    async def find_topology_hotspots(
        self, affected_route: str, topo_signals: List[TopoAnomalySignal]
    ) -> List[Dict]:
        """
        Find topology hotspots related to the affected route.

        Args:
            affected_route: The route being affected (R1-R5)
            topo_signals: Topology anomaly signals

        Returns:
            List of hotspot dicts with edge_id and metrics
        """
        hotspots = []

        # Map route to relevant edges
        route_edges = self._get_edges_for_route(affected_route)

        for signal in topo_signals:
            if signal.edge_id in route_edges:
                hotspots.append(
                    {
                        "edge_id": signal.edge_id,
                        "anomaly_type": signal.anomaly_type,
                        "metrics": signal.metrics,
                    }
                )

        return hotspots

    def _infer_root_cause_type(self, problem: ProblemReport) -> RootCauseType:
        """Infer root cause type from problem attributes."""
        # Map problem category to root cause type
        category_to_type = {
            "prompt_issue": RootCauseType.POOR_QUERY_UNDERSTANDING,
            "tool_failure": RootCauseType.TOOL_FAILURE,
            "routing_error": RootCauseType.ARCHITECTURE_FLAW,
            "low_quality": RootCauseType.SUBOPTIMAL_RANKING,
            "diversity_issue": RootCauseType.INSUFFICIENT_DIVERSITY,
            "contract_violation": RootCauseType.ARCHITECTURE_FLAW,
            "topo_anomaly": RootCauseType.CONFIGURATION_ERROR,
        }

        # Check description for specific keywords
        desc_lower = problem.description.lower()
        if "数据" in desc_lower or "data" in desc_lower or "outdated" in desc_lower:
            return RootCauseType.DATA_STALE

        return category_to_type.get(
            problem.category.value, RootCauseType.ARCHITECTURE_FLAW
        )

    def _identify_contributing_factors(
        self, problem: ProblemReport
    ) -> List[str]:
        """Identify secondary factors contributing to the problem."""
        factors = []

        context = problem.additional_context or {}

        # Check for common secondary factors
        if context.get("p95_latency_ms", 0) > 3000:
            factors.append("High latency contributing to perceived quality issues")

        if context.get("failure_count", 0) > 5:
            factors.append("Multiple repeated failures indicate cascading issue")

        if context.get("affected_sessions", 0) > 3:
            factors.append("Multiple user sessions affected (not isolated)")

        if "error_distribution" in context:
            error_types = len(context["error_distribution"])
            if error_types > 1:
                factors.append(
                    f"Multiple error types ({error_types}) suggest multiple root causes"
                )

        if problem.confidence < 0.5:
            factors.append("Low confidence suggests complex/multi-factor issue")

        return factors or ["Single factor issue (appears isolated)"]

    def _build_evidence_chain(
        self, problem: ProblemReport, context: Dict
    ) -> Dict[str, Any]:
        """Build a chain of evidence supporting the root cause hypothesis."""
        chain = {
            "primary_evidence": problem.evidence,
            "problem_category": problem.category.value,
            "confidence": problem.confidence,
            "affected_route": problem.affected_route,
        }

        # Add context-specific evidence
        if problem.additional_context:
            chain["detailed_metrics"] = problem.additional_context

        return chain

    def _generate_repair_suggestions(
        self, problem: ProblemReport, cause_type: RootCauseType
    ) -> List[str]:
        """Generate actionable repair suggestions based on root cause."""
        suggestions = []

        # Route-specific suggestions
        if problem.affected_route == "R1_navigator_dict":
            suggestions.extend([
                "Add missing query type classification rules",
                "Expand keyword dictionary with synonyms",
                "Review query analyzer confidence thresholds",
                "Add unit tests for edge case queries",
            ])
        elif problem.affected_route == "R2_path_default":
            suggestions.extend([
                "Update path constraint defaults based on historical hits",
                "Add data freshness validation before retrieval",
                "Implement data source quality scoring",
            ])
        elif problem.affected_route == "R3_planner_examples":
            suggestions.extend([
                "Add new few-shot examples covering failed query types",
                "Review planner prompt for ambiguous instructions",
                "Increase planning step diversity",
            ])
        elif problem.affected_route == "R4_rerank_weights":
            suggestions.extend([
                "Rebalance ranking weights based on click-through data",
                "Add freshness/recency factors to ranking",
                "Test ranking performance on historical queries",
            ])
        elif problem.affected_route == "R5_tool_priority":
            suggestions.extend([
                "Reorder tool selection priority based on hit rates",
                "Add tool fallback strategies",
                "Profile tool performance and timeout settings",
            ])

        # Cause-type-specific suggestions
        if cause_type == RootCauseType.DATA_STALE:
            suggestions.extend([
                "Schedule data refresh and verify freshness",
                "Implement data source health checks",
                "Add timestamp validation in retrieval",
            ])
        elif cause_type == RootCauseType.TOOL_FAILURE:
            suggestions.extend([
                "Check external tool status and health",
                "Implement retry logic with exponential backoff",
                "Add circuit breaker pattern for tool calls",
            ])
        elif cause_type == RootCauseType.INSUFFICIENT_DIVERSITY:
            suggestions.extend([
                "Implement query reformulation diversity",
                "Add different retrieval strategies",
                "Rotate through different ranking approaches",
            ])

        return suggestions[:5]  # Return top 5 suggestions

    def _calculate_confidence(
        self, problem: ProblemReport, evidence_chain: Dict
    ) -> float:
        """Calculate confidence in the root cause hypothesis."""
        base_confidence = problem.confidence

        # Increase confidence if we have multiple evidence pieces
        evidence_count = len(problem.evidence)
        evidence_multiplier = min(1.0, evidence_count / 5)

        # Increase confidence for high-severity problems
        severity_multiplier = {
            "high": 1.0,
            "medium": 0.8,
            "low": 0.6,
        }.get(problem.severity.value, 0.5)

        confidence = base_confidence * evidence_multiplier * severity_multiplier
        return min(1.0, confidence)

    def _determine_priority(
        self, problem: ProblemReport, cause_type: RootCauseType
    ) -> str:
        """Determine repair priority."""
        if problem.severity.value == "high":
            return "urgent"
        elif problem.severity.value == "medium":
            if cause_type in [
                RootCauseType.TOOL_FAILURE,
                RootCauseType.DATA_STALE,
            ]:
                return "high"
            return "medium"
        else:
            return "low"

    def _formulate_hypothesis(
        self,
        problem: ProblemReport,
        cause_type: RootCauseType,
        contributing_factors: List[str],
    ) -> str:
        """Formulate a human-readable root cause hypothesis."""
        hypothesis = f"Root cause: {cause_type.value}. "

        if contributing_factors:
            hypothesis += f"Contributing factors: {', '.join(contributing_factors[:2])}. "

        hypothesis += (
            f"Affected route: {problem.affected_route}. "
            f"Confidence: {problem.confidence:.0%}"
        )

        return hypothesis

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text for pattern matching."""
        # Simple keyword extraction: split and filter short words
        words = re.findall(r"\w+", text.lower())
        # Return words longer than 2 chars, removing common stopwords
        stopwords = {"the", "and", "or", "is", "to", "of", "in", "a"}
        return [w for w in words if len(w) > 2 and w not in stopwords]

    def _get_edges_for_route(self, affected_route: str) -> List[str]:
        """Get topology edges that are relevant to a route."""
        route_edges = {
            "R1_navigator_dict": [
                "query->analyzer",
                "analyzer->navigator",
            ],
            "R2_path_default": [
                "analyzer->navigator",
                "navigator->retriever",
            ],
            "R3_planner_examples": [
                "query->analyzer",
                "analyzer->navigator",
            ],
            "R4_rerank_weights": [
                "retriever->tool",
                "tool->verifier",
            ],
            "R5_tool_priority": [
                "retriever->tool",
                "tool->verifier",
                "verifier->synthesize",
            ],
        }
        return route_edges.get(affected_route, [])
