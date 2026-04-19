"""
召回精排架构模块

提供多路召回、Cross-Encoder 精排、分数融合和上下文增强功能。
"""

from .multi_stage_retriever import (
    MultiStageRetriever,
    VectorRetriever,
    KeywordRetriever,
    GraphRetriever,
    Reranker,
    FusionScorer,
    Document,
    RetrievalResult,
    QueryType,
)

from .vector_store import (
    QdrantClient,
    EmbeddingService,
    VectorStorePipeline,
    VectorDocument,
)

from .keyword_store import (
    ElasticsearchClient,
    KeywordStorePipeline,
    KeywordDocument,
)

from .graph_store import (
    Neo4jClient,
    GraphBuilder,
    Entity,
    Relationship,
    GraphDocument,
)

from .context_enhancer import (
    ContextEnhancer,
    ContextStrategy,
    RAGContextBuilder,
    ContextChunk,
    EnhancedResult,
)

from .rag_pipeline import (
    RAGPipeline,
    RAGResponse,
)

__all__ = [
    # 多阶段召回
    "MultiStageRetriever",
    "VectorRetriever",
    "KeywordRetriever",
    "GraphRetriever",
    "Reranker",
    "FusionScorer",
    "Document",
    "RetrievalResult",
    "QueryType",
    # 向量存储
    "QdrantClient",
    "EmbeddingService",
    "VectorStorePipeline",
    "VectorDocument",
    # 关键词存储
    "ElasticsearchClient",
    "KeywordStorePipeline",
    "KeywordDocument",
    # 图谱存储
    "Neo4jClient",
    "GraphBuilder",
    "Entity",
    "Relationship",
    "GraphDocument",
    # 上下文增强
    "ContextEnhancer",
    "ContextStrategy",
    "RAGContextBuilder",
    "ContextChunk",
    "EnhancedResult",
    # RAG Pipeline
    "RAGPipeline",
    "RAGResponse",
]
