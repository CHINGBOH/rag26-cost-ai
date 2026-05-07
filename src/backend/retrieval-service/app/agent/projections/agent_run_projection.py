"""
Projection writes for canonical interaction runs.
"""

from __future__ import annotations

from psycopg2.extras import Json


def upsert_agent_run_projection(cur, payload: dict) -> None:
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
            payload["run_id"],
            payload["session_id"],
            payload["query"],
            payload.get("query_type") or "",
            payload["channel"],
            payload["status"],
            payload["outcome_family"],
            payload["outcome_code"],
            payload["quality"],
            bool(payload["learning_eligible"]),
            bool(payload["early_exit"]),
            bool(payload["refused"]),
            int(payload["iterations"]),
            int(payload["chunks_count"]),
            Json(payload.get("tools_used") or []),
            Json(payload.get("evaluation") or {}),
            Json(payload.get("runtime") or {}),
            str(payload.get("answer") or payload.get("error_message") or "")[:500],
            payload["request_id"],
            payload["trace_id"],
            payload["started_at"],
            payload["completed_at"],
            int(payload["latency_ms"]),
        ),
    )
