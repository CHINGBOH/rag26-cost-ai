"""Tests for ParamRegistry — #114 unified parameter management."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.param_registry import ParamRegistry, ParamCategory, param


def setup_function():
    """Clear runtime overrides before each test (leave registered params)."""
    ParamRegistry.clear_runtime()


def teardown_function():
    ParamRegistry.clear_runtime()


# ─── Registration ─────────────────────────────────────────────────────────────

def test_register_and_get():
    ParamRegistry.register(
        name="_test_threshold",
        value=0.75,
        rationale="Unit test sentinel value",
        category=ParamCategory.FOLLOWUP,
        source="tests/test_param_registry.py",
    )
    assert ParamRegistry.get("_test_threshold") == 0.75


def test_register_requires_rationale():
    """register() should succeed; audit() reveals undocumented params."""
    ParamRegistry.register(
        name="_test_no_rationale",
        value=42,
        rationale="",
        category=ParamCategory.FOLLOWUP,
        source="tests/test_param_registry.py",
    )
    audit = ParamRegistry.audit()
    assert "_test_no_rationale" in audit.get("missing_rationale", [])


def test_param_function_convenience():
    ParamRegistry.register(
        name="_test_param_fn",
        value=3,
        rationale="Test",
        category=ParamCategory.FOLLOWUP,
        source="tests/test_param_registry.py",
    )
    assert param("_test_param_fn") == 3


def test_param_function_returns_default_for_unknown():
    assert param("_totally_unknown_xyz", default=99) == 99


# ─── Runtime override ─────────────────────────────────────────────────────────

def test_set_runtime_overrides_registered_value():
    ParamRegistry.register(
        name="_test_rt_override",
        value=0.5,
        rationale="Test",
        category=ParamCategory.FOLLOWUP,
        source="tests/test_param_registry.py",
    )
    ParamRegistry.set_runtime("_test_rt_override", 0.9)
    assert ParamRegistry.get("_test_rt_override") == 0.9


def test_clear_runtime_restores_registered_value():
    ParamRegistry.register(
        name="_test_rt_clear",
        value=0.5,
        rationale="Test",
        category=ParamCategory.FOLLOWUP,
        source="tests/test_param_registry.py",
    )
    ParamRegistry.set_runtime("_test_rt_clear", 0.9)
    ParamRegistry.clear_runtime("_test_rt_clear")
    assert ParamRegistry.get("_test_rt_clear") == 0.5


# ─── default_params registration ─────────────────────────────────────────────

def test_default_params_register_all():
    from config.default_params import register_all
    register_all()
    # After registration, known params should be accessible
    val = param("followup_coverage_high", default=None)
    assert val is not None


def test_followup_coverage_high_value():
    from config.default_params import register_all
    register_all()
    val = param("followup_coverage_high")
    assert 0.5 <= val <= 0.9


def test_followup_coverage_med_below_high():
    from config.default_params import register_all
    register_all()
    high = param("followup_coverage_high")
    med = param("followup_coverage_med")
    assert med < high


# ─── Audit ────────────────────────────────────────────────────────────────────

def test_audit_returns_dict():
    result = ParamRegistry.audit()
    assert isinstance(result, dict)


def test_get_all_returns_registered_params():
    ParamRegistry.register(
        name="_test_all_check",
        value=1,
        rationale="Test",
        category=ParamCategory.FOLLOWUP,
        source="tests/test_param_registry.py",
    )
    all_params = ParamRegistry.get_all()
    assert "_test_all_check" in all_params


def test_get_by_category():
    ParamRegistry.register(
        name="_test_cat_check",
        value=7,
        rationale="Test category filter",
        category=ParamCategory.FOLLOWUP,
        source="tests/test_param_registry.py",
    )
    followup_params = ParamRegistry.get_by_category(ParamCategory.FOLLOWUP)
    assert "_test_cat_check" in followup_params
