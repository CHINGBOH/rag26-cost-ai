from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from psycopg2.extras import Json

from app.agent.projections.rebuild import (
    _build_agent_run_projection_rows,
    _build_conversation_turn_projection_rows,
    _build_knowledge_gap_projection_rows,
    _build_learning_run_projection_rows,
    compare_agent_run_projection,
    compare_canonical_projection_drift,
    compare_conversation_turns_projection,
    compare_knowledge_gaps_projection,
    compare_learning_runs_projection,
    reconcile_agent_run_projection,
    reconcile_canonical_projections,
    reconcile_conversation_turns_projection,
    reconcile_knowledge_gaps_projection,
    reconcile_learning_runs_projection,
    rebuild_agent_run_projection,
    rebuild_conversation_turns_projection,
    rebuild_knowledge_gaps_projection,
    rebuild_learning_runs_projection,
)


def test_build_learning_run_projection_rows_filters_invalid_rows():
    rows = [
        (
            "run_manual_001",
            {"run_type": "manual", "status": "completed", "result": {"signals_count": 3}},
            datetime(2026, 5, 6, 3, 0, tzinfo=timezone.utc),
        ),
        ("", {"run_type": "manual", "status": "completed", "result": {}}, datetime.now(timezone.utc)),
        ("run_missing_status", {"run_type": "manual", "result": {}}, datetime.now(timezone.utc)),
    ]

    projection_rows = _build_learning_run_projection_rows(rows)

    assert len(projection_rows) == 1
    assert projection_rows[0]["run_id"] == "run_manual_001"
    assert projection_rows[0]["status"] == "completed"
    assert projection_rows[0]["result"]["signals_count"] == 3


def test_rebuild_learning_runs_projection_upserts_latest_ledger_rows():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchall.return_value = [
        (
            "run_manual_002",
            {"run_type": "manual", "status": "failed", "result": {"error": "timeout"}},
            datetime(2026, 5, 6, 3, 15, tzinfo=timezone.utc),
        )
    ]

    with patch("app.agent.projections.rebuild._get_pg_conn", return_value=mock_conn), patch(
        "app.agent.projections.rebuild._put_pg_conn"
    ):
        rebuilt = rebuild_learning_runs_projection()

    assert rebuilt == 1
    sql_calls = [call.args[0] for call in mock_cursor.execute.call_args_list]
    assert any("FROM event_ledger" in sql for sql in sql_calls)
    assert any("INSERT INTO learning_runs" in sql for sql in sql_calls)
    upsert_args = mock_cursor.execute.call_args_list[-1].args[1]
    assert isinstance(upsert_args[2], Json)
    mock_conn.commit.assert_called_once()


def test_rebuild_learning_runs_projection_deletes_stale_global_rows():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchall.return_value = [
        (
            "run_manual_002",
            {"run_type": "manual", "status": "failed", "result": {"error": "timeout"}},
            datetime(2026, 5, 6, 3, 15, tzinfo=timezone.utc),
        )
    ]
    mock_cursor.rowcount = 2

    with patch("app.agent.projections.rebuild._get_pg_conn", return_value=mock_conn), patch(
        "app.agent.projections.rebuild._put_pg_conn"
    ):
        rebuilt = rebuild_learning_runs_projection()

    assert rebuilt == 3
    delete_call = mock_cursor.execute.call_args_list[1]
    assert "DELETE FROM learning_runs" in delete_call.args[0]
    assert delete_call.args[1] == (["run_manual_002"],)
    mock_conn.commit.assert_called_once()


def test_rebuild_learning_runs_projection_deletes_stale_scoped_row():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchall.return_value = []
    mock_cursor.rowcount = 1

    with patch("app.agent.projections.rebuild._get_pg_conn", return_value=mock_conn), patch(
        "app.agent.projections.rebuild._put_pg_conn"
    ):
        rebuilt = rebuild_learning_runs_projection(run_id="run_stale_001")

    assert rebuilt == 1
    delete_call = mock_cursor.execute.call_args_list[1]
    assert "DELETE FROM learning_runs WHERE run_id = %s" in delete_call.args[0]
    assert delete_call.args[1] == ("run_stale_001",)
    mock_conn.commit.assert_called_once()


