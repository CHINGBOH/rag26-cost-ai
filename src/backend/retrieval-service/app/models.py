"""
API 请求/响应模型（最小化复制）
兼容 unified_api.py 和 rag_api_service.py 的字段差异
"""

from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field, model_validator


class SearchRequest(BaseModel):
    query: str = Field(..., description="搜索查询文本")
    top_k: int = Field(default=10, ge=1, le=100)
    mode: str = Field(default="hybrid", description="搜索模式: vector|keyword|graph|hybrid")
    filters: Dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[str] = None


class RerankRequest(BaseModel):
    query: str
    documents: Optional[List[Dict[str, Any]]] = Field(default=None, description="文档列表（unified_api 风格）")
    candidates: Optional[List[str]] = Field(default=None, description="候选文本列表（rag_api_service 风格）")
    top_k: int = Field(default=10, ge=1, le=100)

    @model_validator(mode="after")
    def check_documents_or_candidates(self):
        if self.documents is None and self.candidates is None:
            raise ValueError("必须提供 documents 或 candidates 之一")
        return self


class RerankResponse(BaseModel):
    results: List[Dict[str, Any]]
    query: str


class EvaluationRequest(BaseModel):
    query: str
    retrieved_chunks: List[Dict[str, Any]]
    generated_answer: str
    history_rounds: int = 0


class EvaluationResponse(BaseModel):
    completeness: float
    consistency: float
    confidence: float
    information_gain: float
    source_diversity: float
    fact_consistency: float
    coverage_estimate: float


class DecomposeRequest(BaseModel):
    query: str


class DecomposeResponse(BaseModel):
    sub_queries: List[Dict[str, Any]]
    original_query: str
