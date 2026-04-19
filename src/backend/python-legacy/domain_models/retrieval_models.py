"""
检索类型定义
"""

from typing import List, Dict, Optional, Any
from enum import Enum
from pydantic import BaseModel, Field


class RetrievalStrategy(str, Enum):
    MULTI_STAGE = "multi_stage"
    ITERATIVE = "iterative"
    ADAPTIVE = "adaptive"


class RetrievalConfig(BaseModel):
    # 召回配置
    vector_top_k: int = Field(default=30)
    keyword_top_k: int = Field(default=20)
    graph_top_k: int = Field(default=10)

    # 精排配置
    enable_rerank: bool = Field(default=True)
    rerank_top_k: int = Field(default=60)
    rerank_batch_size: int = Field(default=8)

    # 融合配置
    enable_fusion: bool = Field(default=True)
    fusion_weights: Dict[str, float] = Field(
        default_factory=lambda: {
            "rerank": 0.4,
            "vector": 0.3,
            "keyword": 0.2,
            "graph": 0.05,
            "time": 0.05,
        }
    )

    # 上下文配置
    context_strategy: str = Field(default="surrounding")
    context_window: int = Field(default=2)
    max_context_length: int = Field(default=2000)

    # 分数阈值
    score_threshold: float = Field(default=0.6)

    # 时间衰减
    time_decay_factor: float = Field(default=0.95)


class RetrievalRequest(BaseModel):
    query: str
    config: RetrievalConfig = Field(default_factory=RetrievalConfig)
    session_id: Optional[str] = None
    filters: Dict[str, Any] = Field(default_factory=dict)


class RetrievedDocument(BaseModel):
    doc_id: str
    chunk_id: str
    content: str
    score: float
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RetrievalResponse(BaseModel):
    request_id: str
    documents: List[RetrievedDocument]

    # 性能指标
    latency_ms: float = Field(default=0.0)

    # 召回统计
    stats: Dict[str, Any] = Field(default_factory=dict)

    # 融合详情
    fusion_details: Optional[Dict[str, Any]] = None
