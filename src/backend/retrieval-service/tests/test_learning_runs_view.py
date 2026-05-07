from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.agent.projections.learning_runs_view import fetch_learning_runs


def test_fetch_learning_runs_reads_learning_loop_projection_only():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchall.side_effect = [
        [
            (
                "run_manual_20260506_030000",
                "manual",
                {"signals_count": 5, "status": "completed", "reason": "manual"},
                "completed",
                datetime(2026, 5, 6, 3, 0, tzinfo=timezone.utc),
            )
        ],
    ]

    with patch("app.agent.projections.learning_runs_view._get_pg_conn", return_value=mock_conn), patch(
        "app.agent.projections.learning_runs_view._put_pg_conn"
    ):
        result = fetch_learning_runs(limit=10, kind="learning_loop")

    assert result["runs"][0]["run_id"] == "run_manual_20260506_030000"
    assert result["runs"][0]["run_type"] == "manual"
    assert result["runs"][0]["status"] == "completed"
    executed_sql = mock_cursor.execute.call_args.args[0]
    assert "FROM learning_runs" in executed_sql


def test_fetch_learning_runs_kind_all_merges_projection_reads():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchall.side_effect = [
        [
            (
                "run-interaction-1",
                "session-1",
                "What is the price?",
                "price",
                "sync",
                "completed",
                "answered",
                "ANSWERED_OK",
                "good",
                True,
                False,
                False,
                1,
                1,
                [],
                {},
                {},
                "42",
                "request-1",
                "trace-1",
                datetime(2026, 5, 6, 1, 0, tzinfo=timezone.utc),
                datetime(2026, 5, 6, 1, 1, tzinfo=timezone.utc),
                1000,
            )
        ],
        [
            (
                "run-learning-1",
                "manual",
                {"signals_count": 2, "status": "completed"},
                "completed",
                datetime(2026, 5, 6, 2, 0, tzinfo=timezone.utc),
            )
        ],
    ]

    with patch("app.agent.projections.learning_runs_view._get_pg_conn", return_value=mock_conn), patch(
        "app.agent.projections.learning_runs_view._put_pg_conn"
    ):
        result = fetch_learning_runs(limit=10, kind="all")

    assert result["runs"][0]["kind"] == "learning_loop"
    assert result["runs"][0]["run_id"] == "run-learning-1"
    assert result["runs"][1]["kind"] == "interaction"
    assert result["runs"][1]["run_id"] == "run-interaction-1"


def test_fetch_learning_runs_returns_error_payload_when_projection_read_fails():
    with patch(
        "app.agent.projections.learning_runs_view._get_pg_conn",
        side_effect=RuntimeError("projection unavailable"),
    ), patch("app.agent.projections.learning_runs_view._put_pg_conn"):
        result = fetch_learning_runs(limit=10, kind="interaction")

    assert result["runs"] == []
    assert result["total_in_window"] == 0
    assert result["error"] == "projection unavailable"
