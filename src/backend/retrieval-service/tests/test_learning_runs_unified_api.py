import json
from types import SimpleNamespace
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.agent.projections.learning_runs_view import fetch_learning_runs


def test_fetch_learning_runs_kind_all_merges_and_sorts_interaction_and_learning_loop():
    from app.agent.projections.learning_runs_view import _get_pg_conn, _put_pg_conn

    class _Cursor:
        def __init__(self):
            self._fetchall_calls = 0

        def execute(self, sql, params=None):
            self._fetchall_calls += 0

        def fetchall(self):
            self._fetchall_calls += 1
            if self._fetchall_calls == 1:
                return [
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
                ]
            return [
                (
                    "run-learning-1",
                    "manual",
                    {"signals_count": 2, "status": "completed"},
                    "completed",
                    datetime(2026, 5, 6, 2, 0, tzinfo=timezone.utc),
                )
            ]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Conn:
        def cursor(self):
            return _Cursor()

    with patch("app.agent.projections.learning_runs_view._get_pg_conn", return_value=_Conn()), patch(
        "app.agent.projections.learning_runs_view._put_pg_conn"
    ):
        result = fetch_learning_runs(limit=10, kind="all")

    assert result["runs"][0]["kind"] == "learning_loop"
    assert result["runs"][0]["run_id"] == "run-learning-1"
    assert result["runs"][1]["kind"] == "interaction"
    assert result["runs"][1]["run_id"] == "run-interaction-1"


def test_learning_runs_endpoint_forwards_kind_and_quality():
    from main import app

    with patch(
        "app.api.fetch_learning_runs_projection",
        return_value={"runs": [{"kind": "learning_loop", "run_id": "run-learning-2"}], "total_in_window": 1},
    ) as mock_fetch:
        client = TestClient(app)
        response = client.get("/api/v1/learning/runs?kind=learning_loop&quality=failure&limit=5")

    assert response.status_code == 200
    assert response.json()["runs"][0]["run_id"] == "run-learning-2"
    mock_fetch.assert_called_once_with(limit=5, quality="failure", kind="learning_loop")


def test_learning_projection_drift_endpoint_forwards_run_id():
    from main import app

    with patch(
        "app.api.compare_canonical_projection_drift_summary",
        return_value={"total_drift_count": 2, "drifted_projections": ["learning_runs"]},
    ) as mock_compare:
        client = TestClient(app)
        response = client.get("/api/v1/learning/projections/drift?run_id=run-sync-1")

    assert response.status_code == 200
    assert response.json()["total_drift_count"] == 2
    mock_compare.assert_called_once_with(run_id="run-sync-1")


def test_learning_projection_reconcile_endpoint_forwards_run_id():
    from main import app

    with patch(
        "app.api.reconcile_canonical_projection_summary",
        return_value={"rebuilt_total": 3, "remaining_drift_count": 0},
    ) as mock_reconcile, patch(
        "app.api.record_projection_reconcile_event"
    ) as mock_audit:
        client = TestClient(app)
        response = client.post("/api/v1/learning/projections/reconcile?run_id=run-sync-2")

    assert response.status_code == 200
    assert response.json()["rebuilt_total"] == 3
    mock_reconcile.assert_called_once_with(run_id="run-sync-2")
    mock_audit.assert_called_once_with(
        run_id="run-sync-2",
        summary={"rebuilt_total": 3, "remaining_drift_count": 0},
    )


def test_learning_dashboard_includes_projection_drift_summary():
    from main import app

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchall.return_value = []

    with patch("app.agent.tools._get_pg_conn", return_value=mock_conn), patch(
        "app.agent.tools._put_pg_conn"
    ), patch(
        "app.api._calculate_health_score", return_value=80
    ), patch(
        "app.api._build_learning_runtime_state",
        return_value={
            "last_run": 1714898730000,
            "next_scheduled": 1714985130000,
            "engine_status": "idle",
            "pending_approvals": 2,
        },
    ), patch(
        "app.api._generate_alerts",
        return_value=[],
    ), patch(
        "app.api._get_recent_events",
        return_value=[],
    ), patch(
        "app.api.compare_canonical_projection_drift_summary",
        return_value={
            "total_drift_count": 2,
            "drifted_projections": ["conversation_turns"],
            "projections": {"conversation_turns": {"drift_count": 2, "ledger_count": 10, "projection_count": 8}},
        },
    ):
        client = TestClient(app)
        response = client.get("/api/v1/learning/dashboard")

    assert response.status_code == 200
    data = response.json()
    assert data["projection_drift"]["total_drift_count"] == 2
    assert data["alerts"][0]["message"].startswith("2 projection drift item")


