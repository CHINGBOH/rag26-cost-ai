"""Tests for DomainAdapter interface, CostConsultingAdapter, AdapterRegistry,
and ValidationPipeline. (Issue #164)"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure retrieval-service root is on the path.
_SVC_ROOT = Path(__file__).parent.parent
if str(_SVC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SVC_ROOT))

from app.agent.adapters.base import DomainAdapter, Entity, ValidationResult
from app.agent.adapters.cost_consulting import CostConsultingAdapter
from app.agent.adapters.registry import AdapterRegistry
from app.agent.validation_pipeline import ValidationPipeline, ValidationReport


# ── Helpers ───────────────────────────────────────────────────────────────────

class _ConcreteAdapter(DomainAdapter):
    """Minimal concrete subclass for testing ABC."""
    domain_id = "test-domain"
    agent_persona = "test"

    def validate_static(self, chunk):
        return ValidationResult(passed=True)

    def validate_runtime(self, chunk, sandbox):
        return ValidationResult(passed=True)

    def validate_factual(self, chunk, kb):
        return ValidationResult(passed=True)

    def extract_entities(self, chunk):
        return []

    def seed_skills(self):
        return []

    def classify_hallucination(self, error):
        return "UNKNOWN"


# ── 1. DomainAdapter ABC is abstract ──────────────────────────────────────────

def test_domain_adapter_cannot_be_instantiated():
    with pytest.raises(TypeError):
        DomainAdapter()  # type: ignore


def test_domain_adapter_concrete_subclass_instantiates():
    adapter = _ConcreteAdapter()
    assert adapter.domain_id == "test-domain"


# ── 2. CostConsultingAdapter — validate_static (valid quota) ─────────────────

def test_validate_static_passes_when_entity_exists():
    entity_store = lambda qn: True
    adapter = CostConsultingAdapter(entity_store=entity_store)
    result = adapter.validate_static("定额编号 010101001 用于土方开挖。")
    assert result.passed


# ── 3. CostConsultingAdapter — validate_static (invalid quota) ───────────────

def test_validate_static_fails_with_symbol_hallucination():
    entity_store = lambda qn: False  # nothing exists
    adapter = CostConsultingAdapter(entity_store=entity_store)
    chunk = "根据定额010101001计算人工费。"
    result = adapter.validate_static(chunk)
    assert not result.passed
    assert result.error_type == "SYMBOL_HALLUCINATION"
    assert "010101001" in result.error_location


def test_validate_static_skips_check_when_no_entity_store():
    adapter = CostConsultingAdapter(entity_store=None)
    result = adapter.validate_static("定额010101001单价为10元。")
    assert result.passed


# ── 4. CostConsultingAdapter — validate_factual (citation hallucination) ──────

def test_validate_factual_fails_on_missing_cited_source():
    adapter = CostConsultingAdapter()
    chunk = "根据《第三册通用安装工程》第3章规定，费率为15%。"
    kb = [{"doc_filename": "第一册建筑工程.pdf", "source": "第一册"}]
    result = adapter.validate_factual(chunk, kb)
    assert not result.passed
    assert result.error_type == "FACTUAL_CONTRADICTION"


# ── 5. CostConsultingAdapter — validate_factual (valid citations) ─────────────

def test_validate_factual_passes_when_citation_in_kb():
    adapter = CostConsultingAdapter()
    chunk = "根据《第二册电气设备安装工程》第5章，综合费率为12%。"
    kb = [{"doc_filename": "第二册电气设备安装工程.pdf"}]
    result = adapter.validate_factual(chunk, kb)
    assert result.passed


def test_validate_factual_passes_with_empty_kb():
    adapter = CostConsultingAdapter()
    result = adapter.validate_factual("无引用内容", kb=None)
    assert result.passed


# ── 6. CostConsultingAdapter — extract_entities ───────────────────────────────

def test_extract_entities_returns_quota_and_material():
    adapter = CostConsultingAdapter()
    chunk = "使用定额010101001，主材为C30混凝土，综合单价为580元/m³。"
    entities = adapter.extract_entities(chunk)
    types = {e.entity_type for e in entities}
    # quota_number and material should both appear
    assert "quota_number" in types
    assert "material" in types


# ── 7. CostConsultingAdapter — seed_skills ────────────────────────────────────

def test_seed_skills_returns_three_entries():
    adapter = CostConsultingAdapter()
    skills = adapter.seed_skills()
    assert len(skills) == 3
    names = {s["name"] for s in skills}
    assert "quota-lookup" in names
    assert "formula-verify" in names
    assert "chapter-navigate" in names


# ── 8. CostConsultingAdapter — classify_hallucination ────────────────────────

def test_classify_hallucination_maps_symbol():
    adapter = CostConsultingAdapter()
    err = ValidationResult(passed=False, error_type="SYMBOL_HALLUCINATION")
    label = adapter.classify_hallucination(err)
    assert label == "定额编号不存在"


def test_classify_hallucination_maps_factual():
    adapter = CostConsultingAdapter()
    err = ValidationResult(passed=False, error_type="FACTUAL_CONTRADICTION")
    label = adapter.classify_hallucination(err)
    assert label == "引用章节或文档不存在"


# ── 9. ValidationPipeline — all steps pass ───────────────────────────────────

def test_validation_pipeline_all_pass():
    adapter = CostConsultingAdapter(entity_store=lambda _: True)
    pipeline = ValidationPipeline(adapter)
    report = pipeline.run("无定额编号，无引用文献的普通文本。")
    assert report.passed
    assert report.hallucination_type is None


# ── 10. ValidationPipeline — correction loop max retries ─────────────────────

def test_validation_pipeline_max_retry_records_error(tmp_path, monkeypatch):
    monkeypatch.setenv("ERRORS_MD_PATH", str(tmp_path / "ERRORS.md"))

    # Re-import to pick up the monkeypatched env var
    import importlib
    import app.agent.validation_pipeline as vp_mod
    importlib.reload(vp_mod)
    ValidationPipelineReloaded = vp_mod.ValidationPipeline

    entity_store = lambda _: False  # every quota fails
    adapter = CostConsultingAdapter(entity_store=entity_store)

    # correction_fn always returns the same chunk (no improvement)
    pipeline = ValidationPipelineReloaded(adapter, correction_fn=lambda chunk, err: chunk)
    report = pipeline.run("定额010101001")

    assert not report.passed
    assert report.hallucination_type == "SYMBOL_HALLUCINATION"
    assert (tmp_path / "ERRORS.md").exists()


# ── 11. AdapterRegistry — register and get ───────────────────────────────────

def test_adapter_registry_register_and_get():
    AdapterRegistry.register(_ConcreteAdapter)
    adapter = AdapterRegistry.get("test-domain")
    assert isinstance(adapter, _ConcreteAdapter)
    # Cleanup to avoid polluting other tests
    AdapterRegistry._registry.pop("test-domain", None)


def test_adapter_registry_raises_for_unknown_domain():
    with pytest.raises(KeyError, match="nonexistent"):
        AdapterRegistry.get("nonexistent")


# ── 12. AdapterRegistry — AGENT_DOMAIN_ID env var ───────────────────────────

def test_adapter_registry_get_active_uses_env_var(monkeypatch):
    monkeypatch.setenv("AGENT_DOMAIN_ID", "construction-cost")
    adapter = AdapterRegistry.get_active()
    assert isinstance(adapter, CostConsultingAdapter)


def test_adapter_registry_construction_cost_registered():
    assert "construction-cost" in AdapterRegistry.available()
