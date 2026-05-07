"""
Projection rebuild helpers for canonical event-ledger rollouts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from psycopg2.extras import Json

from app.agent.learning_state import coerce_json_dict, normalize_epoch_milliseconds
from app.agent.tools import _get_pg_conn, _put_pg_conn


def _coerce_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except Exception:
            return []
        if isinstance(loaded, list):
            return loaded
    return []


def _fetch_latest_learning_run_event_rows(cur: Any, *, run_id: Optional[str] = None) -> list[tuple[Any, Any, Any]]:
    if run_id:
        cur.execute(
            """
            SELECT run_id, payload, occurred_at
            FROM (
                SELECT DISTINCT ON (run_id)
                    run_id, payload, occurred_at, event_id
                FROM event_ledger
                WHERE aggregate_type = 'learning_run'
                  AND run_id = %s
                ORDER BY run_id, occurred_at DESC, event_id DESC
            ) latest
            """,
            (run_id,),
        )
    else:
        cur.execute(
            """
            SELECT run_id, payload, occurred_at
            FROM (
                SELECT DISTINCT ON (run_id)
                    run_id, payload, occurred_at, event_id
                FROM event_ledger
                WHERE aggregate_type = 'learning_run'
                ORDER BY run_id, occurred_at DESC, event_id DESC
            ) latest
            ORDER BY occurred_at DESC
            """
        )
    return list(cur.fetchall())


def _fetch_latest_interaction_run_event_rows(
    cur: Any, *, run_id: Optional[str] = None, session_id: Optional[str] = None
) -> list[tuple[Any, Any, Any]]:
    if run_id:
        cur.execute(
            """
            SELECT run_id, payload, occurred_at
            FROM (
                SELECT DISTINCT ON (run_id)
                    run_id, payload, occurred_at, event_id
                FROM event_ledger
                WHERE aggregate_type = 'interaction_run'
                  AND event_type = 'interaction.run.terminal'
                  AND run_id = %s
                ORDER BY run_id, occurred_at DESC, event_id DESC
            ) latest
            """,
            (run_id,),
        )
    elif session_id:
        cur.execute(
            """
            SELECT run_id, payload, occurred_at
            FROM (
                SELECT DISTINCT ON (run_id)
                    run_id, payload, occurred_at, event_id
                FROM event_ledger
                WHERE aggregate_type = 'interaction_run'
                  AND event_type = 'interaction.run.terminal'
                  AND session_id = %s
                ORDER BY run_id, occurred_at DESC, event_id DESC
            ) latest
            ORDER BY occurred_at DESC
            """,
            (session_id,),
        )
    else:
        cur.execute(
            """
            SELECT run_id, payload, occurred_at
            FROM (
                SELECT DISTINCT ON (run_id)
                    run_id, payload, occurred_at, event_id
                FROM event_ledger
                WHERE aggregate_type = 'interaction_run'
                  AND event_type = 'interaction.run.terminal'
                ORDER BY run_id, occurred_at DESC, event_id DESC
            ) latest
            ORDER BY occurred_at DESC
            """
        )
    return list(cur.fetchall())


def _resolve_interaction_session_id(cur: Any, run_id: str) -> Optional[str]:
    cur.execute(
        """
        SELECT session_id
        FROM event_ledger
        WHERE aggregate_type = 'interaction_run'
          AND event_type = 'interaction.run.terminal'
          AND run_id = %s
        ORDER BY occurred_at DESC, event_id DESC
        LIMIT 1
        """,
        (run_id,),
    )
    row = cur.fetchone()
    if not row or not row[0]:
        return None
    return str(row[0])


def _build_learning_run_projection_rows(rows: list[tuple[Any, Any, Any]]) -> list[dict[str, Any]]:
    projection_rows: list[dict[str, Any]] = []
    for run_id, payload_value, occurred_at in rows:
        payload = coerce_json_dict(payload_value)
        result = coerce_json_dict(payload.get("result"))
        run_type = str(payload.get("run_type") or "").strip()
        status = str(payload.get("status") or result.get("status") or "").strip()
        if not run_id or not run_type or not status:
            continue
        projection_rows.append(
            {
                "run_id": str(run_id),
                "run_type": run_type,
                "result": result,
                "status": status,
                "ts": occurred_at if isinstance(occurred_at, datetime) else datetime.now(timezone.utc),
            }
        )
    return projection_rows


def _build_conversation_turn_projection_rows(
    rows: list[tuple[Any, Any, Any]], *, base_turn_indexes: Optional[dict[str, int]] = None
) -> list[dict[str, Any]]:
    grouped_rows: dict[str, list[dict[str, Any]]] = {}
    for run_id, payload_value, occurred_at in rows:
        payload = coerce_json_dict(payload_value)
        session_id = str(payload.get("session_id") or "").strip()
        request_id = payload.get("request_id")
        if not run_id or not session_id or not request_id:
            continue
        completed_at = payload.get("completed_at") or occurred_at
        grouped_rows.setdefault(session_id, []).append(
            {
                "run_id": str(run_id),
                "session_id": session_id,
                "user_content": str(payload.get("query") or "").strip(),
                "assistant_content": str(payload.get("answer") or payload.get("error_message") or ""),
                "message_id": request_id,
                "source": "agent",
                "status": str(payload.get("status") or "completed").strip() or "completed",
                "latency_ms": int(payload.get("latency_ms") or 0),
                "channel": str(payload.get("channel") or "").strip(),
                "outcome_code": str(payload.get("outcome_code") or "").strip(),
                "quality": str(payload.get("quality") or "").strip(),
                "early_exit": bool(payload.get("early_exit")),
                "ts": normalize_epoch_milliseconds(completed_at),
                "created_at": completed_at,
            }
        )

    projection_rows: list[dict[str, Any]] = []
    offsets = base_turn_indexes or {}
    for session_id, session_rows in grouped_rows.items():
        session_rows.sort(key=lambda row: (row.get("ts") or 0, row["run_id"]))
        base_turn_index = int(offsets.get(session_id) or 0)
        for index, row in enumerate(session_rows, start=1):
            projection_rows.append(
                {
                    **row,
                    "turn_index": base_turn_index + index,
                }
            )
    return projection_rows


def _build_agent_run_projection_rows(rows: list[tuple[Any, Any, Any]]) -> list[dict[str, Any]]:
    projection_rows: list[dict[str, Any]] = []
    for run_id, payload_value, occurred_at in rows:
        payload = coerce_json_dict(payload_value)
        query = str(payload.get("query") or "").strip()
        channel = str(payload.get("channel") or "").strip()
        status = str(payload.get("status") or "").strip()
        outcome_family = str(payload.get("outcome_family") or "").strip()
        outcome_code = str(payload.get("outcome_code") or "").strip()
        quality = str(payload.get("quality") or "").strip()
        if not run_id or not query or not channel or not status or not outcome_family or not outcome_code or not quality:
            continue
        answer_preview = str(payload.get("answer") or payload.get("error_message") or "")[:500]
        projection_rows.append(
            {
                "run_id": str(run_id),
                "session_id": payload.get("session_id"),
                "query": query,
                "query_type": str(payload.get("query_type") or "").strip(),
                "channel": channel,
                "status": status,
                "outcome_family": outcome_family,
                "outcome_code": outcome_code,
                "quality": quality,
                "learning_eligible": bool(payload.get("learning_eligible")),
                "early_exit": bool(payload.get("early_exit")),
                "refused": bool(payload.get("refused")),
                "iterations": int(payload.get("iterations") or 0),
                "chunks_count": int(payload.get("chunks_count") or 0),
                "tools_used": _coerce_json_list(payload.get("tools_used")),
                "evaluation": coerce_json_dict(payload.get("evaluation")),
                "runtime": coerce_json_dict(payload.get("runtime")),
                "answer_preview": answer_preview,
                "request_id": payload.get("request_id"),
                "trace_id": payload.get("trace_id"),
                "started_at": payload.get("started_at"),
                "completed_at": payload.get("completed_at") or occurred_at,
                "latency_ms": int(payload.get("latency_ms") or 0),
            }
        )
    return projection_rows


def _fetch_learning_runs_projection_rows(cur: Any, *, run_id: Optional[str] = None) -> list[dict[str, Any]]:
    if run_id:
        cur.execute(
            """
            SELECT run_id, run_type, result, status, ts
            FROM learning_runs
            WHERE run_id = %s
            """,
            (run_id,),
        )
    else:
        cur.execute(
            """
            SELECT run_id, run_type, result, status, ts
            FROM learning_runs
            ORDER BY ts DESC
            """
        )
    return [
        {
            "run_id": str(row[0]),
            "run_type": str(row[1] or "").strip(),
            "result": coerce_json_dict(row[2]),
            "status": str(row[3] or "").strip(),
            "ts": row[4] if isinstance(row[4], datetime) else datetime.now(timezone.utc),
        }
        for row in cur.fetchall()
        if row[0]
    ]


def _fetch_agent_run_projection_rows(cur: Any, *, run_id: Optional[str] = None) -> list[dict[str, Any]]:
    if run_id:
        cur.execute(
            """
            SELECT
                run_id, session_id, query, query_type, channel, status,
                outcome_family, outcome_code, quality, learning_eligible,
                early_exit, refused, iterations, chunks_count, tools_used,
                evaluation, runtime, answer_preview, request_id, trace_id,
                started_at, completed_at, latency_ms
            FROM agent_run_projection
            WHERE run_id = %s
            """,
            (run_id,),
        )
    else:
        cur.execute(
            """
            SELECT
                run_id, session_id, query, query_type, channel, status,
                outcome_family, outcome_code, quality, learning_eligible,
                early_exit, refused, iterations, chunks_count, tools_used,
                evaluation, runtime, answer_preview, request_id, trace_id,
                started_at, completed_at, latency_ms
            FROM agent_run_projection
            ORDER BY completed_at DESC
            """
        )
    return [
        {
            "run_id": str(row[0]),
            "session_id": row[1],
            "query": str(row[2] or "").strip(),
            "query_type": str(row[3] or "").strip(),
            "channel": str(row[4] or "").strip(),
            "status": str(row[5] or "").strip(),
            "outcome_family": str(row[6] or "").strip(),
            "outcome_code": str(row[7] or "").strip(),
            "quality": str(row[8] or "").strip(),
            "learning_eligible": bool(row[9]),
            "early_exit": bool(row[10]),
            "refused": bool(row[11]),
            "iterations": int(row[12] or 0),
            "chunks_count": int(row[13] or 0),
            "tools_used": _coerce_json_list(row[14]),
            "evaluation": coerce_json_dict(row[15]),
            "runtime": coerce_json_dict(row[16]),
            "answer_preview": str(row[17] or ""),
            "request_id": row[18],
            "trace_id": row[19],
            "started_at": row[20],
            "completed_at": row[21],
            "latency_ms": int(row[22] or 0),
        }
        for row in cur.fetchall()
        if row[0]
    ]


def _fetch_conversation_turn_base_offsets(cur: Any, *, session_ids: list[str]) -> dict[str, int]:
    if not session_ids:
        return {}
    cur.execute(
        """
        SELECT session_id, COALESCE(MAX(turn_index), 0)
        FROM conversation_turns
        WHERE session_id = ANY(%s)
          AND run_id IS NULL
        GROUP BY session_id
        """,
        (session_ids,),
    )
    return {str(row[0]): int(row[1] or 0) for row in cur.fetchall() if row and row[0]}


def _fetch_conversation_turn_projection_rows(
    cur: Any, *, session_id: Optional[str] = None
) -> list[dict[str, Any]]:
    if session_id:
        cur.execute(
            """
            SELECT
                session_id, turn_index, user_content, assistant_content, message_id,
                source, status, latency_ms, run_id, channel, outcome_code, quality,
                early_exit, ts
            FROM conversation_turns
            WHERE session_id = %s
              AND run_id IS NOT NULL
            ORDER BY turn_index ASC
            """,
            (session_id,),
        )
    else:
        cur.execute(
            """
            SELECT
                session_id, turn_index, user_content, assistant_content, message_id,
                source, status, latency_ms, run_id, channel, outcome_code, quality,
                early_exit, ts
            FROM conversation_turns
            WHERE run_id IS NOT NULL
            ORDER BY session_id ASC, turn_index ASC
            """
        )
    return [
        {
            "session_id": str(row[0] or "").strip(),
            "turn_index": int(row[1] or 0),
            "user_content": str(row[2] or ""),
            "assistant_content": str(row[3] or ""),
            "message_id": row[4],
            "source": str(row[5] or "").strip(),
            "status": str(row[6] or "").strip(),
            "latency_ms": int(row[7] or 0),
            "run_id": str(row[8]),
            "channel": str(row[9] or "").strip(),
            "outcome_code": str(row[10] or "").strip(),
            "quality": str(row[11] or "").strip(),
            "early_exit": bool(row[12]),
            "ts": normalize_epoch_milliseconds(row[13]),
        }
        for row in cur.fetchall()
        if row[8]
    ]


def _fetch_latest_knowledge_gap_event_rows(cur: Any) -> list[tuple[Any, Any, Any]]:
    cur.execute(
        """
        SELECT aggregate_id, payload, occurred_at
        FROM (
            SELECT DISTINCT ON (aggregate_id)
                aggregate_id, payload, occurred_at, event_id
            FROM event_ledger
            WHERE aggregate_type = 'knowledge_gap'
            ORDER BY aggregate_id, occurred_at DESC, event_id DESC
        ) latest
        ORDER BY occurred_at DESC
        """
    )
    return list(cur.fetchall())


def _build_knowledge_gap_projection_rows(rows: list[tuple[Any, Any, Any]]) -> list[dict[str, Any]]:
    projection_rows: list[dict[str, Any]] = []
    for gap_key, payload_value, _ in rows:
        payload = coerce_json_dict(payload_value)
        current_gap_key = str(payload.get("gap_key") or gap_key or "").strip()
        status = str(payload.get("status") or "").strip()
        source = str(payload.get("source") or "").strip()
        if not current_gap_key or not status or not source:
            continue
        projection_rows.append(
            {
                "gap_key": current_gap_key,
                "problem_id": payload.get("problem_id"),
                "description": str(payload.get("description") or current_gap_key),
                "source": source,
                "affected_route": payload.get("affected_route"),
                "query_text": payload.get("query_text"),
                "status": status,
                "quality": str(payload.get("quality") or "").strip(),
                "resolution_plan": payload.get("resolution_plan"),
                "confidence": float(payload.get("confidence") or 0.0),
                "metadata": coerce_json_dict(payload.get("metadata")),
                "created_at": payload.get("created_at"),
                "resolved_at": payload.get("resolved_at"),
                "verified_at": payload.get("verified_at"),
                "observation_until": payload.get("observation_until"),
                "last_reopened_at": payload.get("last_reopened_at"),
                "scope_type": payload.get("scope_type"),
                "scope_id": payload.get("scope_id"),
                "cluster_id": payload.get("cluster_id"),
                "cause_type": payload.get("cause_type"),
                "priority": int(payload.get("priority") or 0),
                "owner": payload.get("owner"),
                "reopen_count": int(payload.get("reopen_count") or 0),
                "linked_event_id": payload.get("linked_event_id"),
                "first_seen_at": payload.get("first_seen_at"),
                "last_seen_at": payload.get("last_seen_at"),
            }
        )
    return projection_rows


def _fetch_knowledge_gap_projection_rows(cur: Any, *, gap_keys: Optional[list[str]] = None) -> list[dict[str, Any]]:
    if gap_keys:
        cur.execute(
            """
            SELECT
                gap_key, problem_id, description, source, affected_route, query_text, status, quality,
                resolution_plan, confidence, metadata, created_at, resolved_at, verified_at,
                observation_until, last_reopened_at, scope_type, scope_id, cluster_id, cause_type,
                priority, owner, reopen_count, linked_event_id, first_seen_at, last_seen_at
            FROM knowledge_gaps
            WHERE gap_key = ANY(%s)
            ORDER BY updated_at DESC
            """,
            (gap_keys,),
        )
    else:
        cur.execute(
            """
            SELECT
                gap_key, problem_id, description, source, affected_route, query_text, status, quality,
                resolution_plan, confidence, metadata, created_at, resolved_at, verified_at,
                observation_until, last_reopened_at, scope_type, scope_id, cluster_id, cause_type,
                priority, owner, reopen_count, linked_event_id, first_seen_at, last_seen_at
            FROM knowledge_gaps
            ORDER BY updated_at DESC
            """
        )
    return [
        {
            "gap_key": str(row[0]),
            "problem_id": row[1],
            "description": str(row[2] or row[0]),
            "source": str(row[3] or "").strip(),
            "affected_route": row[4],
            "query_text": row[5],
            "status": str(row[6] or "").strip(),
            "quality": str(row[7] or "").strip(),
            "resolution_plan": row[8],
            "confidence": float(row[9] or 0.0),
            "metadata": coerce_json_dict(row[10]),
            "created_at": row[11],
            "resolved_at": row[12],
            "verified_at": row[13],
            "observation_until": row[14],
            "last_reopened_at": row[15],
            "scope_type": row[16],
            "scope_id": row[17],
            "cluster_id": row[18],
            "cause_type": row[19],
            "priority": int(row[20] or 0),
            "owner": row[21],
            "reopen_count": int(row[22] or 0),
            "linked_event_id": row[23],
            "first_seen_at": row[24],
            "last_seen_at": row[25],
        }
        for row in cur.fetchall()
        if row[0]
    ]


def _index_projection_rows(rows: list[dict[str, Any]], key_field: str = "run_id") -> dict[str, dict[str, Any]]:
    return {str(row[key_field]): row for row in rows if row.get(key_field)}


def _diff_learning_run_rows(ledger_row: dict[str, Any], projection_row: dict[str, Any]) -> list[str]:
    drift_fields: list[str] = []
    if ledger_row["run_type"] != projection_row["run_type"]:
        drift_fields.append("run_type")
    if ledger_row["status"] != projection_row["status"]:
        drift_fields.append("status")
    if ledger_row["result"] != projection_row["result"]:
        drift_fields.append("result")
    return drift_fields


def _diff_agent_run_rows(ledger_row: dict[str, Any], projection_row: dict[str, Any]) -> list[str]:
    drift_fields: list[str] = []
    comparable_fields = [
        "session_id",
        "query",
        "query_type",
        "channel",
        "status",
        "outcome_family",
        "outcome_code",
        "quality",
        "learning_eligible",
        "early_exit",
        "refused",
        "iterations",
        "chunks_count",
        "tools_used",
        "evaluation",
        "runtime",
        "answer_preview",
        "request_id",
        "trace_id",
        "latency_ms",
    ]
    for field in comparable_fields:
        if ledger_row[field] != projection_row[field]:
            drift_fields.append(field)

    if normalize_epoch_milliseconds(ledger_row["started_at"]) != normalize_epoch_milliseconds(
        projection_row["started_at"]
    ):
        drift_fields.append("started_at")
    if normalize_epoch_milliseconds(ledger_row["completed_at"]) != normalize_epoch_milliseconds(
        projection_row["completed_at"]
    ):
        drift_fields.append("completed_at")
    return drift_fields


def _diff_conversation_turn_rows(ledger_row: dict[str, Any], projection_row: dict[str, Any]) -> list[str]:
    drift_fields: list[str] = []
    comparable_fields = [
        "session_id",
        "turn_index",
        "user_content",
        "assistant_content",
        "message_id",
        "source",
        "status",
        "latency_ms",
        "channel",
        "outcome_code",
        "quality",
        "early_exit",
    ]
    for field in comparable_fields:
        if ledger_row[field] != projection_row[field]:
            drift_fields.append(field)
    if normalize_epoch_milliseconds(ledger_row["ts"]) != normalize_epoch_milliseconds(projection_row["ts"]):
        drift_fields.append("ts")
    return drift_fields


def _diff_knowledge_gap_rows(ledger_row: dict[str, Any], projection_row: dict[str, Any]) -> list[str]:
    drift_fields: list[str] = []
    comparable_fields = [
        "problem_id",
        "description",
        "source",
        "affected_route",
        "query_text",
        "status",
        "quality",
        "resolution_plan",
        "confidence",
        "metadata",
        "scope_type",
        "scope_id",
        "cluster_id",
        "cause_type",
        "priority",
        "owner",
        "reopen_count",
        "linked_event_id",
    ]
    for field in comparable_fields:
        if ledger_row.get(field) != projection_row.get(field):
            drift_fields.append(field)
    for field in ["created_at", "resolved_at", "verified_at", "observation_until", "last_reopened_at", "first_seen_at", "last_seen_at"]:
        if normalize_epoch_milliseconds(ledger_row.get(field)) != normalize_epoch_milliseconds(projection_row.get(field)):
            drift_fields.append(field)
    return drift_fields


def compare_learning_runs_projection(*, run_id: Optional[str] = None) -> dict[str, Any]:
    conn = None
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            ledger_rows = _build_learning_run_projection_rows(
                _fetch_latest_learning_run_event_rows(cur, run_id=run_id)
            )
            projection_rows = _fetch_learning_runs_projection_rows(cur, run_id=run_id)
    finally:
        if conn is not None:
            _put_pg_conn(conn)

    ledger_index = _index_projection_rows(ledger_rows, "run_id")
    projection_index = _index_projection_rows(projection_rows, "run_id")

    missing_in_projection = sorted(set(ledger_index) - set(projection_index))
    stale_in_projection = sorted(set(projection_index) - set(ledger_index))
    mismatches: list[dict[str, Any]] = []

    for current_run_id in sorted(set(ledger_index) & set(projection_index)):
        ledger_row = ledger_index[current_run_id]
        projection_row = projection_index[current_run_id]
        drift_fields = _diff_learning_run_rows(ledger_row, projection_row)
        if drift_fields:
            mismatches.append(
                {
                    "run_id": current_run_id,
                    "fields": drift_fields,
                    "ledger": ledger_row,
                    "projection": projection_row,
                }
            )

    return {
        "run_id": run_id,
        "ledger_count": len(ledger_rows),
        "projection_count": len(projection_rows),
        "missing_in_projection": missing_in_projection,
        "stale_in_projection": stale_in_projection,
        "mismatches": mismatches,
        "drift_count": len(missing_in_projection) + len(stale_in_projection) + len(mismatches),
    }


def compare_agent_run_projection(*, run_id: Optional[str] = None) -> dict[str, Any]:
    conn = None
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            ledger_rows = _build_agent_run_projection_rows(
                _fetch_latest_interaction_run_event_rows(cur, run_id=run_id)
            )
            projection_rows = _fetch_agent_run_projection_rows(cur, run_id=run_id)
    finally:
        if conn is not None:
            _put_pg_conn(conn)

    ledger_index = _index_projection_rows(ledger_rows, "run_id")
    projection_index = _index_projection_rows(projection_rows, "run_id")

    missing_in_projection = sorted(set(ledger_index) - set(projection_index))
    stale_in_projection = sorted(set(projection_index) - set(ledger_index))
    mismatches: list[dict[str, Any]] = []

    for current_run_id in sorted(set(ledger_index) & set(projection_index)):
        ledger_row = ledger_index[current_run_id]
        projection_row = projection_index[current_run_id]
        drift_fields = _diff_agent_run_rows(ledger_row, projection_row)
        if drift_fields:
            mismatches.append(
                {
                    "run_id": current_run_id,
                    "fields": drift_fields,
                    "ledger": ledger_row,
                    "projection": projection_row,
                }
            )

    return {
        "run_id": run_id,
        "ledger_count": len(ledger_rows),
        "projection_count": len(projection_rows),
        "missing_in_projection": missing_in_projection,
        "stale_in_projection": stale_in_projection,
        "mismatches": mismatches,
        "drift_count": len(missing_in_projection) + len(stale_in_projection) + len(mismatches),
    }


def compare_conversation_turns_projection(*, run_id: Optional[str] = None) -> dict[str, Any]:
    conn = None
    session_id: Optional[str] = None
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            if run_id:
                session_id = _resolve_interaction_session_id(cur, run_id)
            ledger_source_rows = _fetch_latest_interaction_run_event_rows(
                cur, session_id=session_id
            ) if session_id else _fetch_latest_interaction_run_event_rows(cur, run_id=run_id)
            session_ids = sorted(
                {
                    str(coerce_json_dict(payload).get("session_id") or "").strip()
                    for _, payload, _ in ledger_source_rows
                    if str(coerce_json_dict(payload).get("session_id") or "").strip()
                }
            )
            base_turn_indexes = _fetch_conversation_turn_base_offsets(cur, session_ids=session_ids)
            ledger_rows = _build_conversation_turn_projection_rows(
                ledger_source_rows,
                base_turn_indexes=base_turn_indexes,
            )
            projection_rows = _fetch_conversation_turn_projection_rows(cur, session_id=session_id)
    finally:
        if conn is not None:
            _put_pg_conn(conn)

    ledger_index = _index_projection_rows(ledger_rows, "run_id")
    projection_index = _index_projection_rows(projection_rows, "run_id")

    missing_in_projection = sorted(set(ledger_index) - set(projection_index))
    stale_in_projection = sorted(set(projection_index) - set(ledger_index))
    mismatches: list[dict[str, Any]] = []

    for current_run_id in sorted(set(ledger_index) & set(projection_index)):
        ledger_row = ledger_index[current_run_id]
        projection_row = projection_index[current_run_id]
        drift_fields = _diff_conversation_turn_rows(ledger_row, projection_row)
        if drift_fields:
            mismatches.append(
                {
                    "run_id": current_run_id,
                    "fields": drift_fields,
                    "ledger": ledger_row,
                    "projection": projection_row,
                }
            )

    return {
        "run_id": run_id,
        "session_id": session_id,
        "ledger_count": len(ledger_rows),
        "projection_count": len(projection_rows),
        "missing_in_projection": missing_in_projection,
        "stale_in_projection": stale_in_projection,
        "mismatches": mismatches,
        "drift_count": len(missing_in_projection) + len(stale_in_projection) + len(mismatches),
    }


def compare_knowledge_gaps_projection(*, run_id: Optional[str] = None) -> dict[str, Any]:
    if run_id:
        return {
            "run_id": run_id,
            "scope": "global_only",
            "ledger_count": 0,
            "projection_count": 0,
            "unmanaged_projection_count": 0,
            "missing_in_projection": [],
            "stale_in_projection": [],
            "mismatches": [],
            "drift_count": 0,
        }

    conn = None
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            ledger_rows = _build_knowledge_gap_projection_rows(_fetch_latest_knowledge_gap_event_rows(cur))
            ledger_gap_keys = [str(row["gap_key"]) for row in ledger_rows]
            projection_rows = _fetch_knowledge_gap_projection_rows(cur, gap_keys=ledger_gap_keys or None)
            unmanaged_projection_count = 0
            if ledger_gap_keys:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM knowledge_gaps
                    WHERE gap_key <> ALL(%s)
                    """,
                    (ledger_gap_keys,),
                )
                unmanaged_projection_count = int(cur.fetchone()[0] or 0)
            else:
                cur.execute("SELECT COUNT(*) FROM knowledge_gaps")
                unmanaged_projection_count = int(cur.fetchone()[0] or 0)
                projection_rows = []
    finally:
        if conn is not None:
            _put_pg_conn(conn)

    ledger_index = _index_projection_rows(ledger_rows, "gap_key")
    projection_index = _index_projection_rows(projection_rows, "gap_key")

    missing_in_projection = sorted(set(ledger_index) - set(projection_index))
    stale_in_projection = sorted(set(projection_index) - set(ledger_index))
    mismatches: list[dict[str, Any]] = []

    for current_gap_key in sorted(set(ledger_index) & set(projection_index)):
        ledger_row = ledger_index[current_gap_key]
        projection_row = projection_index[current_gap_key]
        drift_fields = _diff_knowledge_gap_rows(ledger_row, projection_row)
        if drift_fields:
            mismatches.append(
                {
                    "gap_key": current_gap_key,
                    "fields": drift_fields,
                    "ledger": ledger_row,
                    "projection": projection_row,
                }
            )

    return {
        "run_id": run_id,
        "scope": "global_only",
        "ledger_count": len(ledger_rows),
        "projection_count": len(projection_rows),
        "unmanaged_projection_count": unmanaged_projection_count,
        "missing_in_projection": missing_in_projection,
        "stale_in_projection": stale_in_projection,
        "mismatches": mismatches,
        "drift_count": len(missing_in_projection) + len(stale_in_projection) + len(mismatches),
    }


