"""
Projection writes for conversation_turns.
"""

from __future__ import annotations


def insert_conversation_turn(cur, payload: dict) -> None:
    cur.execute(
        """
        INSERT INTO conversation_turns
            (session_id, turn_index, user_content, assistant_content,
             message_id, source, status, latency_ms, run_id, channel, outcome_code, quality, early_exit)
        VALUES
            (%s, (SELECT COALESCE(MAX(turn_index), 0) + 1 FROM conversation_turns WHERE session_id = %s),
             %s, %s, %s, 'agent', %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (session_id, turn_index) DO NOTHING
        """,
        (
            payload["session_id"],
            payload["session_id"],
            payload["query"],
            payload.get("answer") or payload.get("error_message") or "",
            payload["request_id"],
            payload["status"],
            payload["latency_ms"],
            payload["run_id"],
            payload["channel"],
            payload["outcome_code"],
            payload["quality"],
            bool(payload["early_exit"]),
        ),
    )
