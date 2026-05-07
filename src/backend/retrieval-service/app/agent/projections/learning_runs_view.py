"""
Projection-backed read helpers for interaction and learning-loop runs.
"""

from __future__ import annotations

from typing import Any, Optional

from app.agent.learning_state import coerce_json_dict, normalize_epoch_milliseconds
from app.agent.tools import _get_pg_conn, _put_pg_conn


def _append_learning_loop_runs_from_projection(cur: Any, items: list[dict[str, Any]], limit: int) -> None:
    cur.execute(
        """
        SELECT run_id, run_type, result, status, ts
        FROM learning_runs
        ORDER BY ts DESC
        LIMIT %s
        """,
        (max(limit * 2, 100),),
    )
    for row in cur.fetchall():
        items.append(
            {
                "kind": "learning_loop",
                "run_id": row[0],
                "run_type": row[1],
                "result": coerce_json_dict(row[2]),
                "status": row[3],
                "ts": normalize_epoch_milliseconds(row[4]),
            }
        )
def fetch_learning_runs(
    *,
    limit: int = 50,
    quality: Optional[str] = None,
    kind: str = "interaction",
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    normalized_kind = (kind or "interaction").strip().lower()
    conn = None
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            if normalized_kind in {"interaction", "all"}:
                params: list[Any] = []
                quality_clause = ""
                if quality:
                    quality_clause = "AND quality = %s"
                    params.append(quality)
                params.append(max(limit * 2, 200))
                cur.execute(
                    f"""
                    SELECT run_id, session_id, query, query_type, channel, status,
                           outcome_family, outcome_code, quality, learning_eligible,
                           early_exit, refused, iterations, chunks_count, tools_used,
                           evaluation, runtime, answer_preview, request_id, trace_id,
                           started_at, completed_at, latency_ms
                    FROM agent_run_projection
                    WHERE 1=1 {quality_clause}
                    ORDER BY completed_at DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                for row in cur.fetchall():
                    items.append(
                        {
                            "kind": "interaction",
                            "run_id": row[0],
                            "session_id": row[1],
                            "query": row[2],
                            "query_type": row[3],
                            "channel": row[4],
                            "status": row[5],
                            "outcome_family": row[6],
                            "outcome_code": row[7],
                            "quality": row[8],
                            "learning_eligible": bool(row[9]),
                            "early_exit": bool(row[10]),
                            "refused": bool(row[11]),
                            "iterations": int(row[12] or 0),
                            "chunks_count": int(row[13] or 0),
                            "tools_used": row[14] or [],
                            "evaluation": coerce_json_dict(row[15]),
                            "runtime": coerce_json_dict(row[16]),
                            "answer": row[17] or "",
                            "request_id": row[18],
                            "trace_id": row[19],
                            "ts": normalize_epoch_milliseconds(row[21] or row[20]),
                            "latency_ms": int(row[22] or 0),
                        }
                    )

            if normalized_kind in {"learning_loop", "all"} and not quality:
                _append_learning_loop_runs_from_projection(cur, items, limit)
    except Exception as exc:
        return {"runs": [], "total_in_window": 0, "error": str(exc)}
    finally:
        if conn is not None:
            _put_pg_conn(conn)

    items.sort(key=lambda item: item.get("ts") or 0, reverse=True)
    return {"runs": items[:limit], "total_in_window": len(items)}
