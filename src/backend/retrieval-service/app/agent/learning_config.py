"""
Canonical JSON config entrypoint for the learning module.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


def _default_learning_config_path() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "config" / "modules" / "learning.json"
        if candidate.exists():
            return candidate
    # Tolerant fallback: container layout has fewer parents than host (#154)
    parents = current.parents
    root = parents[5] if len(parents) > 5 else parents[-1]
    return root / "config" / "modules" / "learning.json"


class FailureMonitorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    failure_threshold: float = Field(ge=0.0, le=1.0)
    window_size: int = Field(ge=1)
    min_window_samples: int = Field(ge=1)


class ProblemDetectorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    continuous_failure_threshold: int = Field(ge=1)
    repeat_question_threshold: int = Field(ge=1)
    negative_feedback_frequency_threshold: float = Field(ge=0.0, le=1.0)
    latency_p95_threshold_ms: int = Field(ge=1)


class GapRetestListenerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    interval_seconds: int = Field(default=300, ge=60)
    startup_delay_seconds: int = Field(default=60, ge=0)
    limit: int = Field(default=20, ge=1, le=200)
    max_live_retests: int = Field(default=3, ge=1, le=20)
    consultation_endpoint: str = "http://localhost:8002/api/v1/agent"
    consultation_timeout_seconds: int = Field(default=90, ge=5, le=180)
    max_iterations: int = Field(default=3, ge=1, le=5)
    observation_window_days: int = Field(default=7, ge=1)
    projection_reconcile_enabled: bool = True
    projection_reconcile_limit: int = Field(default=200, ge=1, le=500)
    fixed_state_invalidation_enabled: bool = True
    fixed_state_invalidation_limit: int = Field(default=100, ge=1, le=500)
    repair_promotion_enabled: bool = True
    repair_promotion_min_keep_open_evidence: int = Field(default=2, ge=1, le=20)
    repair_promotion_issue_number: int | None = Field(default=None, ge=1)
    repair_promotion_issue_url: str | None = None
    actor: str = "learning_gap_listener"
    dry_run: bool = False
    active_only: bool = True


class CuratorConfig(BaseModel):
    """#174: Curator 每周层配置。"""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    cron_day_of_week: int = Field(default=6, ge=0, le=6)   # 0=Mon ... 6=Sun
    cron_hour: int = Field(default=4, ge=0, le=23)          # UTC
    cron_minute: int = Field(default=0, ge=0, le=59)
    skill_archive_days: int = Field(default=30, ge=7, le=365)
    peripheral_purge_days: int = Field(default=7, ge=1, le=60)
    errors_promotion_threshold: int = Field(default=3, ge=2, le=20)
    max_candidates_per_domain: int = Field(default=1000, ge=100, le=5000)
    dry_run: bool = False


class LearningModuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module: str
    version: int = Field(ge=1)
    failure_monitor: FailureMonitorConfig
    problem_detector: ProblemDetectorConfig
    gap_retest_listener: GapRetestListenerConfig = Field(default_factory=GapRetestListenerConfig)
    curator: CuratorConfig = Field(default_factory=CuratorConfig)


_cached_learning_config: LearningModuleConfig | None = None
_cached_learning_config_path: Path | None = None


def _coerce_env_value(value: str, current: object) -> object:
    if isinstance(current, bool):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(current, int) and not isinstance(current, bool):
        return int(value)
    if isinstance(current, float):
        return float(value)
    return value


def _apply_env_overrides(raw: dict) -> dict:
    prefix = "RAG__LEARNING__"
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        path = [part.lower() for part in key[len(prefix) :].split("__") if part]
        if not path:
            continue
        target = raw
        for part in path[:-1]:
            next_target = target.get(part)
            if not isinstance(next_target, dict):
                next_target = {}
                target[part] = next_target
            target = next_target
        leaf = path[-1]
        target[leaf] = _coerce_env_value(value, target.get(leaf))
    return raw


def load_learning_config(path: Path | None = None) -> LearningModuleConfig:
    config_path = (path or _default_learning_config_path()).resolve()
    raw = _apply_env_overrides(json.loads(config_path.read_text(encoding="utf-8")))
    config = LearningModuleConfig.model_validate(raw)
    logger.info(
        "learning_config.loaded module=%s version=%s path=%s loaded_at=%s",
        config.module,
        config.version,
        config_path,
        datetime.now(timezone.utc).isoformat(),
    )
    return config


def get_learning_config() -> LearningModuleConfig:
    global _cached_learning_config
    global _cached_learning_config_path

    if _cached_learning_config is None:
        _cached_learning_config_path = _default_learning_config_path().resolve()
        _cached_learning_config = load_learning_config(_cached_learning_config_path)
    return _cached_learning_config


def reload_learning_config(path: Path | None = None) -> LearningModuleConfig:
    global _cached_learning_config
    global _cached_learning_config_path

    _cached_learning_config_path = (path or _default_learning_config_path()).resolve()
    _cached_learning_config = load_learning_config(_cached_learning_config_path)
    return _cached_learning_config


def get_learning_config_path() -> Path:
    if _cached_learning_config_path is not None:
        return _cached_learning_config_path
    return _default_learning_config_path().resolve()
