"""
搜索类型定义
"""

from typing import List, Dict, Optional, Any
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class SearchMode(str, Enum):
    VECTOR = "vector"
    KEYWORD = "keyword"
    GRAPH = "graph"
    HYBRID = "hybrid"


class SearchStage(str, Enum):
    RECALL = "recall"
    RERANK = "rerank"
    FUSION = "fusion"
    FINAL = "final"


class SearchQuery(BaseModel):
    query_id: str
    text: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None

    # 搜索配置
    mode: SearchMode = Field(default=SearchMode.HYBRID)
    top_k: int = Field(default=10)
    filters: Dict[str, Any] = Field(default_factory=dict)

    # 上下文
    context: Optional[str] = None
    history: List[Dict[str, Any]] = Field(default_factory=list)

    # 时间戳
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class SearchResultItem(BaseModel):
    result_id: str
    chunk: Any  # DocumentChunk

    # 各阶段分数
    vector_score: float = Field(default=0.0)
    keyword_score: float = Field(default=0.0)
    graph_score: float = Field(default=0.0)
    rerank_score: float = Field(default=0.0)
    final_score: float = Field(default=0.0)

    # 融合权重
    fusion_weights: Dict[str, float] = Field(
        default_factory=lambda: {
            "rerank": 0.4,
            "vector": 0.3,
            "keyword": 0.2,
            "graph": 0.05,
            "time": 0.05,
        }
    )

    # 结果元数据
    stage: SearchStage = Field(default=SearchStage.FINAL)
    explanation: Optional[str] = None
    highlights: List[str] = Field(default_factory=list)


class SearchContext(BaseModel):
    context_id: str
    query: SearchQuery
    results: List[SearchResultItem] = Field(default_factory=list)

    # 性能指标
    latency_ms: float = Field(default=0.0)
    total_chunks_searched: int = Field(default=0)

    # 召回统计
    recall_stats: Dict[str, Any] = Field(default_factory=dict)

    # 时间戳
    started_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None

    def to_response(self) -> Dict[str, Any]:
        return {
            "context_id": self.context_id,
            "query": {
                "query_id": self.query.query_id,
                "text": self.query.text,
                "mode": self.query.mode.value,
            },
            "results": [
                {
                    "chunk_id": r.chunk.chunk_id if hasattr(r.chunk, "chunk_id") else str(r.chunk),
                    "content": r.chunk.content if hasattr(r.chunk, "content") else "",
                    "final_score": r.final_score,
                    "vector_score": r.vector_score,
                    "keyword_score": r.keyword_score,
                    "rerank_score": r.rerank_score,
                    "explanation": r.explanation,
                }
                for r in self.results[:10]
            ],
            "latency_ms": self.latency_ms,
            "total_results": len(self.results),
        }


class SearchResult(BaseModel):
    success: bool
    context: Optional[SearchContext] = None
    error: Optional[str] = None

    @staticmethod
    def ok(context: SearchContext) -> "SearchResult":
        return SearchResult(success=True, context=context)

    @staticmethod
    def fail(error: str) -> "SearchResult":
        return SearchResult(success=False, error=error)