def test_compare_learning_runs_projection_detects_missing_and_mismatched_rows():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchall.side_effect = [
        [
            (
                "run_manual_003",
                {"run_type": "manual", "status": "completed", "result": {"signals_count": 3}},
                datetime(2026, 5, 6, 3, 30, tzinfo=timezone.utc),
            )
        ],
        [
            (
                "run_manual_003",
                "scheduled",
                {"signals_count": 1},
                "failed",
                datetime(2026, 5, 6, 3, 0, tzinfo=timezone.utc),
            ),
            (
                "run_stale_001",
                "manual",
                {"signals_count": 4},
                "completed",
                datetime(2026, 5, 6, 2, 45, tzinfo=timezone.utc),
            ),
        ],
    ]

    with patch("app.agent.projections.rebuild._get_pg_conn", return_value=mock_conn), patch(
        "app.agent.projections.rebuild._put_pg_conn"
    ):
        result = compare_learning_runs_projection()

    assert result["drift_count"] == 2
    assert result["stale_in_projection"] == ["run_stale_001"]
    assert result["mismatches"][0]["run_id"] == "run_manual_003"
    assert set(result["mismatches"][0]["fields"]) == {"run_type", "status", "result"}


def test_reconcile_learning_runs_projection_rebuilds_only_when_drift_exists():
    with patch(
        "app.agent.projections.rebuild.compare_learning_runs_projection",
        side_effect=[
            {"drift_count": 1, "missing_in_projection": ["run_manual_004"], "stale_in_projection": [], "mismatches": []},
            {"drift_count": 0, "missing_in_projection": [], "stale_in_projection": [], "mismatches": []},
        ],
    ) as mock_compare, patch(
        "app.agent.projections.rebuild.rebuild_learning_runs_projection",
        return_value=1,
    ) as mock_rebuild:
        result = reconcile_learning_runs_projection(run_id="run_manual_004")

    assert result["rebuilt"] == 1
    assert result["after"]["drift_count"] == 0
    mock_rebuild.assert_called_once_with(run_id="run_manual_004")
    assert mock_compare.call_count == 2


def test_build_agent_run_projection_rows_filters_invalid_rows():
    rows = [
        (
            "run_sync_001",
            {
                "session_id": "session-001",
                "query": "What is the price?",
                "query_type": "price",
                "channel": "sync",
                "status": "completed",
                "outcome_family": "answered",
                "outcome_code": "ANSWERED_OK",
                "quality": "good",
                "learning_eligible": True,
                "iterations": 2,
                "chunks_count": 3,
                "tools_used": ["retrieve"],
                "evaluation": {"confidence": 0.9},
                "runtime": {"provider": "test"},
                "answer": "The price is 42.",
                "request_id": "request-001",
                "trace_id": "trace-001",
                "started_at": "2026-05-06T03:40:00+00:00",
                "completed_at": "2026-05-06T03:40:02+00:00",
                "latency_ms": 2000,
            },
            datetime(2026, 5, 6, 3, 40, 2, tzinfo=timezone.utc),
        ),
        (
            "run_invalid_001",
            {"channel": "sync", "status": "completed", "outcome_family": "answered"},
            datetime.now(timezone.utc),
        ),
    ]

    projection_rows = _build_agent_run_projection_rows(rows)

    assert len(projection_rows) == 1
    assert projection_rows[0]["run_id"] == "run_sync_001"
    assert projection_rows[0]["answer_preview"] == "The price is 42."
    assert projection_rows[0]["tools_used"] == ["retrieve"]


