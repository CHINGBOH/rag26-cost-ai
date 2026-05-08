"""
Agent Configuration Domain Models

Issue #125: Unified schema for frontend-backend contract.
Extracted from app/api.py to enable lightweight import (no deep service dependencies).

Schema mirrors @rag/shared AgentConfigSchema in packages/shared/src/types/agent-config.ts.
"""

from typing import Optional
from pydantic import BaseModel


PROVIDER_MAP: dict[str, str] = {
    "deepseek": "deepseek",
    "local": "ollama",
    "auto": "deepseek",
}

DEFAULT_PROVIDER = "deepseek"


class AgentRequest(BaseModel):
    """Sync agent request (POST /api/v1/agent)"""
    query: str
    session_id: Optional[str] = None
    max_iterations: int = 3
    llm_route: str = "deepseek"
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_engine: Optional[str] = None

    def resolve_llm_provider(self) -> str:
        """Infer provider from route if not explicitly set (Issue #125)."""
        if self.llm_provider:
            return self.llm_provider
        return PROVIDER_MAP.get(self.llm_route, DEFAULT_PROVIDER)


class AgentStreamRequest(BaseModel):
    """Streaming agent request (POST /api/v1/agent/stream)"""
    query: str
    session_id: Optional[str] = None
    max_iterations: int = 3
    score_threshold: float = 0.60
    top_k: int = 8
    search_mode: str = "hybrid"
    doc_types: list = []
    llm_route: str = "deepseek"
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_engine: Optional[str] = None

    def resolve_llm_provider(self) -> str:
        """Infer provider from route if not explicitly set (Issue #125)."""
        if self.llm_provider:
            return self.llm_provider
        return PROVIDER_MAP.get(self.llm_route, DEFAULT_PROVIDER)


def build_llm_config(request: AgentStreamRequest | AgentRequest) -> dict:
    """Build LLM config dict, always resolving provider (never None)."""
    return {
        "route_mode": request.llm_route,
        "provider": request.resolve_llm_provider(),
        "model": request.llm_model,
        "engine": request.llm_engine,
    }
