from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.agent.event_ledger import (
    insert_improvement_event,
    record_interaction_run_terminal,
    record_projection_reconcile_event,
)
from app.agent.run_context import RunContext


def _build_run_context() -> RunContext:
    return RunContext(
        run_id="run-123",
        session_id="session-123",
        request_id="request-123",
        trace_id="trace-123",
        channel="sync",
        query="What is the price?",
        started_at=datetime(2026, 5, 6, 1, 0, tzinfo=timezone.utc),
    )


def test_record_interaction_run_terminal_writes_one_terminal_event_and_projections():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("app.agent.event_ledger._get_pg_conn", return_value=mock_conn), patch(
        "app.agent.event_ledger._put_pg_conn"
    ), patch("app.agent.event_ledger.upsert_agent_run_projection") as mock_projection, patch(
        "app.agent.event_ledger.insert_conversation_turn"
    ) as mock_turn, patch("app.agent.event_ledger._append_legacy_run_record") as mock_legacy:
        payload = record_interaction_run_terminal(
            run_context=_build_run_context(),
            query_type="price",
            final_answer="The price is 42.",
            evaluation={"confidence": 0.95, "information_gain": 0.9},
            runtime={"provider": "test"},
            chunks=[{"id": "c1"}],
            iterations=2,
            messages=[],
        )

    assert payload["run_id"] == "run-123"
    assert payload["outcome_family"] == "answered"
    assert payload["quality"] == "good"
    sql = mock_cursor.execute.call_args.args[0]
    params = mock_cursor.execute.call_args.args[1]
    assert "INSERT INTO event_ledger" in sql
    assert params[0] == "interaction_run"
    assert params[2] == "interaction.run.terminal"
    assert params[16] == "interaction-terminal:run-123"
    mock_projection.assert_called_once()
    mock_turn.assert_called_once()
    mock_legacy.assert_not_called()
    mock_conn.commit.assert_called_once()


def test_record_interaction_run_terminal_dual_writes_legacy_for_non_task_early_exit():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("app.agent.event_ledger._get_pg_conn", return_value=mock_conn), patch(
        "app.agent.event_ledger._put_pg_conn"
    ), patch("app.agent.event_ledger.upsert_agent_run_projection"), patch(
        "app.agent.event_ledger.insert_conversation_turn"
    ), patch("app.agent.event_ledger._append_legacy_run_record") as mock_legacy:
        payload = record_interaction_run_terminal(
            run_context=_build_run_context(),
            query_type="chitchat",
            final_answer="Hello there!",
            evaluation={},
            runtime={"provider": "test"},
            chunks=[],
            iterations=0,
            messages=[],
        )

    assert payload["outcome_family"] == "non_task"
    assert payload["early_exit"] is True
    assert payload["learning_eligible"] is False
    mock_legacy.assert_called_once()


def test_insert_improvement_event_uses_stable_idempotency_key():
    mock_cursor = MagicMock()

    payload = insert_improvement_event(
        mock_cursor,
        event_id=7,
        patch_id="patch-7",
        affected_route="R4_rerank_weights",
        patch_type="weight",
        status="verified",
        event_type="improvement.event.verified",
        gap_key="gap-7",
        verification_result={"delta": 0.2},
        recovery_point="abc123",
        occurred_at=datetime(2026, 5, 6, 1, 30, tzinfo=timezone.utc),
    )

    assert payload["event_id"] == 7
    assert payload["event_type"] == "improvement.event.verified"
    assert payload["verification_result"]["delta"] == 0.2
    sql = mock_cursor.execute.call_args.args[0]
    params = mock_cursor.execute.call_args.args[1]
    assert "INSERT INTO event_ledger" in sql
    assert params[0] == "improvement_event"
    assert params[2] == "improvement.event.verified"
    assert params[16] == "improvement.event.verified:7"


def test_record_projection_reconcile_event_writes_audit_event():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("app.agent.event_ledger._get_pg_conn", return_value=mock_conn), patch(
        "app.agent.event_ledger._put_pg_conn"
    ):
        payload = record_projection_reconcile_event(
            run_id="run-sync-9",
            summary={
                "rebuilt_total": 3,
                "remaining_drift_count": 1,
                "projections": {"conversation_turns": {"rebuilt": 2}},
            },
        )

    assert payload["run_id"] == "run-sync-9"
    assert payload["rebuilt_total"] == 3
    sql = mock_cursor.execute.call_args.args[0]
    params = mock_cursor.execute.call_args.args[1]
    assert "INSERT INTO event_ledger" in sql
    assert params[0] == "projection_reconcile"
    assert params[2] == "projection.reconcile.completed"
    assert params[3] == "run-sync-9"
    assert params[10] == "partial"
    assert params[11] == "PROJECTION_RECONCILE_COMPLETED"
    mock_conn.commit.assert_called_once()
