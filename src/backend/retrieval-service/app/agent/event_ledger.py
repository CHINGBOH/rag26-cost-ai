"""
Canonical event and projection writes for interaction runs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from psycopg2.extras import Json

from app.agent.event_builders import (
    build_improvement_event_payload,
    build_interaction_terminal_payload,
    build_knowledge_gap_payload,
    build_learning_run_payload,
    build_projection_reconcile_payload,
    collect_tools_used,
)
from app.agent.outcome_classifier import classify_interaction_outcome
from app.agent.projections.agent_run_projection import upsert_agent_run_projection
from app.agent.projections.conversation_turns_projection import insert_conversation_turn
from app.agent.run_context import RunContext
from app.agent.tools import _get_pg_conn, _put_pg_conn

def record_interaction_run_terminal(
    *,
    run_context: RunContext,
    query_type: str,
    final_answer: str,
    evaluation: Optional[dict[str, Any]],
    runtime: Optional[dict[str, Any]],
    chunks: Optional[list[dict[str, Any]]],
    iterations: int,
    messages: Optional[list[Any]] = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    completed_at = datetime.now(timezone.utc)
    outcome = classify_interaction_outcome(
        query_type=query_type,
        final_answer=final_answer,
        evaluation=evaluation,
        chunks=chunks,
        error_message=error_message,
    )
    payload = build_interaction_terminal_payload(
        run_context=run_context,
        query_type=query_type,
        final_answer=final_answer,
        evaluation=evaluation,
        runtime=runtime,
        chunks=chunks,
        iterations=iterations,
        tools_used=collect_tools_used(messages),
        outcome=outcome,
        completed_at=completed_at,
        error_message=error_message,
    )

    conn = None
    error = False
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO event_ledger (
                    aggregate_type, aggregate_id, event_type, run_id, session_id,
                    request_id, trace_id, channel, actor_service, actor_kind,
                    outcome_family, outcome_code, quality, learning_eligible,
                    payload, occurred_at, idempotency_key, schema_version,
                    topology_version, policy_version, prompt_version
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s
                )
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                (
                    "interaction_run",
                    run_context.run_id,
                    "interaction.run.terminal",
                    run_context.run_id,
                    run_context.session_id,
                    run_context.request_id,
                    run_context.trace_id,
                    run_context.channel,
                    "retrieval-service",
                    "agent_api",
                    payload["outcome_family"],
                    payload["outcome_code"],
                    payload["quality"],
                    bool(payload["learning_eligible"]),
                    Json(payload),
                    completed_at,
                    f"interaction-terminal:{run_context.run_id}",
                    "phase6.v1",
                    "phase6.v1",
                    "phase6.v1",
                    "phase6.v1",
                ),
            )
            upsert_agent_run_projection(cur, payload)
            insert_conversation_turn(cur, payload)
        conn.commit()
    except Exception:
        error = True
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            _put_pg_conn(conn, error=error)

    return payload


def insert_learning_run_event(
    cur: Any,
    *,
    run_id: str,
    run_type: str,
    status: str,
    event_type: str,
    result: Optional[dict[str, Any]] = None,
    occurred_at: Optional[datetime] = None,
) -> dict[str, Any]:
    event_at = occurred_at or datetime.now(timezone.utc)
    payload = build_learning_run_payload(
        run_id=run_id,
        run_type=run_type,
        status=status,
        event_type=event_type,
        result=result,
        occurred_at=event_at,
    )
    outcome_family = status if status in {"completed", "failed"} else None
    outcome_code = event_type.replace(".", "_").upper()
    cur.execute(
        """
        INSERT INTO event_ledger (
            aggregate_type, aggregate_id, event_type, run_id, session_id,
            request_id, trace_id, channel, actor_service, actor_kind,
            outcome_family, outcome_code, quality, learning_eligible,
            payload, occurred_at, idempotency_key, schema_version,
            topology_version, policy_version, prompt_version
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s
        )
        ON CONFLICT (idempotency_key) DO NOTHING
        """,
        (
            "learning_run",
            run_id,
            event_type,
            run_id,
            None,
            None,
            run_id,
            run_type,
            "retrieval-service",
            "learning_scheduler",
            outcome_family,
            outcome_code,
            None,
            False,
            Json(payload),
            event_at,
            f"{event_type}:{run_id}",
            "phase6.v1",
            "phase6.v1",
            "phase6.v1",
            "phase6.v1",
        ),
    )
    return payload


def insert_improvement_event(
    cur: Any,
    *,
    event_id: int,
    patch_id: str,
    affected_route: str,
    patch_type: str,
    status: str,
    event_type: str,
    gap_key: str | None = None,
    verification_result: Optional[dict[str, Any]] = None,
    recovery_point: str | None = None,
    occurred_at: Optional[datetime] = None,
) -> dict[str, Any]:
    event_at = occurred_at or datetime.now(timezone.utc)
    payload = build_improvement_event_payload(
        event_id=event_id,
        patch_id=patch_id,
        affected_route=affected_route,
        patch_type=patch_type,
        status=status,
        event_type=event_type,
        gap_key=gap_key,
        verification_result=verification_result,
        recovery_point=recovery_point,
        occurred_at=event_at,
    )
    cur.execute(
        """
        INSERT INTO event_ledger (
            aggregate_type, aggregate_id, event_type, run_id, session_id,
            request_id, trace_id, channel, actor_service, actor_kind,
            outcome_family, outcome_code, quality, learning_eligible,
            payload, occurred_at, idempotency_key, schema_version,
            topology_version, policy_version, prompt_version
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s
        )
        ON CONFLICT (idempotency_key) DO NOTHING
        """,
        (
            "improvement_event",
            str(event_id),
            event_type,
            None,
            None,
            None,
            patch_id,
            affected_route,
            "retrieval-service",
            "auto_executor",
            status,
            event_type.replace(".", "_").upper(),
            None,
            False,
            Json(payload),
            event_at,
            f"{event_type}:{event_id}",
            "phase6.v1",
            "phase6.v1",
            "phase6.v1",
            "phase6.v1",
        ),
    )
    return payload


def insert_knowledge_gap_event(
    cur: Any,
    *,
    gap_key: str,
    event_type: str,
    snapshot: dict[str, Any],
    occurred_at: Optional[datetime] = None,
) -> dict[str, Any]:
    event_at = occurred_at or datetime.now(timezone.utc)
    payload = build_knowledge_gap_payload(
        snapshot=snapshot,
        event_type=event_type,
        occurred_at=event_at,
    )
    cur.execute(
        """
        INSERT INTO event_ledger (
            aggregate_type, aggregate_id, event_type, run_id, session_id,
            request_id, trace_id, channel, actor_service, actor_kind,
            outcome_family, outcome_code, quality, learning_eligible,
            payload, occurred_at, idempotency_key, schema_version,
            topology_version, policy_version, prompt_version
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s
        )
        ON CONFLICT (idempotency_key) DO NOTHING
        """,
        (
            "knowledge_gap",
            gap_key,
            event_type,
            None,
            None,
            None,
            gap_key,
            snapshot.get("source"),
            "retrieval-service",
            "learning_state",
            snapshot.get("status"),
            event_type.replace(".", "_").upper(),
            snapshot.get("quality"),
            False,
            Json(payload),
            event_at,
            f"{event_type}:{gap_key}:{int(event_at.timestamp() * 1000)}",
            "phase8.v1",
            "phase8.v1",
            "phase8.v1",
            "phase8.v1",
        ),
    )
    return payload


def record_projection_reconcile_event(
    *,
    run_id: str | None,
    summary: dict[str, Any],
) -> dict[str, Any]:
    event_at = datetime.now(timezone.utc)
    aggregate_id = run_id or "global"
    remaining_drift_count = int(summary.get("remaining_drift_count") or 0)
    payload = build_projection_reconcile_payload(
        run_id=run_id,
        summary=summary,
        occurred_at=event_at,
    )

    conn = None
    error = False
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO event_ledger (
                    aggregate_type, aggregate_id, event_type, run_id, session_id,
                    request_id, trace_id, channel, actor_service, actor_kind,
                    outcome_family, outcome_code, quality, learning_eligible,
                    payload, occurred_at, idempotency_key, schema_version,
                    topology_version, policy_version, prompt_version
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s
                )
                """,
                (
                    "projection_reconcile",
                    aggregate_id,
                    "projection.reconcile.completed",
                    run_id,
                    None,
                    None,
                    aggregate_id,
                    "learning_api",
                    "retrieval-service",
                    "learning_api",
                    "completed" if remaining_drift_count == 0 else "partial",
                    "PROJECTION_RECONCILE_COMPLETED",
                    None,
                    False,
                    Json(payload),
                    event_at,
                    f"projection-reconcile:{aggregate_id}:{int(event_at.timestamp() * 1000)}",
                    "phase6.v1",
                    "phase6.v1",
                    "phase6.v1",
                    "phase6.v1",
                ),
            )
        conn.commit()
    except Exception:
        error = True
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            _put_pg_conn(conn, error=error)

    return payload