def test_rebuild_agent_run_projection_upserts_latest_ledger_rows():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchall.return_value = [
        (
            "run_sync_002",
            {
                "session_id": "session-002",
                "query": "Tell me the price",
                "query_type": "price",
                "channel": "sync",
                "status": "completed",
                "outcome_family": "answered",
                "outcome_code": "ANSWERED_OK",
                "quality": "good",
                "learning_eligible": True,
                "early_exit": False,
                "refused": False,
                "iterations": 1,
                "chunks_count": 2,
                "tools_used": ["search"],
                "evaluation": {"confidence": 0.88},
                "runtime": {"provider": "test"},
                "answer": "42",
                "request_id": "request-002",
                "trace_id": "trace-002",
                "started_at": "2026-05-06T03:45:00+00:00",
                "completed_at": "2026-05-06T03:45:01+00:00",
                "latency_ms": 1000,
            },
            datetime(2026, 5, 6, 3, 45, 1, tzinfo=timezone.utc),
        )
    ]

    with patch("app.agent.projections.rebuild._get_pg_conn", return_value=mock_conn), patch(
        "app.agent.projections.rebuild._put_pg_conn"
    ):
        rebuilt = rebuild_agent_run_projection()

    assert rebuilt == 1
    sql_calls = [call.args[0] for call in mock_cursor.execute.call_args_list]
    assert any("FROM event_ledger" in sql for sql in sql_calls)
    assert any("INSERT INTO agent_run_projection" in sql for sql in sql_calls)
    mock_conn.commit.assert_called_once()


def test_compare_agent_run_projection_detects_missing_and_mismatched_rows():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchall.side_effect = [
        [
            (
                "run_sync_003",
                {
                    "session_id": "session-003",
                    "query": "price?",
                    "query_type": "price",
                    "channel": "sync",
                    "status": "completed",
                    "outcome_family": "answered",
                    "outcome_code": "ANSWERED_OK",
                    "quality": "good",
                    "learning_eligible": True,
                    "early_exit": False,
                    "refused": False,
                    "iterations": 1,
                    "chunks_count": 2,
                    "tools_used": ["search"],
                    "evaluation": {"confidence": 0.95},
                    "runtime": {"provider": "test"},
                    "answer": "42",
                    "request_id": "request-003",
                    "trace_id": "trace-003",
                    "started_at": "2026-05-06T03:50:00+00:00",
                    "completed_at": "2026-05-06T03:50:01+00:00",
                    "latency_ms": 1000,
                },
                datetime(2026, 5, 6, 3, 50, 1, tzinfo=timezone.utc),
            )
        ],
        [
            (
                "run_sync_003",
                "session-003",
                "price?",
                "price",
                "sync",
                "failed",
                "answered",
                "ANSWERED_OK",
                "good",
                True,
                False,
                False,
                1,
                1,
                ["search"],
                {"confidence": 0.95},
                {"provider": "test"},
                "42",
                "request-003",
                "trace-003",
                datetime(2026, 5, 6, 3, 50, 0, tzinfo=timezone.utc),
                datetime(2026, 5, 6, 3, 50, 1, tzinfo=timezone.utc),
                1000,
            ),
            (
                "run_stale_sync_001",
                "session-stale",
                "old price?",
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
                ["search"],
                {"confidence": 0.7},
                {"provider": "test"},
                "41",
                "request-stale",
                "trace-stale",
                datetime(2026, 5, 6, 3, 30, 0, tzinfo=timezone.utc),
                datetime(2026, 5, 6, 3, 30, 1, tzinfo=timezone.utc),
                1000,
            ),
        ],
    ]

    with patch("app.agent.projections.rebuild._get_pg_conn", return_value=mock_conn), patch(
        "app.agent.projections.rebuild._put_pg_conn"
    ):
        result = compare_agent_run_projection()

    assert result["drift_count"] == 2
    assert result["stale_in_projection"] == ["run_stale_sync_001"]
    assert result["mismatches"][0]["run_id"] == "run_sync_003"
    assert set(result["mismatches"][0]["fields"]) == {"status", "chunks_count"}


def test_reconcile_agent_run_projection_rebuilds_only_when_drift_exists():
    with patch(
        "app.agent.projections.rebuild.compare_agent_run_projection",
        side_effect=[
            {"drift_count": 1, "missing_in_projection": ["run_sync_004"], "stale_in_projection": [], "mismatches": []},
            {"drift_count": 0, "missing_in_projection": [], "stale_in_projection": [], "mismatches": []},
        ],
    ) as mock_compare, patch(
        "app.agent.projections.rebuild.rebuild_agent_run_projection",
        return_value=1,
    ) as mock_rebuild:
        result = reconcile_agent_run_projection(run_id="run_sync_004")

    assert result["rebuilt"] == 1
    assert result["after"]["drift_count"] == 0
    mock_rebuild.assert_called_once_with(run_id="run_sync_004")
    assert mock_compare.call_count == 2


