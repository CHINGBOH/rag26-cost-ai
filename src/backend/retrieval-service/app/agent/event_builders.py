"""
Helpers for building canonical event and projection payloads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from app.agent.event_taxonomy import RunOutcome
from app.agent.run_context import RunContext


def collect_tools_used(messages: Iterable[Any] | None) -> list[str]:
    tools_used: list[str] = []
    for message in messages or []:
        tool_name = getattr(message, "name", None)
        if tool_name and tool_name not in tools_used:
            tools_used.append(tool_name)
    return tools_used


def build_interaction_terminal_payload(
    *,
    run_context: RunContext,
    query_type: str,
    final_answer: str,
    evaluation: dict[str, Any] | None,
    runtime: dict[str, Any] | None,
    chunks: list[dict[str, Any]] | None,
    iterations: int,
    tools_used: list[str] | None,
    outcome: RunOutcome,
    completed_at: datetime,
    error_message: str | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run_context.run_id,
        "session_id": run_context.session_id,
        "request_id": run_context.request_id,
        "trace_id": run_context.trace_id,
        "channel": run_context.channel,
        "query": run_context.query,
        "query_type": query_type or "",
        "answer": final_answer or "",
        "iterations": int(iterations or 0),
        "chunks_count": len(chunks or []),
        "tools_used": tools_used or [],
        "evaluation": evaluation or {},
        "runtime": runtime or {},
        "outcome_family": outcome.outcome_family,
        "outcome_code": outcome.outcome_code,
        "quality": outcome.quality,
        "learning_eligible": outcome.learning_eligible,
        "refused": outcome.refused,
        "early_exit": outcome.early_exit,
        "status": outcome.status,
        "started_at": run_context.started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "latency_ms": max(0, int((completed_at - run_context.started_at).total_seconds() * 1000)),
        "error_message": error_message,
    }

def build_learning_run_payload(
    *,
    run_id: str,
    run_type: str,
    status: str,
    event_type: str,
    result: dict[str, Any] | None,
    occurred_at: datetime,
) -> dict[str, Any]:
    normalized_result = result or {}
    return {
        "run_id": run_id,
        "run_type": run_type,
        "status": status,
        "event_type": event_type,
        "result": normalized_result,
        "signal_summary": normalized_result.get("signal_summary") or {},
        "problems_count": int(normalized_result.get("problems_count") or 0),
        "severity_score": float(normalized_result.get("severity_score") or 0.0),
        "error": normalized_result.get("error"),
        "reason": normalized_result.get("reason"),
        "occurred_at": occurred_at.isoformat(),
    }


def build_improvement_event_payload(
    *,
    event_id: int,
    patch_id: str,
    affected_route: str,
    patch_type: str,
    status: str,
    event_type: str,
    gap_key: str | None,
    verification_result: dict[str, Any] | None,
    recovery_point: str | None,
    occurred_at: datetime,
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "patch_id": patch_id,
        "affected_route": affected_route,
        "patch_type": patch_type,
        "status": status,
        "event_type": event_type,
        "gap_key": gap_key,
        "verification_result": verification_result or {},
        "recovery_point": recovery_point,
        "occurred_at": occurred_at.isoformat(),
    }


def build_projection_reconcile_payload(
    *,
    run_id: str | None,
    summary: dict[str, Any],
    occurred_at: datetime,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "scope": "run" if run_id else "global",
        "rebuilt_total": int(summary.get("rebuilt_total") or 0),
        "remaining_drift_count": int(summary.get("remaining_drift_count") or 0),
        "projections": summary.get("projections") or {},
        "occurred_at": occurred_at.isoformat(),
    }


def build_knowledge_gap_payload(
    *,
    snapshot: dict[str, Any],
    event_type: str,
    occurred_at: datetime,
) -> dict[str, Any]:
    def _serialize(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    payload = {key: _serialize(value) for key, value in snapshot.items()}
    payload["event_type"] = event_type
    payload["occurred_at"] = occurred_at.isoformat()
    return payload
