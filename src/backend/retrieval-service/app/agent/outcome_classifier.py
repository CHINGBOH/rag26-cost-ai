"""
Classify interaction terminal outcomes into canonical Phase 6 taxonomy.
"""

from __future__ import annotations

from typing import Any, Iterable

from app.agent.event_taxonomy import NON_TASK_QUERY_TYPES, REFUSAL_MARKERS, RunOutcome


def _contains_refusal(text: str) -> bool:
    answer = str(text or "")
    return any(marker in answer for marker in REFUSAL_MARKERS)


def _chunks_count(chunks: Iterable[Any] | None) -> int:
    return len(list(chunks or []))


def _failed_code(error_message: str) -> str:
    message = str(error_message or "").lower()
    if "timeout" in message or "超时" in message:
        return "FAILED_TIMEOUT"
    if "tool" in message:
        return "FAILED_TOOL"
    return "FAILED_INTERNAL"


def classify_interaction_outcome(
    *,
    query_type: str,
    final_answer: str,
    evaluation: dict[str, Any] | None,
    chunks: Iterable[Any] | None,
    error_message: str | None = None,
) -> RunOutcome:
    normalized_query_type = str(query_type or "").strip().lower()
    ev = evaluation or {}
    confidence = float(ev.get("confidence", 0) or 0)
    info_gain = float(ev.get("information_gain", 0) or 0)
    chunk_count = _chunks_count(chunks)

    if error_message:
        return RunOutcome(
            outcome_family="failed",
            outcome_code=_failed_code(error_message),
            quality="failure",
            learning_eligible=True,
            status="error",
        )

    if normalized_query_type in NON_TASK_QUERY_TYPES:
        code = "EARLY_EXIT_CHITCHAT" if normalized_query_type == "chitchat" else "EARLY_EXIT_IRRELEVANT"
        return RunOutcome(
            outcome_family="non_task",
            outcome_code=code,
            quality="non_task",
            learning_eligible=False,
            early_exit=True,
        )

    refused = _contains_refusal(final_answer)
    if refused or chunk_count == 0:
        return RunOutcome(
            outcome_family="refused",
            outcome_code="REFUSED_INSUFFICIENT_EVIDENCE",
            quality="failure",
            learning_eligible=True,
            refused=True,
        )

    if confidence < 0.5 or info_gain < 0.3:
        return RunOutcome(
            outcome_family="answered",
            outcome_code="ANSWERED_WEAK_EVIDENCE",
            quality="weak",
            learning_eligible=True,
        )

    return RunOutcome(
        outcome_family="answered",
        outcome_code="ANSWERED_OK",
        quality="good",
        learning_eligible=True,
    )