def record_tool_execution(
    *,
    audit_id: str,
    adapter: str,
    language: str,
    validation_level: str,
    verdict: str,
    inferred_failure_kind: Optional[str],
    wall_time_ms: float,
) -> None:
    """
    Write a tool_execution sub-event to event_ledger.
    Consumed by #167 Tool Guardrails (via audit_id) and #166 ERRORS.md (via inferred_failure_kind).
    """
    event_at = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "audit_id": audit_id,
        "adapter": adapter,
        "language": language,
        "validation_level": validation_level,
        "verdict": verdict,
        "inferred_failure_kind": inferred_failure_kind,
        "wall_time_ms": round(wall_time_ms, 2),
        "occurred_at": event_at.isoformat(),
    }
    outcome_family = "completed" if verdict == "clean" else "failed"
    outcome_code = f"TOOL_EXEC_{verdict.upper()}"

    conn = None
    error = False
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO event_ledger (
                    aggregate_type, aggregate_id, event_type, run_id, session_id,
                    request_id, trace_id, channel, actor_service, actor_kind,
                    outcome_family, outcome_code, quality, learning_eligible,
                    payload, occurred_at, idempotency_key, schema_version,
                    topology_version, policy_version, prompt_version
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s
                )
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                (
                    "tool_execution",
                    audit_id,
                    "tool.execution.completed",
                    None,
                    None,
                    None,
                    audit_id,
                    "agent_api",
                    "retrieval-service",
                    "code_pipeline",
                    outcome_family,
                    outcome_code,
                    None,
                    False,
                    Json(payload),
                    event_at,
                    f"tool-execution:{audit_id}",
                    "phase9.v1",
                    "phase9.v1",
                    "phase9.v1",
                    "phase9.v1",
                ),
            )
        conn.commit()
    except Exception:
        error = True
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            _put_pg_conn(conn, error=error)
