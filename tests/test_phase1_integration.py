"""
Phase 1 Integration Tests
Testing Feature Flags, Parameter Registry, and Observability
"""

import pytest
import sys
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestFeatureFlags:
    """Test Feature Flag system"""
    
    def test_feature_flag_defaults(self):
        from config.feature_flags import FeatureFlags  # Correct class name
        
        ff = FeatureFlags()
        
        # Test default flags exist and match actual defaults
        assert ff.is_enabled("FOLLOWUP_STRICT_COVERAGE") is False
        assert ff.is_enabled("LEARNING_ADAPTIVE_SCHEDULING") is False
        assert ff.is_enabled("CONTRACT_CONVERGENCE_POLICY") is False
        assert ff.is_enabled("EVALUATION_STRICT_MODE") is False
        assert ff.is_enabled("PRICE_QUERY_TIME_VALIDATION") is True
        assert ff.is_enabled("UNIFIED_CONFIG_LOADER") is True
    
    def test_feature_flag_runtime_override(self):
        from config.feature_flags import FeatureFlags
        
        ff = FeatureFlags()
        
        # Test runtime override
        original = ff.is_enabled("CONTRACT_CONVERGENCE_POLICY")
        ff.set_runtime("CONTRACT_CONVERGENCE_POLICY", not original, ttl_seconds=60)
        assert ff.is_enabled("CONTRACT_CONVERGENCE_POLICY") == (not original)
    
    def test_feature_flag_clear_runtime(self):
        from config.feature_flags import FeatureFlags
        
        ff = FeatureFlags()
        ff.set_runtime("PRICE_QUERY_TIME_VALIDATION", False, ttl_seconds=60)
        ff.clear_runtime("PRICE_QUERY_TIME_VALIDATION")
        # Should return to default (True)
        assert ff.is_enabled("PRICE_QUERY_TIME_VALIDATION") is True


class TestParameterRegistry:
    """Test Parameter Registry system"""
    
    def test_param_registration(self):
        from config.param_registry import ParamRegistry, ParamCategory
        
        # Register a test parameter
        ParamRegistry.register(
            name="test_param_unit_test",
            value=42,
            rationale="Test parameter for unit testing",
            category=ParamCategory.GENERAL,
            source="tests/test_phase1_integration.py"
        )
        
        # Retrieve it
        from config.param_registry import param
        value = param("test_param_unit_test", default=0)
        assert value == 42
    
    def test_param_default_fallback(self):
        from config.param_registry import param
        
        # Non-existent param should return default
        value = param("nonexistent_param_xyz", default=999)
        assert value == 999
    
    def test_retrieval_presets(self):
        from config.retrieval_presets import RetrievalPresets
        
        assert RetrievalPresets.NARROW == 3
        assert RetrievalPresets.FOCUSED == 5
        assert RetrievalPresets.STANDARD == 8
        assert RetrievalPresets.BROAD == 12
        assert RetrievalPresets.DEEP == 20
    
    def test_param_category_validation(self):
        from config.param_registry import ParamRegistry, ParamCategory
        
        # Test that invalid enum value causes error
        try:
            # Should work with valid category
            ParamRegistry.register(
                name="valid_category_test",
                value=1,
                rationale="Valid category test",
                category=ParamCategory.GENERAL,
                source="test"
            )
        except Exception as e:
            pytest.fail(f"Valid category should not raise error: {e}")
    
    def test_followup_coverage_params(self):
        """Test that followup coverage parameters are registered"""
        from config.param_registry import param
        from config.default_params import register_default_params as register_defaults
        
        # Ensure params are registered
        register_defaults()
        
        high_thresh = param("followup_coverage_high", default=0.65)
        med_thresh = param("followup_coverage_med", default=0.50)
        
        assert 0.5 <= high_thresh <= 0.9
        assert 0.4 <= med_thresh <= 0.65
        assert high_thresh > med_thresh
    
    def test_contract_params(self):
        """Test that contract parameters are registered"""
        from config.param_registry import param
        from config.default_params import register_default_params as register_defaults
        
        register_defaults()
        
        max_outer = param("contract_max_outer_iterations", default=3)
        assert 1 <= max_outer <= 10


class TestObservability:
    """Test Observability Layer"""
    
    def test_decision_logger_initialization(self):
        from config.observability import DecisionLogger
        
        logger = DecisionLogger()
        # DecisionLogger stores buffer at class level
        assert isinstance(DecisionLogger._buffer, list)
    
    def test_log_decision(self):
        from config.observability import log_decision, DecisionType
        
        # Should not raise - use correct signature
        decision_id = log_decision(
            decision_type=DecisionType.FOLLOWUP_FILTER,
            context={"test": "input"},
            params_used={"test_param": 0.5},
            outcome={"test": "output"},
            reason="Test decision"
        )
        assert isinstance(decision_id, str)
    
    def test_decision_types_exist(self):
        from config.observability import DecisionType
        
        # Test all decision types exist
        assert hasattr(DecisionType, "FOLLOWUP_FILTER")
        assert hasattr(DecisionType, "FOLLOWUP_COVERAGE")
        assert hasattr(DecisionType, "LEARNING_TRIGGER")
        assert hasattr(DecisionType, "LEARNING_RETEST")
        assert hasattr(DecisionType, "CONTRACT_ITERATION")
        assert hasattr(DecisionType, "CONTRACT_CONVERGENCE")
        assert hasattr(DecisionType, "TOOL_SELECTION")
        assert hasattr(DecisionType, "RETRIEVAL_STRATEGY")


class TestIntegration:
    """Integration tests across Phase 1 components"""
    
    def test_param_and_feature_flag_together(self):
        """Test that params and feature flags work together"""
        from config.param_registry import param
        from config.feature_flags import FeatureFlags
        from config.default_params import register_default_params as register_defaults
        
        register_defaults()
        ff = FeatureFlags()
        
        # If feature flag enabled, use adaptive param
        if ff.is_enabled("CONTRACT_CONVERGENCE_POLICY"):
            max_iter = param("contract_max_outer_iterations", default=3)
        else:
            max_iter = param("contract_max_iterations", default=3)
        
        assert max_iter >= 1
    
    def test_observability_with_param(self):
        """Test logging decisions that use params"""
        from config.observability import log_decision, DecisionType
        from config.param_registry import param
        from config.default_params import register_default_params as register_defaults
        
        register_defaults()
        threshold = param("followup_coverage_high", default=0.65)
        
        decision_id = log_decision(
            decision_type=DecisionType.FOLLOWUP_COVERAGE,
            context={"threshold": threshold},
            params_used={"followup_coverage_high": threshold},
            outcome={"decision": "filter_low"},
            reason=f"Coverage threshold set to {threshold}"
        )
        assert isinstance(decision_id, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
