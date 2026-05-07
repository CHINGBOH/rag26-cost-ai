"""
Problem detection framework — identifies systemic issues from aggregated signals.

Transform raw signals into actionable problems via rule-based heuristics.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
from datetime import datetime
from enum import Enum
import time
import uuid
from collections import defaultdict
from statistics import mean, median

from app.agent.learning_config import get_learning_config


class ProblemCategory(str, Enum):
    """Classification of detected problems."""
    PROMPT_ISSUE = "prompt_issue"
    TOOL_FAILURE = "tool_failure"
    ROUTING_ERROR = "routing_error"
    LOW_QUALITY = "low_quality"
    DIVERSITY_ISSUE = "diversity_issue"
    CONTRACT_VIOLATION = "contract_violation"
    TOPO_ANOMALY = "topo_anomaly"


class Severity(str, Enum):
    """Problem severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class FailureSignal:
    """Represents a query/tool failure."""
    signal_id: str
    ts: float
    route_id: str  # R1_navigator_dict, etc
    error_code: str
    context: Dict = field(default_factory=dict)  # query, tool_name, attempt_count, etc
    latency_ms: int = 0
    metadata: Dict = field(default_factory=dict)


@dataclass
class FeedbackSignal:
    """User feedback on answer quality."""
    signal_id: str
    ts: float
    overall_score: float  # 1-5
    dimensions: Dict[str, float] = field(default_factory=dict)  # accuracy, relevance, timeliness, etc
    tags: List[str] = field(default_factory=list)  # ['数据过时', '缺少依据', ...]
    text: str = ""
    metadata: Dict = field(default_factory=dict)


@dataclass
class ViolationSignal:
    """Contract verification failure."""
    signal_id: str
    ts: float
    contract_name: str
    violation_code: str
    detail: str = ""
    metadata: Dict = field(default_factory=dict)


@dataclass
class RepeatQuestionSignal:
    """User asked similar question again."""
    signal_id: str
    ts: float
    session_id: str
    original_turn: int
    repeat_turn: int
    similarity_score: float
    metadata: Dict = field(default_factory=dict)


@dataclass
class TopoAnomalySignal:
    """Topology edge anomaly."""
    signal_id: str
    ts: float
    edge_id: str  # e.g., 'query->analyzer'
    anomaly_type: str  # 'stale', 'spike', 'dead'
    metrics: Dict = field(default_factory=dict)  # traversal_count, last_traversed_at, etc
    metadata: Dict = field(default_factory=dict)


@dataclass
class AggregatedSignals:
    """Collection of signals aggregated over a time window."""
    window_start: float
    window_end: float
    failure_signals: List[FailureSignal] = field(default_factory=list)
    feedback_signals: List[FeedbackSignal] = field(default_factory=list)
    violation_signals: List[ViolationSignal] = field(default_factory=list)
    repeat_signals: List[RepeatQuestionSignal] = field(default_factory=list)
    topo_signals: List[TopoAnomalySignal] = field(default_factory=list)


