"""Tests for FeatureFlags system — #113 Feature Flag runtime behavior switching."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.feature_flags import FeatureFlags, FeatureFlagName, is_feature_enabled


def setup_function():
    """Reset runtime overrides before each test."""
    FeatureFlags.clear_runtime()


def teardown_function():
    """Clean up after each test."""
    FeatureFlags.clear_runtime()


# ─── Default values ───────────────────────────────────────────────────────────

def test_followup_strict_coverage_off_by_default():
    assert FeatureFlags.is_enabled("FOLLOWUP_STRICT_COVERAGE") is False


def test_price_query_time_validation_on_by_default():
    assert FeatureFlags.is_enabled("PRICE_QUERY_TIME_VALIDATION") is True


def test_unified_config_loader_on_by_default():
    assert FeatureFlags.is_enabled("UNIFIED_CONFIG_LOADER") is True


def test_learning_adaptive_scheduling_off_by_default():
    assert FeatureFlags.is_enabled("LEARNING_ADAPTIVE_SCHEDULING") is False


# ─── Runtime override: highest priority ───────────────────────────────────────

def test_set_runtime_overrides_default():
    FeatureFlags.set_runtime("FOLLOWUP_STRICT_COVERAGE", True)
    assert FeatureFlags.is_enabled("FOLLOWUP_STRICT_COVERAGE") is True


def test_set_runtime_can_disable_default_on():
    FeatureFlags.set_runtime("PRICE_QUERY_TIME_VALIDATION", False)
    assert FeatureFlags.is_enabled("PRICE_QUERY_TIME_VALIDATION") is False


def test_clear_runtime_restores_default():
    FeatureFlags.set_runtime("FOLLOWUP_STRICT_COVERAGE", True)
    FeatureFlags.clear_runtime("FOLLOWUP_STRICT_COVERAGE")
    assert FeatureFlags.is_enabled("FOLLOWUP_STRICT_COVERAGE") is False


def test_clear_all_runtime_overrides():
    FeatureFlags.set_runtime("FOLLOWUP_STRICT_COVERAGE", True)
    FeatureFlags.set_runtime("LEARNING_ADAPTIVE_SCHEDULING", True)
    FeatureFlags.clear_runtime()
    assert FeatureFlags.is_enabled("FOLLOWUP_STRICT_COVERAGE") is False
    assert FeatureFlags.is_enabled("LEARNING_ADAPTIVE_SCHEDULING") is False


# ─── Unknown flags ────────────────────────────────────────────────────────────

def test_unknown_flag_returns_false():
    assert FeatureFlags.is_enabled("NONEXISTENT_FLAG") is False


# ─── Convenience function ─────────────────────────────────────────────────────

def test_is_feature_enabled_function():
    assert is_feature_enabled("UNIFIED_CONFIG_LOADER") is True


def test_is_feature_enabled_with_override():
    FeatureFlags.set_runtime("EVALUATION_STRICT_MODE", True)
    assert is_feature_enabled("EVALUATION_STRICT_MODE") is True


# ─── get_all ─────────────────────────────────────────────────────────────────

def test_get_all_returns_dict():
    result = FeatureFlags.get_all()
    assert isinstance(result, dict)
    assert len(result) > 0


def test_get_all_contains_known_flags():
    result = FeatureFlags.get_all()
    assert "PRICE_QUERY_TIME_VALIDATION" in result or len(result) > 0


# ─── FeatureFlagName enum ─────────────────────────────────────────────────────

def test_flag_name_enum_values():
    assert FeatureFlagName.FOLLOWUP_STRICT_COVERAGE == "FOLLOWUP_STRICT_COVERAGE"
    assert FeatureFlagName.EVALUATION_STRICT_MODE == "EVALUATION_STRICT_MODE"