def test_build_conversation_turn_projection_rows_assigns_turn_indexes_with_offsets():
    rows = [
        (
            "run_sync_005",
            {
                "session_id": "session-005",
                "request_id": "request-005",
                "query": "first question",
                "answer": "first answer",
                "status": "completed",
                "latency_ms": 1000,
                "channel": "sync",
                "outcome_code": "ANSWERED_OK",
                "quality": "good",
                "completed_at": "2026-05-06T04:00:01+00:00",
            },
            datetime(2026, 5, 6, 4, 0, 1, tzinfo=timezone.utc),
        ),
        (
            "run_sync_006",
            {
                "session_id": "session-005",
                "request_id": "request-006",
                "query": "second question",
                "answer": "second answer",
                "status": "completed",
                "latency_ms": 900,
                "channel": "sync",
                "outcome_code": "ANSWERED_OK",
                "quality": "good",
                "completed_at": "2026-05-06T04:00:02+00:00",
            },
            datetime(2026, 5, 6, 4, 0, 2, tzinfo=timezone.utc),
        ),
    ]

    projection_rows = _build_conversation_turn_projection_rows(
        rows,
        base_turn_indexes={"session-005": 2},
    )

    assert len(projection_rows) == 2
    assert projection_rows[0]["turn_index"] == 3
    assert projection_rows[1]["turn_index"] == 4
    assert projection_rows[1]["assistant_content"] == "second answer"


def test_rebuild_conversation_turns_projection_rewrites_managed_rows():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchall.side_effect = [
        [
            (
                "run_sync_007",
                {
                    "session_id": "session-007",
                    "request_id": "request-007",
                    "query": "question",
                    "answer": "answer",
                    "status": "completed",
                    "latency_ms": 1200,
                    "channel": "sync",
                    "outcome_code": "ANSWERED_OK",
                    "quality": "good",
                    "completed_at": "2026-05-06T04:10:01+00:00",
                },
                datetime(2026, 5, 6, 4, 10, 1, tzinfo=timezone.utc),
            )
        ],
        [],
    ]

    with patch("app.agent.projections.rebuild._get_pg_conn", return_value=mock_conn), patch(
        "app.agent.projections.rebuild._put_pg_conn"
    ):
        rebuilt = rebuild_conversation_turns_projection()

    assert rebuilt == 1
    sql_calls = [call.args[0] for call in mock_cursor.execute.call_args_list]
    assert any("DELETE FROM conversation_turns" in sql for sql in sql_calls)
    assert any("INSERT INTO conversation_turns" in sql for sql in sql_calls)
    mock_conn.commit.assert_called_once()


def test_compare_conversation_turns_projection_detects_stale_and_mismatch():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchall.side_effect = [
        [
            (
                "run_sync_008",
                {
                    "session_id": "session-008",
                    "request_id": "request-008",
                    "query": "question",
                    "answer": "answer",
                    "status": "completed",
                    "latency_ms": 800,
                    "channel": "sync",
                    "outcome_code": "ANSWERED_OK",
                    "quality": "good",
                    "completed_at": "2026-05-06T04:20:01+00:00",
                },
                datetime(2026, 5, 6, 4, 20, 1, tzinfo=timezone.utc),
            )
        ],
        [],
        [
            (
                "session-008",
                1,
                "question",
                "different answer",
                "request-008",
                "agent",
                "completed",
                800,
                "run_sync_008",
                "sync",
                "ANSWERED_OK",
                "good",
                False,
                datetime(2026, 5, 6, 4, 20, 1, tzinfo=timezone.utc).timestamp(),
            ),
            (
                "session-008",
                2,
                "stale question",
                "stale answer",
                "request-stale",
                "agent",
                "completed",
                700,
                "run_stale_turn_001",
                "sync",
                "ANSWERED_OK",
                "good",
                False,
                datetime(2026, 5, 6, 4, 19, 1, tzinfo=timezone.utc).timestamp(),
            ),
        ],
    ]

    with patch("app.agent.projections.rebuild._get_pg_conn", return_value=mock_conn), patch(
        "app.agent.projections.rebuild._put_pg_conn"
    ):
        result = compare_conversation_turns_projection()

    assert result["drift_count"] == 2
    assert result["stale_in_projection"] == ["run_stale_turn_001"]
    assert result["mismatches"][0]["run_id"] == "run_sync_008"
    assert set(result["mismatches"][0]["fields"]) == {"assistant_content"}