@dataclass
class ProblemReport:
    """Detected problem requiring action."""
    problem_id: str
    category: ProblemCategory
    severity: Severity
    affected_route: str  # R1-R5
    description: str
    evidence: List[str]  # Supporting evidence from signals
    confidence: float  # 0-1
    suggested_gap_id: str  # For creating KnowledgeGap
    ts: float
    additional_context: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convert to dict for persistence."""
        return {
            "problem_id": self.problem_id,
            "category": self.category.value,
            "severity": self.severity.value,
            "affected_route": self.affected_route,
            "description": self.description,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "suggested_gap_id": self.suggested_gap_id,
            "ts": self.ts,
            "additional_context": self.additional_context,
        }


class ProblemDetector:
    """
    Detects problems from aggregated signals.
    Applies rule-based heuristics to identify systemic issues.
    """

    def __init__(self):
        config = get_learning_config().problem_detector
        self.CONTINUOUS_FAILURE_THRESHOLD = config.continuous_failure_threshold
        self.REPEAT_QUESTION_THRESHOLD = config.repeat_question_threshold
        self.NEGATIVE_FEEDBACK_FREQUENCY_THRESHOLD = (
            config.negative_feedback_frequency_threshold
        )
        self.LATENCY_P95_THRESHOLD_MS = config.latency_p95_threshold_ms
        self.detected_problems: List[ProblemReport] = []

    async def detect_problems(
        self, signals: AggregatedSignals
    ) -> List[ProblemReport]:
        """
        Identify problems from aggregated signals.
        Returns sorted by confidence (descending).
        """
        self.detected_problems = []

        # Rule 1: Continuous failures → systemic issue
        if len(signals.failure_signals) > self.CONTINUOUS_FAILURE_THRESHOLD:
            self.detected_problems.extend(
                self._rule_continuous_failure(signals.failure_signals)
            )

        # Rule 2: Negative feedback clustering → prompt or tool issue
        if signals.feedback_signals:
            self.detected_problems.extend(
                self._rule_negative_feedback(signals.feedback_signals)
            )

        # Rule 3: Contract violations → integrity issue
        if signals.violation_signals:
            self.detected_problems.extend(
                self._rule_contract_violation(signals.violation_signals)
            )

        # Rule 4: Repeated questions → diversity/robustness issue
        if len(signals.repeat_signals) > self.REPEAT_QUESTION_THRESHOLD:
            problem = self._rule_repeat_questions(signals.repeat_signals)
            if problem:
                self.detected_problems.append(problem)

        # Rule 5: Topology anomalies → dead code or stale paths
        if signals.topo_signals:
            self.detected_problems.extend(
                self._rule_topology_anomaly(signals.topo_signals)
            )

        # Deduplicate + sort by confidence
        self.detected_problems = self._deduplicate_problems(self.detected_problems)
        self.detected_problems.sort(
            key=lambda p: (p.severity.value, -p.confidence),
            reverse=True
        )

        return self.detected_problems

    def _rule_continuous_failure(
        self, failures: List[FailureSignal]
    ) -> List[ProblemReport]:
        """
        Detect: Multiple failures in same route suggest systemic problem.

        Heuristic: Group by route, check if any route has >3 failures,
        extract common context.
        """
        problems = []
        failures_by_route: Dict[str, List[FailureSignal]] = defaultdict(list)

        for failure in failures:
            failures_by_route[failure.route_id].append(failure)

        for route_id, route_failures in failures_by_route.items():
            if len(route_failures) > self.CONTINUOUS_FAILURE_THRESHOLD:
                # Analyze common context
                error_codes = [f.error_code for f in route_failures]
                most_common_error = max(set(error_codes), key=error_codes.count)

                # Extract latency pattern
                latencies = [f.latency_ms for f in route_failures if f.latency_ms > 0]
                latency_p95 = (
                    sorted(latencies)[-1] if latencies else 0
                )

                # Infer context: what's common across failures?
                common_context = self._extract_common_context(
                    [f.context for f in route_failures]
                )

                problem_desc = (
                    f"Continuous failures on {route_id}: "
                    f"{len(route_failures)} failures, "
                    f"most common error={most_common_error}"
                )

                if latency_p95 > self.LATENCY_P95_THRESHOLD_MS:
                    problem_desc += f" (P95 latency={latency_p95}ms)"

                problem = ProblemReport(
                    problem_id=f"cont_fail_{route_id}_{int(time.time())}",
                    category=ProblemCategory.TOOL_FAILURE,
                    severity=Severity.HIGH,
                    affected_route=route_id,
                    description=problem_desc,
                    evidence=[
                        f"Failure #{i + 1}: {f.error_code}" for i, f in enumerate(route_failures[:3])
                    ],
                    confidence=min(1.0, len(route_failures) / 10),  # 3→0.3, 10→1.0
                    suggested_gap_id=f"gap_{route_id}_error_handling",
                    ts=time.time(),
                    additional_context={
                        "failure_count": len(route_failures),
                        "error_distribution": dict(
                            (code, error_codes.count(code)) for code in set(error_codes)
                        ),
                        "common_context": common_context,
                        "p95_latency_ms": latency_p95,
                    },
                )
                problems.append(problem)

        return problems

    def _rule_negative_feedback(
        self, feedbacks: List[FeedbackSignal]
    ) -> List[ProblemReport]:
        """
        Detect: Clustered negative feedback on specific issues.

        Heuristic: Count tag frequencies, if any tag >20%, it's a problem signal.
        Also check score distribution — if mean <3.0, systemic quality issue.
        """
        problems = []

        # Tag frequency analysis
        tag_counts: Dict[str, int] = defaultdict(int)
        for feedback in feedbacks:
            for tag in feedback.tags:
                tag_counts[tag] += 1

        total_feedbacks = len(feedbacks)
        for tag, count in tag_counts.items():
            frequency = count / total_feedbacks
            if frequency > self.NEGATIVE_FEEDBACK_FREQUENCY_THRESHOLD:
                # This tag is significant
                problem_desc = (
                    f"Feedback cluster: '{tag}' appears in {count}/{total_feedbacks} "
                    f"({frequency:.1%}) of feedback. Potential systemic issue."
                )

                # Map tag to affected route (simple heuristic)
                route = self._map_tag_to_route(tag)

                problem = ProblemReport(
                    problem_id=f"feedback_{tag.replace(' ', '_')}_{int(time.time())}",
                    category=ProblemCategory.LOW_QUALITY,
                    severity=Severity.MEDIUM if frequency < 0.5 else Severity.HIGH,
                    affected_route=route,
                    description=problem_desc,
                    evidence=[
                        f"User feedback #{i + 1}: {f.text[:100]}"
                        for i, f in enumerate(feedbacks[:3]) if f.text
                    ],
                    confidence=frequency,
                    suggested_gap_id=f"gap_quality_{tag.replace(' ', '_')}",
                    ts=time.time(),
                    additional_context={
                        "tag": tag,
                        "frequency": frequency,
                        "count": count,
                        "sample_texts": [f.text for f in feedbacks if tag in f.tags][:3],
                    },
                )
                problems.append(problem)

        # Score distribution analysis
        scores = [f.overall_score if f.overall_score > 0 else f.rating for f in feedbacks]
        if scores:
            mean_score = mean(scores)
            if mean_score < 3.0:
                problem = ProblemReport(
                    problem_id=f"low_score_{int(time.time())}",
                    category=ProblemCategory.LOW_QUALITY,
                    severity=Severity.HIGH,
                    affected_route="R4_rerank_weights",  # Default: ranking issue
                    description=f"Low overall score: mean={mean_score:.2f}/5",
                    evidence=[f"Score #{i + 1}: {score}" for i, score in enumerate(scores[:5])],
                    confidence=1.0 - (mean_score / 5.0),
                    suggested_gap_id="gap_answer_quality",
                    ts=time.time(),
                    additional_context={
                        "mean_score": mean_score,
                        "median_score": median(scores),
                        "min_score": min(scores),
                        "max_score": max(scores),
                    },
                )
                problems.append(problem)

        return problems

    def _rule_contract_violation(
        self, violations: List[ViolationSignal]
    ) -> List[ProblemReport]:
        """
        Detect: Contract violations indicate structural integrity issues.

        Heuristic: Map violation_code → affected_route based on contract semantics.
        """
        problems = []
        violations_by_code: Dict[str, List[ViolationSignal]] = defaultdict(list)

        for violation in violations:
            violations_by_code[violation.violation_code].append(violation)

        for violation_code, code_violations in violations_by_code.items():
            if len(code_violations) > 1:  # At least 2 occurrences
                # Map violation to route
                route = self._map_violation_to_route(violation_code)

                problem = ProblemReport(
                    problem_id=f"contract_{violation_code}_{int(time.time())}",
                    category=ProblemCategory.CONTRACT_VIOLATION,
                    severity=Severity.HIGH,
                    affected_route=route,
                    description=(
                        f"Contract violation: {violation_code} "
                        f"occurred {len(code_violations)} times"
                    ),
                    evidence=[v.detail for v in code_violations[:3]],
                    confidence=min(1.0, len(code_violations) / 5),
                    suggested_gap_id=f"gap_contract_{violation_code}",
                    ts=time.time(),
                    additional_context={
                        "violation_count": len(code_violations),
                        "violation_code": violation_code,
                    },
                )
                problems.append(problem)

        return problems

    def _rule_repeat_questions(
        self, repeats: List[RepeatQuestionSignal]
    ) -> Optional[ProblemReport]:
        """
        Detect: User asking similar questions → system lacks diversity or self-learning.

        Heuristic: If repeat_count > threshold, it's a robustness issue.
        """
        if len(repeats) <= self.REPEAT_QUESTION_THRESHOLD:
            return None

        # Analyze repeat patterns
        avg_similarity = mean([r.similarity_score for r in repeats])

        problem = ProblemReport(
            problem_id=f"repeat_questions_{int(time.time())}",
            category=ProblemCategory.DIVERSITY_ISSUE,
            severity=Severity.MEDIUM,
            affected_route="R3_planner_examples",  # Planner should avoid repetition
            description=(
                f"User repeating questions: {len(repeats)} similar questions detected, "
                f"avg similarity={avg_similarity:.2f}"
            ),
            evidence=[
                f"Repeat #{i + 1}: turn {r.original_turn} → turn {r.repeat_turn} "
                f"(similarity={r.similarity_score:.2f})"
                for i, r in enumerate(repeats[:3])
            ],
            confidence=min(1.0, len(repeats) / 10),
            suggested_gap_id="gap_question_diversity",
            ts=time.time(),
            additional_context={
                "repeat_count": len(repeats),
                "avg_similarity": avg_similarity,
                "sessions_affected": len(set(r.session_id for r in repeats)),
            },
        )
        return problem

    def _rule_topology_anomaly(
        self, anomalies: List[TopoAnomalySignal]
    ) -> List[ProblemReport]:
        """
        Detect: Topology anomalies → dead code paths or architectural issues.

        Heuristic: Stale edges suggest unused code; spike edges suggest bottlenecks.
        """
        problems = []

        for anomaly in anomalies:
            if anomaly.anomaly_type == "stale":
                problem = ProblemReport(
                    problem_id=f"stale_edge_{anomaly.edge_id.replace('->', '_')}_{int(time.time())}",
                    category=ProblemCategory.TOPO_ANOMALY,
                    severity=Severity.LOW,
                    affected_route="R1_navigator_dict",  # Generic fallback
                    description=f"Stale topology edge: {anomaly.edge_id} (not traversed recently)",
                    evidence=[f"Edge: {anomaly.edge_id}", f"Metrics: {anomaly.metrics}"],
                    confidence=0.6,
                    suggested_gap_id=f"gap_dead_code_{anomaly.edge_id}",
                    ts=time.time(),
                    additional_context=anomaly.metrics,
                )
                problems.append(problem)

            elif anomaly.anomaly_type == "spike":
                problem = ProblemReport(
                    problem_id=f"spike_edge_{anomaly.edge_id.replace('->', '_')}_{int(time.time())}",
                    category=ProblemCategory.TOPO_ANOMALY,
                    severity=Severity.MEDIUM,
                    affected_route="R5_tool_priority",  # Tool selection bottleneck
                    description=f"Topology spike: {anomaly.edge_id} is heavily traversed (potential bottleneck)",
                    evidence=[f"Edge: {anomaly.edge_id}", f"High traversal count: {anomaly.metrics.get('traversal_count', 'N/A')}"],
                    confidence=0.7,
                    suggested_gap_id=f"gap_bottleneck_{anomaly.edge_id}",
                    ts=time.time(),
                    additional_context=anomaly.metrics,
                )
                problems.append(problem)

        return problems

    def _extract_common_context(self, contexts: List[Dict]) -> Dict:
        """Extract common fields from failure contexts."""
        if not contexts:
            return {}

        common = {}
        # Get first context as baseline
        for key in contexts[0]:
            values = [c.get(key) for c in contexts]
            # If all values are the same, it's common
            if all(v == values[0] for v in values):
                common[key] = values[0]

        return common

    def _map_tag_to_route(self, tag: str) -> str:
        """Map feedback tag to affected route."""
        tag_lower = tag.lower()
        if "数据" in tag_lower or "outdated" in tag_lower:
            return "R2_path_default"
        elif "逻辑" in tag_lower or "logic" in tag_lower:
            return "R1_navigator_dict"
        elif "工具" in tag_lower or "tool" in tag_lower:
            return "R5_tool_priority"
        elif "排序" in tag_lower or "rank" in tag_lower:
            return "R4_rerank_weights"
        else:
            return "R3_planner_examples"

    def _map_violation_to_route(self, violation_code: str) -> str:
        """Map violation code to affected route."""
        code_lower = violation_code.lower()
        if "nav" in code_lower or "router" in code_lower:
            return "R1_navigator_dict"
        elif "path" in code_lower or "constraint" in code_lower:
            return "R2_path_default"
        elif "plan" in code_lower or "example" in code_lower:
            return "R3_planner_examples"
        elif "rank" in code_lower or "weight" in code_lower:
            return "R4_rerank_weights"
        elif "tool" in code_lower or "priority" in code_lower:
            return "R5_tool_priority"
        else:
            return "R1_navigator_dict"

    def _deduplicate_problems(
        self, problems: List[ProblemReport]
    ) -> List[ProblemReport]:
        """
        Deduplicate problems: same route + category → keep highest confidence.
        """
        seen: Dict[tuple, ProblemReport] = {}
        for problem in problems:
            key = (problem.affected_route, problem.category)
            if key not in seen or problem.confidence > seen[key].confidence:
                seen[key] = problem
        return list(seen.values())
