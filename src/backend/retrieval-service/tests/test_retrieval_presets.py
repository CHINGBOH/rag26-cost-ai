"""
Tests for Issue #116: RetrievalPresets unified top_k

Validates that:
1. All preset values are correctly defined
2. Preset ordering is semantically correct (NARROW < FOCUSED < STANDARD < BROAD < DEEP)
3. graph.py uses RetrievalPresets (not hardcoded ints)
4. param_registry integration works
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from config.retrieval_presets import RetrievalPresets, RetrievalMultiplier


class TestRetrievalPresetValues:
    def test_narrow_is_3(self):
        assert RetrievalPresets.NARROW == 3

    def test_focused_is_5(self):
        assert RetrievalPresets.FOCUSED == 5

    def test_standard_is_8(self):
        assert RetrievalPresets.STANDARD == 8

    def test_broad_is_12(self):
        assert RetrievalPresets.BROAD == 12

    def test_deep_is_20(self):
        assert RetrievalPresets.DEEP == 20

    def test_ordering_is_ascending(self):
        assert (
            RetrievalPresets.NARROW
            < RetrievalPresets.FOCUSED
            < RetrievalPresets.STANDARD
            < RetrievalPresets.BROAD
            < RetrievalPresets.DEEP
        )

    def test_presets_are_int_compatible(self):
        """Presets must be usable as int in API calls."""
        assert isinstance(int(RetrievalPresets.NARROW), int)
        assert int(RetrievalPresets.STANDARD) == 8


class TestRetrievalMultiplierValues:
    def test_vector_fetch_multiplier(self):
        assert RetrievalMultiplier.VECTOR_FETCH == 2.0

    def test_text_fetch_multiplier(self):
        assert RetrievalMultiplier.TEXT_FETCH == 1.5

    def test_vector_fetch_greater_than_text(self):
        assert RetrievalMultiplier.VECTOR_FETCH > RetrievalMultiplier.TEXT_FETCH


class TestParamRegistryIntegration:
    def test_presets_registered_in_param_registry(self):
        from config.param_registry import ParamRegistry, ParamCategory
        all_params = ParamRegistry.get_all()
        assert "retrieval_preset_narrow" in all_params
        assert "retrieval_preset_standard" in all_params
        assert "retrieval_preset_broad" in all_params

    def test_registered_values_match_presets(self):
        from config.param_registry import ParamRegistry
        assert ParamRegistry.get("retrieval_preset_narrow") == RetrievalPresets.NARROW
        assert ParamRegistry.get("retrieval_preset_focused") == RetrievalPresets.FOCUSED
        assert ParamRegistry.get("retrieval_preset_standard") == RetrievalPresets.STANDARD
        assert ParamRegistry.get("retrieval_preset_broad") == RetrievalPresets.BROAD
        assert ParamRegistry.get("retrieval_preset_deep") == RetrievalPresets.DEEP

    def test_registered_category_is_retrieval(self):
        from config.param_registry import ParamRegistry, ParamCategory
        meta = ParamRegistry.get_all().get("retrieval_preset_standard")
        assert meta is not None
        assert meta.category == ParamCategory.RETRIEVAL


class TestGraphUsesPresets:
    def test_graph_imports_retrieval_presets(self):
        """Verify graph.py uses RetrievalPresets, not bare ints for top_k."""
        graph_path = PROJECT_ROOT / "app" / "agent" / "graph.py"
        content = graph_path.read_text(encoding="utf-8")
        assert "from config.retrieval_presets import RetrievalPresets" in content

    def test_no_bare_top_k_magic_numbers_in_graph(self):
        """graph.py should not have top_k=<digit> without RetrievalPresets."""
        import re
        graph_path = PROJECT_ROOT / "app" / "agent" / "graph.py"
        content = graph_path.read_text(encoding="utf-8")
        # Find top_k=<int> not using RetrievalPresets (neighbor_top_k is exempted)
        bare_topk = re.findall(r'(?<!neighbor_)top_k=\d+', content)
        assert bare_topk == [], f"Found bare top_k magic numbers: {bare_topk}"
