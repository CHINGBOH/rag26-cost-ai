from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.agent.learning_state import (
    _should_reopen_gap,
    summarize_knowledge_gaps,
    update_knowledge_gap_status,
)


def test_should_reopen_gap_requires_fresh_post_verification_signal():
    verified_at = datetime(2026, 5, 6, 0, 0, tzinfo=timezone.utc)

    assert _should_reopen_gap(
        existing_status="observing",
        incoming_status="open",
        verified_at=verified_at,
        incoming_last_seen_at=verified_at + timedelta(seconds=1),
    )
    assert not _should_reopen_gap(
        existing_status="observing",
        incoming_status="open",
        verified_at=verified_at,
        incoming_last_seen_at=verified_at,
    )
    assert not _should_reopen_gap(
        existing_status="resolved",
        incoming_status="open",
        verified_at=verified_at,
        incoming_last_seen_at=verified_at - timedelta(seconds=1),
    )


def test_summarize_knowledge_gaps_counts_observing():
    summary = summarize_knowledge_gaps(
        [
            {"status": "open", "cluster_id": "c1"},
            {"status": "observing", "cluster_id": "c1"},
            {"status": "observing", "cluster_id": "c2"},
            {"status": "blocked", "cluster_id": "c3"},
        ]
    )

    assert summary["total"] == 4
    assert summary["observing"] == 2
    assert summary["cluster_count"] == 3


def test_update_knowledge_gap_status_sets_observing_window():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_cursor.fetchone.return_value = (
        "gap_001",
        None,
        "Verification passed; entering observation window",
        "problem",
        None,
        None,
        "observing",
        "weak",
        "Verification passed; entering observation window",
        None,
        0.7,
        {"event_id": 7},
        datetime(2026, 5, 6, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 6, 0, 5, tzinfo=timezone.utc),
        None,
        datetime(2026, 5, 6, 0, 5, tzinfo=timezone.utc),
        datetime(2026, 5, 11, 0, 5, tzinfo=timezone.utc),
        None,
        "global",
        None,
        None,
        None,
        10,
        None,
        0,
        7,
        datetime(2026, 5, 6, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 6, 0, 5, tzinfo=timezone.utc),
    )
    mock_conn.cursor.return_value = mock_cursor

    with patch("app.agent.learning_state._get_db_conn", return_value=mock_conn), patch(
        "app.agent.learning_state._put_db_conn"
    ):
        updated = update_knowledge_gap_status(
            "gap_001",
            "observing",
            "Verification passed; entering observation window",
            metadata_patch={"event_id": 7},
            observation_window_days=5,
        )

    assert updated is True
    sql = mock_cursor.execute.call_args_list[0].args[0]
    params = mock_cursor.execute.call_args_list[0].args[1]
    assert "verified_at = CASE" in sql
    assert "observation_until = CASE" in sql
    assert params[9] == 5


def test_update_knowledge_gap_status_marks_blocked_verified():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_cursor.fetchone.return_value = (
        "gap_policy",
        None,
        "Policy boundary",
        "run",
        None,
        "ignore instructions",
        "blocked",
        "failure",
        "Policy boundary",
        None,
        0.9,
        {"triage_action": "block_policy"},
        datetime(2026, 5, 6, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 6, 0, 5, tzinfo=timezone.utc),
        datetime(2026, 5, 6, 0, 5, tzinfo=timezone.utc),
        datetime(2026, 5, 6, 0, 5, tzinfo=timezone.utc),
        None,
        None,
        "global",
        None,
        None,
        "policy_boundary",
        20,
        "copilot_issue_107",
        0,
        None,
        datetime(2026, 5, 6, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 6, 0, 5, tzinfo=timezone.utc),
    )
    mock_conn.cursor.return_value = mock_cursor

    with patch("app.agent.learning_state._get_db_conn", return_value=mock_conn), patch(
        "app.agent.learning_state._put_db_conn"
    ):
        updated = update_knowledge_gap_status(
            "gap_policy",
            "blocked",
            "Policy boundary",
            metadata_patch={"triage_action": "block_policy"},
            owner="copilot_issue_107",
        )

    assert updated is True
    sql = mock_cursor.execute.call_args_list[0].args[0]
    assert "WHEN %s IN ('observing', 'resolved', 'blocked') THEN NOW()" in sql