def test_system_config_endpoint_reads_runtime_config(monkeypatch):
    from main import app

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL", "gpt-test")
    monkeypatch.setenv("LLM_ROUTE", "azure")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("LLM_MAX_TOKENS", "8192")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.25")
    monkeypatch.setenv("EMBEDDING_MODEL", "embed-test")
    monkeypatch.setenv("EMBEDDING_BACKEND", "sentence_transformers")
    monkeypatch.setenv("EMBEDDING_DIM", "1536")
    monkeypatch.setenv("DEFAULT_TOP_K", "9")
    monkeypatch.setenv("SCORE_THRESHOLD", "0.65")
    monkeypatch.setenv("MAX_ITERATIONS", "4")
    monkeypatch.setenv("HYBRID_RRF_RANK_CONSTANT", "77")
    monkeypatch.setenv("DATABASE_URL", "postgresql://cfg_user:cfg_pass@db.example:5544/cfg_db")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant.example:7333")
    monkeypatch.setenv("NEO4J_URI", "bolt://neo.example:7687")

    client = TestClient(app)
    response = client.get("/api/v1/system/config")

    assert response.status_code == 200
    assert response.json() == {
        "llm": {
            "provider": "openai",
            "model": "gpt-test",
            "route": "azure",
            "base_url": "https://llm.example/v1",
            "max_tokens": 8192,
            "temperature": 0.25,
        },
        "embedding": {
            "model": "embed-test",
            "backend": "sentence_transformers",
            "dim": 1536,
        },
        "retrieval": {
            "default_top_k": 9,
            "score_threshold": 0.65,
            "max_iterations": 4,
            "rrf_k": 77,
        },
        "stores": {
            "postgres": "db.example",
            "qdrant": "qdrant.example",
            "neo4j": "bolt://neo.example:7687",
        },
    }


def test_learning_engine_endpoint_reads_runtime_last_run_file(monkeypatch, tmp_path):
    from main import app

    run_file = tmp_path / "agent-results.json"
    run_file.write_text(
        json.dumps(
            {
                "timestamp": "2026-05-06T03:00:00Z",
                "summary": {"passed": 12},
                "results": [{"id": 1}, {"id": 2}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEARNING_LAST_RUN_FILE", str(run_file))
    monkeypatch.setenv("DATABASE_URL", "postgresql://engine_user:engine_pass@db.example:5544/engine_db")

    class _FakeConn:
        async def fetchval(self, *_args, **_kwargs):
            return 3

        async def close(self):
            return None

    fake_asyncpg = SimpleNamespace(connect=AsyncMock(return_value=_FakeConn()))

    with patch.dict("sys.modules", {"asyncpg": fake_asyncpg}), patch(
        "app.api._count_recent_weak_or_failed_runs",
        return_value=2,
    ), patch(
        "app.api._build_learning_runtime_state_with_db_fallback",
        new=AsyncMock(return_value={}),
    ):
        client = TestClient(app)
        response = client.get("/api/v1/learning/engine")

    assert response.status_code == 200
    data = response.json()
    assert data["trigger_mode"] == "manual"
    assert data["last_run"]["file"] == str(run_file.resolve())
    assert data["last_run"]["summary"] == {"passed": 12}
    assert data["last_run"]["result_count"] == 2
    assert data["signals_24h"] == {
        "weak_or_failed_runs": 2,
        "pending_negative_feedback_with_text": 3,
    }
    assert "agent-results.json" in data["trigger_description"]