def compare_canonical_projection_drift(*, run_id: Optional[str] = None) -> dict[str, Any]:
    projections = {
        "learning_runs": compare_learning_runs_projection(run_id=run_id),
        "agent_run_projection": compare_agent_run_projection(run_id=run_id),
        "conversation_turns": compare_conversation_turns_projection(run_id=run_id),
        "knowledge_gaps": compare_knowledge_gaps_projection(run_id=run_id),
    }
    drifted_projections = [
        name for name, summary in projections.items() if int(summary.get("drift_count") or 0) > 0
    ]
    return {
        "run_id": run_id,
        "projections": projections,
        "drifted_projections": drifted_projections,
        "total_drift_count": sum(int(summary.get("drift_count") or 0) for summary in projections.values()),
    }


def _cursor_rowcount(cursor: Any) -> int:
    rowcount = getattr(cursor, "rowcount", 0)
    return rowcount if isinstance(rowcount, int) and rowcount > 0 else 0


def _delete_stale_learning_runs_projection_rows(
    cursor: Any,
    *,
    run_id: Optional[str],
    canonical_run_ids: list[str],
) -> int:
    if run_id:
        if canonical_run_ids:
            return 0
        cursor.execute("DELETE FROM learning_runs WHERE run_id = %s", (run_id,))
        return _cursor_rowcount(cursor)

    if canonical_run_ids:
        cursor.execute("DELETE FROM learning_runs WHERE NOT (run_id = ANY(%s))", (canonical_run_ids,))
    else:
        cursor.execute("DELETE FROM learning_runs")
    return _cursor_rowcount(cursor)


