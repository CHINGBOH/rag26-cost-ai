import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agent.failure_monitor import FailureMonitor
from app.agent.learning_config import (
    get_learning_config,
    get_learning_config_path,
    load_learning_config,
    reload_learning_config,
)
from app.agent.problem_detector import ProblemDetector


def test_learning_config_loads_default_module_json():
    config = get_learning_config()

    assert config.module == "learning"
    assert config.version == 1
    assert config.failure_monitor.failure_threshold == 0.2
    assert config.problem_detector.continuous_failure_threshold == 3
    assert config.gap_retest_listener.enabled is True
    assert config.gap_retest_listener.active_only is True
    assert config.gap_retest_listener.projection_reconcile_enabled is True
    assert config.gap_retest_listener.projection_reconcile_limit == 200
    assert config.gap_retest_listener.fixed_state_invalidation_enabled is True
    assert config.gap_retest_listener.fixed_state_invalidation_limit == 100


def test_learning_components_read_thresholds_from_custom_json(tmp_path: Path):
    original_path = get_learning_config_path()
    custom_path = tmp_path / "learning.json"
    custom_path.write_text(
        json.dumps(
            {
                "module": "learning",
                "version": 2,
                "failure_monitor": {
                    "failure_threshold": 0.35,
                    "window_size": 24,
                    "min_window_samples": 12,
                },
                "problem_detector": {
                    "continuous_failure_threshold": 5,
                    "repeat_question_threshold": 4,
                    "negative_feedback_frequency_threshold": 0.45,
                    "latency_p95_threshold_ms": 7200,
                },
            }
        ),
        encoding="utf-8",
    )

    try:
        reload_learning_config(custom_path)
        monitor = FailureMonitor(db_pool=None)
        detector = ProblemDetector()

        assert monitor.FAILURE_THRESHOLD == 0.35
        assert monitor.WINDOW_SIZE == 24
        assert monitor.MIN_WINDOW_SAMPLES == 12
        assert detector.CONTINUOUS_FAILURE_THRESHOLD == 5
        assert detector.REPEAT_QUESTION_THRESHOLD == 4
        assert detector.NEGATIVE_FEEDBACK_FREQUENCY_THRESHOLD == 0.45
        assert detector.LATENCY_P95_THRESHOLD_MS == 7200
    finally:
        reload_learning_config(original_path)


def test_learning_config_applies_gap_listener_env_overrides(tmp_path: Path, monkeypatch):
    original_path = get_learning_config_path()
    custom_path = tmp_path / "learning.json"
    custom_path.write_text(
        json.dumps(
            {
                "module": "learning",
                "version": 2,
                "failure_monitor": {
                    "failure_threshold": 0.35,
                    "window_size": 24,
                    "min_window_samples": 12,
                },
                "problem_detector": {
                    "continuous_failure_threshold": 5,
                    "repeat_question_threshold": 4,
                    "negative_feedback_frequency_threshold": 0.45,
                    "latency_p95_threshold_ms": 7200,
                },
                "gap_retest_listener": {
                    "enabled": False,
                    "interval_seconds": 600,
                    "startup_delay_seconds": 120,
                    "limit": 10,
                    "max_live_retests": 2,
                    "consultation_endpoint": "http://localhost:8002/api/v1/agent",
                    "consultation_timeout_seconds": 30,
                    "max_iterations": 2,
                    "observation_window_days": 7,
                    "projection_reconcile_enabled": False,
                    "projection_reconcile_limit": 25,
                    "fixed_state_invalidation_enabled": False,
                    "fixed_state_invalidation_limit": 15,
                    "actor": "config_test",
                    "dry_run": True,
                    "active_only": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RAG__LEARNING__GAP_RETEST_LISTENER__ENABLED", "true")
    monkeypatch.setenv("RAG__LEARNING__GAP_RETEST_LISTENER__MAX_LIVE_RETESTS", "4")
    monkeypatch.setenv("RAG__LEARNING__GAP_RETEST_LISTENER__PROJECTION_RECONCILE_LIMIT", "40")
    monkeypatch.setenv("RAG__LEARNING__GAP_RETEST_LISTENER__FIXED_STATE_INVALIDATION_LIMIT", "30")

    try:
        config = reload_learning_config(custom_path)

        assert config.gap_retest_listener.enabled is True
        assert config.gap_retest_listener.max_live_retests == 4
        assert config.gap_retest_listener.projection_reconcile_enabled is False
        assert config.gap_retest_listener.projection_reconcile_limit == 40
        assert config.gap_retest_listener.fixed_state_invalidation_enabled is False
        assert config.gap_retest_listener.fixed_state_invalidation_limit == 30
    finally:
        reload_learning_config(original_path)


def test_learning_config_rejects_invalid_module_json(tmp_path: Path):
    invalid_path = tmp_path / "learning-invalid.json"
    invalid_path.write_text(
        json.dumps(
            {
                "module": "learning",
                "version": 1,
                "failure_monitor": {
                    "failure_threshold": 1.5,
                    "window_size": 0,
                    "min_window_samples": 0,
                },
                "problem_detector": {
                    "continuous_failure_threshold": 0,
                    "repeat_question_threshold": 0,
                    "negative_feedback_frequency_threshold": 1.2,
                    "latency_p95_threshold_ms": -1,
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_learning_config(invalid_path)