def test_reconcile_conversation_turns_projection_rebuilds_only_when_drift_exists():
    with patch(
        "app.agent.projections.rebuild.compare_conversation_turns_projection",
        side_effect=[
            {
                "drift_count": 1,
                "session_id": "session-009",
                "missing_in_projection": ["run_sync_009"],
                "stale_in_projection": [],
                "mismatches": [],
            },
            {
                "drift_count": 0,
                "session_id": "session-009",
                "missing_in_projection": [],
                "stale_in_projection": [],
                "mismatches": [],
            },
        ],
    ) as mock_compare, patch(
        "app.agent.projections.rebuild.rebuild_conversation_turns_projection",
        return_value=1,
    ) as mock_rebuild:
        result = reconcile_conversation_turns_projection(run_id="run_sync_009")

    assert result["rebuilt"] == 1
    assert result["after"]["drift_count"] == 0
    assert result["session_id"] == "session-009"
    mock_rebuild.assert_called_once_with(run_id="run_sync_009")
    assert mock_compare.call_count == 2


def test_build_knowledge_gap_projection_rows_filters_invalid_rows():
    rows = [
        (
            "gap_answer_quality",
            {
                "gap_key": "gap_answer_quality",
                "description": "Answer quality degradation",
                "source": "problem",
                "status": "observing",
                "quality": "weak",
                "priority": 12,
                "metadata": {"frequency": 2},
            },
            datetime(2026, 5, 6, 4, 0, tzinfo=timezone.utc),
        ),
        ("", {"description": "missing key", "source": "problem", "status": "open"}, datetime.now(timezone.utc)),
    ]

    projection_rows = _build_knowledge_gap_projection_rows(rows)

    assert len(projection_rows) == 1
    assert projection_rows[0]["gap_key"] == "gap_answer_quality"
    assert projection_rows[0]["status"] == "observing"
    assert projection_rows[0]["metadata"]["frequency"] == 2


def test_compare_knowledge_gaps_projection_detects_mismatches_and_tracks_unmanaged_rows():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchall.side_effect = [
        [
            (
                "gap_answer_quality",
                {
                    "gap_key": "gap_answer_quality",
                    "problem_id": "prob-1",
                    "description": "Answer quality degradation",
                    "source": "problem",
                    "status": "observing",
                    "quality": "weak",
                    "priority": 12,
                    "metadata": {"frequency": 3},
                    "verified_at": "2026-05-06T04:00:00+00:00",
                },
                datetime(2026, 5, 6, 4, 0, tzinfo=timezone.utc),
            )
        ],
        [
            (
                "gap_answer_quality",
                "prob-1",
                "Answer quality degradation",
                "problem",
                None,
                None,
                "open",
                "weak",
                None,
                0.0,
                {"frequency": 1},
                datetime(2026, 5, 6, 3, 0, tzinfo=timezone.utc),
                None,
                None,
                None,
                None,
                "global",
                None,
                None,
                None,
                5,
                None,
                0,
                None,
                datetime(2026, 5, 6, 3, 0, tzinfo=timezone.utc),
                datetime(2026, 5, 6, 3, 30, tzinfo=timezone.utc),
            )
        ],
    ]
    mock_cursor.fetchone.return_value = (2,)

    with patch("app.agent.projections.rebuild._get_pg_conn", return_value=mock_conn), patch(
        "app.agent.projections.rebuild._put_pg_conn"
    ):
        result = compare_knowledge_gaps_projection()

    assert result["unmanaged_projection_count"] == 2
    assert result["drift_count"] == 1
    assert result["mismatches"][0]["gap_key"] == "gap_answer_quality"
    assert set(result["mismatches"][0]["fields"]) >= {"status", "priority", "metadata", "verified_at"}