def rebuild_learning_runs_projection(*, run_id: Optional[str] = None) -> int:
    conn = None
    error = False
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            projection_rows = _build_learning_run_projection_rows(
                _fetch_latest_learning_run_event_rows(cur, run_id=run_id)
            )
            deleted_stale = _delete_stale_learning_runs_projection_rows(
                cur,
                run_id=run_id,
                canonical_run_ids=[row["run_id"] for row in projection_rows],
            )
            for row in projection_rows:
                cur.execute(
                    """
                    INSERT INTO learning_runs (run_id, run_type, result, status, ts)
                    VALUES (%s, %s, %s::jsonb, %s, %s)
                    ON CONFLICT(run_id) DO UPDATE
                    SET run_type = EXCLUDED.run_type,
                        result = EXCLUDED.result,
                        status = EXCLUDED.status,
                        ts = EXCLUDED.ts
                    """,
                    (row["run_id"], row["run_type"], Json(row["result"]), row["status"], row["ts"]),
                )
        conn.commit()
        return len(projection_rows) + deleted_stale
    except Exception:
        error = True
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            _put_pg_conn(conn, error=error)


def rebuild_conversation_turns_projection(*, run_id: Optional[str] = None) -> int:
    conn = None
    error = False
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            session_id = _resolve_interaction_session_id(cur, run_id) if run_id else None
            ledger_source_rows = _fetch_latest_interaction_run_event_rows(
                cur, session_id=session_id
            ) if session_id else _fetch_latest_interaction_run_event_rows(cur, run_id=run_id)
            session_ids = sorted(
                {
                    str(coerce_json_dict(payload).get("session_id") or "").strip()
                    for _, payload, _ in ledger_source_rows
                    if str(coerce_json_dict(payload).get("session_id") or "").strip()
                }
            )
            base_turn_indexes = _fetch_conversation_turn_base_offsets(cur, session_ids=session_ids)
            projection_rows = _build_conversation_turn_projection_rows(
                ledger_source_rows,
                base_turn_indexes=base_turn_indexes,
            )
            if session_id:
                cur.execute(
                    """
                    DELETE FROM conversation_turns
                    WHERE session_id = %s
                      AND run_id IS NOT NULL
                    """,
                    (session_id,),
                )
            elif run_id:
                cur.execute(
                    """
                    DELETE FROM conversation_turns
                    WHERE run_id = %s
                    """,
                    (run_id,),
                )
            else:
                cur.execute(
                    """
                    DELETE FROM conversation_turns
                    WHERE run_id IS NOT NULL
                    """
                )
            for row in projection_rows:
                cur.execute(
                    """
                    INSERT INTO conversation_turns (
                        session_id, turn_index, user_content, assistant_content,
                        message_id, source, status, latency_ms, ts, created_at,
                        run_id, channel, outcome_code, quality, early_exit
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        row["session_id"],
                        row["turn_index"],
                        row["user_content"],
                        row["assistant_content"],
                        row["message_id"],
                        row["source"],
                        row["status"],
                        row["latency_ms"],
                        (row["ts"] or 0) / 1000.0 if row.get("ts") is not None else None,
                        row["created_at"],
                        row["run_id"],
                        row["channel"],
                        row["outcome_code"],
                        row["quality"],
                        row["early_exit"],
                    ),
                )
        conn.commit()
        return len(projection_rows)
    except Exception:
        error = True
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            _put_pg_conn(conn, error=error)


def rebuild_agent_run_projection(*, run_id: Optional[str] = None) -> int:
    conn = None
    error = False
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            projection_rows = _build_agent_run_projection_rows(
                _fetch_latest_interaction_run_event_rows(cur, run_id=run_id)
            )
            for row in projection_rows:
                cur.execute(
                    """
                    INSERT INTO agent_run_projection (
                        run_id, session_id, query, query_type, channel, status,
                        outcome_family, outcome_code, quality, learning_eligible,
                        early_exit, refused, iterations, chunks_count, tools_used,
                        evaluation, runtime, answer_preview, request_id, trace_id,
                        started_at, completed_at, latency_ms, updated_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, NOW()
                    )
                    ON CONFLICT (run_id) DO UPDATE SET
                        session_id = EXCLUDED.session_id,
                        query = EXCLUDED.query,
                        query_type = EXCLUDED.query_type,
                        channel = EXCLUDED.channel,
                        status = EXCLUDED.status,
                        outcome_family = EXCLUDED.outcome_family,
                        outcome_code = EXCLUDED.outcome_code,
                        quality = EXCLUDED.quality,
                        learning_eligible = EXCLUDED.learning_eligible,
                        early_exit = EXCLUDED.early_exit,
                        refused = EXCLUDED.refused,
                        iterations = EXCLUDED.iterations,
                        chunks_count = EXCLUDED.chunks_count,
                        tools_used = EXCLUDED.tools_used,
                        evaluation = EXCLUDED.evaluation,
                        runtime = EXCLUDED.runtime,
                        answer_preview = EXCLUDED.answer_preview,
                        request_id = EXCLUDED.request_id,
                        trace_id = EXCLUDED.trace_id,
                        started_at = EXCLUDED.started_at,
                        completed_at = EXCLUDED.completed_at,
                        latency_ms = EXCLUDED.latency_ms,
                        updated_at = NOW()
                    """,
                    (
                        row["run_id"],
                        row["session_id"],
                        row["query"],
                        row["query_type"],
                        row["channel"],
                        row["status"],
                        row["outcome_family"],
                        row["outcome_code"],
                        row["quality"],
                        row["learning_eligible"],
                        row["early_exit"],
                        row["refused"],
                        row["iterations"],
                        row["chunks_count"],
                        Json(row["tools_used"]),
                        Json(row["evaluation"]),
                        Json(row["runtime"]),
                        row["answer_preview"],
                        row["request_id"],
                        row["trace_id"],
                        row["started_at"],
                        row["completed_at"],
                        row["latency_ms"],
                    ),
                )
        conn.commit()
        return len(projection_rows)
    except Exception:
        error = True
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            _put_pg_conn(conn, error=error)


def rebuild_knowledge_gaps_projection(*, run_id: Optional[str] = None) -> int:
    if run_id:
        return 0

    conn = None
    error = False
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            projection_rows = _build_knowledge_gap_projection_rows(_fetch_latest_knowledge_gap_event_rows(cur))
            managed_gap_keys = [str(row["gap_key"]) for row in projection_rows]
            if managed_gap_keys:
                cur.execute(
                    """
                    DELETE FROM knowledge_gaps
                    WHERE gap_key = ANY(%s)
                    """,
                    (managed_gap_keys,),
                )
            for row in projection_rows:
                cur.execute(
                    """
                    INSERT INTO knowledge_gaps (
                        gap_key, problem_id, description, source, affected_route, query_text, status, quality,
                        resolution_plan, confidence, metadata, created_at, updated_at, resolved_at, verified_at,
                        observation_until, last_reopened_at, scope_type, scope_id, cluster_id, cause_type,
                        priority, owner, reopen_count, linked_event_id, first_seen_at, last_seen_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s::jsonb, %s, NOW(), %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (gap_key) DO UPDATE SET
                        problem_id = EXCLUDED.problem_id,
                        description = EXCLUDED.description,
                        source = EXCLUDED.source,
                        affected_route = EXCLUDED.affected_route,
                        query_text = EXCLUDED.query_text,
                        status = EXCLUDED.status,
                        quality = EXCLUDED.quality,
                        resolution_plan = EXCLUDED.resolution_plan,
                        confidence = EXCLUDED.confidence,
                        metadata = EXCLUDED.metadata,
                        resolved_at = EXCLUDED.resolved_at,
                        verified_at = EXCLUDED.verified_at,
                        observation_until = EXCLUDED.observation_until,
                        last_reopened_at = EXCLUDED.last_reopened_at,
                        scope_type = EXCLUDED.scope_type,
                        scope_id = EXCLUDED.scope_id,
                        cluster_id = EXCLUDED.cluster_id,
                        cause_type = EXCLUDED.cause_type,
                        priority = EXCLUDED.priority,
                        owner = EXCLUDED.owner,
                        reopen_count = EXCLUDED.reopen_count,
                        linked_event_id = EXCLUDED.linked_event_id,
                        first_seen_at = EXCLUDED.first_seen_at,
                        last_seen_at = EXCLUDED.last_seen_at,
                        updated_at = NOW()
                    """,
                    (
                        row["gap_key"],
                        row["problem_id"],
                        row["description"],
                        row["source"],
                        row["affected_route"],
                        row["query_text"],
                        row["status"],
                        row["quality"] or None,
                        row["resolution_plan"],
                        row["confidence"],
                        Json(row["metadata"]),
                        row["created_at"],
                        row["resolved_at"],
                        row["verified_at"],
                        row["observation_until"],
                        row["last_reopened_at"],
                        row["scope_type"],
                        row["scope_id"],
                        row["cluster_id"],
                        row["cause_type"],
                        row["priority"],
                        row["owner"],
                        row["reopen_count"],
                        row["linked_event_id"],
                        row["first_seen_at"],
                        row["last_seen_at"],
                    ),
                )
        conn.commit()
        return len(projection_rows)
    except Exception:
        error = True
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            _put_pg_conn(conn, error=error)


def reconcile_learning_runs_projection(*, run_id: Optional[str] = None) -> dict[str, Any]:
    before = compare_learning_runs_projection(run_id=run_id)
    rebuilt = rebuild_learning_runs_projection(run_id=run_id) if before["drift_count"] else 0
    after = compare_learning_runs_projection(run_id=run_id)
    return {
        "run_id": run_id,
        "before": before,
        "rebuilt": rebuilt,
        "after": after,
    }


def reconcile_agent_run_projection(*, run_id: Optional[str] = None) -> dict[str, Any]:
    before = compare_agent_run_projection(run_id=run_id)
    rebuilt = rebuild_agent_run_projection(run_id=run_id) if before["drift_count"] else 0
    after = compare_agent_run_projection(run_id=run_id)
    return {
        "run_id": run_id,
        "before": before,
        "rebuilt": rebuilt,
        "after": after,
    }


def reconcile_conversation_turns_projection(*, run_id: Optional[str] = None) -> dict[str, Any]:
    before = compare_conversation_turns_projection(run_id=run_id)
    rebuilt = rebuild_conversation_turns_projection(run_id=run_id) if before["drift_count"] else 0
    after = compare_conversation_turns_projection(run_id=run_id)
    return {
        "run_id": run_id,
        "session_id": before.get("session_id") or after.get("session_id"),
        "before": before,
        "rebuilt": rebuilt,
        "after": after,
    }


def reconcile_knowledge_gaps_projection(*, run_id: Optional[str] = None) -> dict[str, Any]:
    before = compare_knowledge_gaps_projection(run_id=run_id)
    rebuilt = rebuild_knowledge_gaps_projection(run_id=run_id) if before["drift_count"] else 0
    after = compare_knowledge_gaps_projection(run_id=run_id)
    return {
        "run_id": run_id,
        "scope": "global_only",
        "before": before,
        "rebuilt": rebuilt,
        "after": after,
    }


def reconcile_canonical_projections(*, run_id: Optional[str] = None) -> dict[str, Any]:
    learning_runs = reconcile_learning_runs_projection(run_id=run_id)
    agent_runs = reconcile_agent_run_projection(run_id=run_id)
    conversation_turns = reconcile_conversation_turns_projection(run_id=run_id)
    knowledge_gaps = reconcile_knowledge_gaps_projection(run_id=run_id)
    projections = {
        "learning_runs": learning_runs,
        "agent_run_projection": agent_runs,
        "conversation_turns": conversation_turns,
        "knowledge_gaps": knowledge_gaps,
    }
    return {
        "run_id": run_id,
        "projections": projections,
        "rebuilt_total": sum(int(result.get("rebuilt") or 0) for result in projections.values()),
        "remaining_drift_count": sum(
            int(result.get("after", {}).get("drift_count") or 0) for result in projections.values()
        ),
    }
