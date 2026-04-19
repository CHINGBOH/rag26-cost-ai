"""
领域层接口定义 (Ports)
使用 Protocol 定义弱耦合的接口契约
"""

from typing import Protocol, List, Optional, Any
from domain.models import Document, DocumentChunk
import numpy as np


# ============ 存储层接口 ============


class VectorStorePort(Protocol):
    """向量存储接口"""

    async def search(
        self, query_vector: np.ndarray, top_k: int = 30, score_threshold: float = 0.6
    ) -> List[tuple[Document, float]]:
        """
        向量相似度搜索

        Args:
            query_vector: 查询向量
            top_k: 返回结果数量
            score_threshold: 分数阈值

        Returns:
            (文档, 相似度分数) 列表
        """
        ...

    async def upsert(self, documents: List[DocumentChunk], vectors: np.ndarray) -> bool:
        """插入或更新文档"""
        ...

    async def delete(self, doc_ids: List[str]) -> bool:
        """删除文档"""
        ...

    def is_available(self) -> bool:
        """检查是否可用"""
        ...


class KeywordStorePort(Protocol):
    """关键词存储接口"""

    async def search(self, query: str, top_k: int = 20, min_score: float = 1.0) -> List[Document]:
        """关键词搜索"""
        ...

    async def index(self, documents: List[DocumentChunk]) -> bool:
        """索引文档"""
        ...

    async def delete(self, doc_ids: List[str]) -> bool:
        """删除文档"""
        ...

    def is_available(self) -> bool:
        """检查是否可用"""
        ...


class GraphStorePort(Protocol):
    """图存储接口"""

    async def expand_entities(
        self, entity_names: List[str], depth: int = 2, top_k: int = 10
    ) -> List[Document]:
        """实体扩展检索"""
        ...

    async def build_from_document(self, doc_id: str, chunks: List[DocumentChunk]) -> bool:
        """从文档构建图谱"""
        ...

    def is_available(self) -> bool:
        """检查是否可用"""
        ...


# ============ 模型层接口 ============


class EmbeddingModelPort(Protocol):
    """Embedding模型接口"""

    def encode(self, texts: str | List[str]) -> np.ndarray:
        """编码文本为向量"""
        ...

    def encode_queries(self, queries: str | List[str]) -> np.ndarray:
        """编码查询（添加指令前缀）"""
        ...

    @property
    def dimension(self) -> int:
        """向量维度"""
        ...


class RerankModelPort(Protocol):
    """Rerank模型接口"""

    def rerank(self, query: str, candidates: List[Document]) -> List[Document]:
        """精排候选文档"""
        ...

    def is_loaded(self) -> bool:
        """检查模型是否加载"""
        ...


# ============ 服务层接口 ============


class RetrieverPort(Protocol):
    """检索器接口"""

    async def retrieve(
        self, query: str, top_k: int = 10, enable_rerank: bool = True
    ) -> List[Document]:
        """执行检索"""
        ...


class IndexerPort(Protocol):
    """索引器接口"""

    async def index_document(
        self, doc_id: str, chunks: List[DocumentChunk], build_graph: bool = True
    ) -> bool:
        """索引文档"""
        ...


# ============ 事件总线接口 ============


class EventPublisherPort(Protocol):
    """事件发布接口"""

    async def publish(self, event: Any) -> None:
        """发布事件"""
        ...


class EventSubscriberPort(Protocol):
    """事件订阅接口"""

    async def subscribe(self, event_type: type, handler: Any) -> None:
        """订阅事件"""
        ...


# ============ 缓存接口 ============


class CachePort(Protocol):
    """缓存接口"""

    async def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        ...

    async def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        """设置缓存"""
        ...

    async def delete(self, key: str) -> bool:
        """删除缓存"""
        ...
