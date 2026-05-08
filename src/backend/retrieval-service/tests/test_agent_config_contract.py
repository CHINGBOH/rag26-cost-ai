"""
Tests for Issue #125: Frontend-Backend Agent Config Contract

Validates that:
1. Frontend schema (@rag/shared AgentConfig) matches backend AgentRequest
2. llm_provider resolution works correctly
3. Backend handles None/undefined llm_provider gracefully
4. All fields map correctly between frontend and backend
"""

import sys
from pathlib import Path

# Bootstrap sys.path to service root
_svc_root = Path(__file__).resolve().parents[1]
if str(_svc_root) not in sys.path:
    sys.path.insert(0, str(_svc_root))

import pytest
from pydantic import ValidationError
from domain_models.agent_config import AgentRequest, AgentStreamRequest, build_llm_config


def test_agent_request_optional_llm_provider():
    """llm_provider 应该是可选字段"""
    request = AgentRequest(
        query="test",
        llm_route="deepseek",
        # llm_provider not provided
    )
    assert request.llm_provider is None


def test_resolve_llm_provider_from_route():
    """测试根据 llm_route 推断 llm_provider"""
    cases = [
        ("deepseek", "deepseek"),
        ("local", "ollama"),
        ("auto", "deepseek"),
    ]
    
    for route, expected_provider in cases:
        request = AgentRequest(query="test", llm_route=route)
        resolved = request.resolve_llm_provider()
        assert resolved == expected_provider, f"Route {route} should resolve to {expected_provider}"


def test_resolve_llm_provider_explicit_override():
    """如果显式指定 llm_provider，应该优先使用"""
    request = AgentRequest(
        query="test",
        llm_route="auto",  # 默认会推断为 deepseek
        llm_provider="custom_provider"  # 但显式指定了
    )
    resolved = request.resolve_llm_provider()
    assert resolved == "custom_provider"


def testbuild_llm_config_uses_resolver():
    """build_llm_config 应该使用 resolve_llm_provider"""
    request = AgentRequest(
        query="test",
        llm_route="local",  # 应该推断为 ollama
        llm_provider=None,
    )
    
    config = build_llm_config(request)
    
    assert config["provider"] == "ollama"  # 不是 None
    assert config["route_mode"] == "local"


def testbuild_llm_config_with_all_fields():
    """测试所有LLM配置字段"""
    request = AgentRequest(
        query="test",
        llm_route="deepseek",
        llm_provider="custom",
        llm_model="deepseek-chat",
        llm_engine="api",
    )
    
    config = build_llm_config(request)
    
    assert config["provider"] == "custom"
    assert config["route_mode"] == "deepseek"
    assert config["model"] == "deepseek-chat"
    assert config["engine"] == "api"


def test_agent_stream_request_same_behavior():
    """AgentStreamRequest 应该和 AgentRequest 行为一致"""
    stream_request = AgentStreamRequest(
        query="test",
        llm_route="local",
    )
    
    resolved = stream_request.resolve_llm_provider()
    assert resolved == "ollama"


def test_frontend_backend_field_mapping():
    """验证前端字段名映射到后端字段名"""
    # Frontend (JavaScript camelCase) -> Backend (Python snake_case)
    frontend_payload = {
        "query": "测试查询",
        "session_id": "sess-123",
        "max_iterations": 5,
        "score_threshold": 0.7,
        "top_k": 10,
        "search_mode": "hybrid",
        "doc_types": ["国标", "信息价"],
        "llm_route": "deepseek",
        "llm_provider": None,  # Frontend sends null/undefined
        "llm_model": "deepseek-chat",
        "llm_engine": "api",
    }
    
    # Backend Pydantic model
    request = AgentRequest(**frontend_payload)
    
    assert request.query == "测试查询"
    assert request.session_id == "sess-123"
    assert request.max_iterations == 5
    assert request.llm_route == "deepseek"
    assert request.llm_provider is None
    assert request.llm_model == "deepseek-chat"
    
    # Resolve should fill in the provider
    resolved_provider = request.resolve_llm_provider()
    assert resolved_provider == "deepseek"


def test_default_values_match_frontend():
    """后端默认值应该和前端 @rag/shared 默认值一致"""
    request = AgentRequest(query="test")
    
    # Check defaults from AgentRequest
    assert request.max_iterations == 3  # matches frontend DEFAULT_AGENT_CONFIG
    assert request.llm_route == "deepseek"  # matches frontend default
    
    # Check resolved provider
    assert request.resolve_llm_provider() == "deepseek"


def test_unknown_route_fallback():
    """未知 route 应该有合理的fallback"""
    request = AgentRequest(query="test", llm_route="unknown_route")
    resolved = request.resolve_llm_provider()
    
    # Should fallback to deepseek
    assert resolved == "deepseek"


def test_empty_llm_provider_string():
    """空字符串 llm_provider 应该被视为 None"""
    request = AgentRequest(
        query="test",
        llm_route="local",
        llm_provider="",  # Empty string
    )
    
    # Empty string is falsy in Python
    resolved = request.resolve_llm_provider()
    # Should fallback to route-based resolution
    assert resolved == "ollama"


def test_agent_request_validation():
    """测试 Pydantic 验证"""
    # Missing required field should raise
    with pytest.raises(ValidationError):
        AgentRequest()  # No query
    
    # Valid minimal request
    request = AgentRequest(query="test")
    assert request.query == "test"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