def test_rebuild_knowledge_gaps_projection_rewrites_managed_rows_only():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchall.return_value = [
        (
            "gap_answer_quality",
            {
                "gap_key": "gap_answer_quality",
                "problem_id": "prob-1",
                "description": "Answer quality degradation",
                "source": "problem",
                "status": "observing",
                "quality": "weak",
                "metadata": {"frequency": 3},
                "priority": 10,
            },
            datetime(2026, 5, 6, 4, 0, tzinfo=timezone.utc),
        )
    ]

    with patch("app.agent.projections.rebuild._get_pg_conn", return_value=mock_conn), patch(
        "app.agent.projections.rebuild._put_pg_conn"
    ):
        rebuilt = rebuild_knowledge_gaps_projection()

    assert rebuilt == 1
    sql_calls = [call.args[0] for call in mock_cursor.execute.call_args_list]
    assert any("FROM event_ledger" in sql for sql in sql_calls)
    assert any("DELETE FROM knowledge_gaps" in sql for sql in sql_calls)
    assert any("INSERT INTO knowledge_gaps" in sql for sql in sql_calls)
    mock_conn.commit.assert_called_once()


def test_reconcile_knowledge_gaps_projection_rebuilds_only_when_drift_exists():
    with patch(
        "app.agent.projections.rebuild.compare_knowledge_gaps_projection",
        side_effect=[
            {"drift_count": 1, "missing_in_projection": ["gap_answer_quality"], "stale_in_projection": [], "mismatches": []},
            {"drift_count": 0, "missing_in_projection": [], "stale_in_projection": [], "mismatches": []},
        ],
    ) as mock_compare, patch(
        "app.agent.projections.rebuild.rebuild_knowledge_gaps_projection",
        return_value=1,
    ) as mock_rebuild:
        result = reconcile_knowledge_gaps_projection()

    assert result["rebuilt"] == 1
    assert result["after"]["drift_count"] == 0
    mock_rebuild.assert_called_once_with(run_id=None)
    assert mock_compare.call_count == 2


def test_compare_canonical_projection_drift_summarizes_projection_state():
    with patch(
        "app.agent.projections.rebuild.compare_learning_runs_projection",
        return_value={"drift_count": 1},
    ), patch(
        "app.agent.projections.rebuild.compare_agent_run_projection",
        return_value={"drift_count": 0},
    ), patch(
        "app.agent.projections.rebuild.compare_conversation_turns_projection",
        return_value={"drift_count": 2},
    ), patch(
        "app.agent.projections.rebuild.compare_knowledge_gaps_projection",
        return_value={"drift_count": 0},
    ):
        result = compare_canonical_projection_drift()

    assert result["total_drift_count"] == 3
    assert result["drifted_projections"] == ["learning_runs", "conversation_turns"]


def test_reconcile_canonical_projections_summarizes_rebuild_results():
    with patch(
        "app.agent.projections.rebuild.reconcile_learning_runs_projection",
        return_value={"rebuilt": 1, "after": {"drift_count": 0}},
    ), patch(
        "app.agent.projections.rebuild.reconcile_agent_run_projection",
        return_value={"rebuilt": 0, "after": {"drift_count": 0}},
    ), patch(
        "app.agent.projections.rebuild.reconcile_conversation_turns_projection",
        return_value={"rebuilt": 2, "after": {"drift_count": 1}},
    ), patch(
        "app.agent.projections.rebuild.reconcile_knowledge_gaps_projection",
        return_value={"rebuilt": 1, "after": {"drift_count": 0}},
    ):
        result = reconcile_canonical_projections()

    assert result["rebuilt_total"] == 4
    assert result["remaining_drift_count"] == 1
