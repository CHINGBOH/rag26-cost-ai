"""
基础设施层 - 向量存储适配器
实现 VectorStorePort 接口
"""

from typing import List, Tuple
import asyncio
import numpy as np
from qdrant_client import QdrantClient as Qdrant
from qdrant_client.models import Distance, VectorParams, PointStruct

from domain.models import Document, DocumentChunk
from domain.ports import VectorStorePort
from config.settings import VectorStoreConfig


class QdrantVectorStoreAdapter(VectorStorePort):
    """
    Qdrant 向量存储适配器

    使用余弦相似度进行向量检索
    """

    def __init__(self, config: VectorStoreConfig):
        self.config = config
        self._client: Qdrant | None = None
        self._connect()

    def _connect(self) -> None:
        """连接到 Qdrant"""
        try:
            self._client = Qdrant(host=self.config.host, port=self.config.port)

            # 检查/创建集合
            collections = self._client.get_collections().collections
            collection_names = [c.name for c in collections]

            if self.config.collection_name not in collection_names:
                self._client.create_collection(
                    collection_name=self.config.collection_name,
                    vectors_config=VectorParams(
                        size=self.config.vector_size, distance=Distance.COSINE
                    ),
                )
        except Exception as e:
            print(f"Qdrant 连接失败: {e}")
            self._client = None

    def is_available(self) -> bool:
        """检查是否可用"""
        if self._client is None:
            return False
        try:
            self._client.get_collections()
            return True
        except Exception:
            return False

    async def search(
        self, query_vector: np.ndarray, top_k: int = 30, score_threshold: float = 0.6
    ) -> List[Tuple[Document, float]]:
        """
        向量相似度搜索

        使用余弦相似度: cos(θ) = (A·B) / (||A|| × ||B||)
        """
        if not self.is_available():
            return []

        try:
            # 将同步的client.search调用转移到线程池执行
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,  # 使用默认线程池执行器
                lambda: self._client.search(
                    collection_name=self.config.collection_name,
                    query_vector=query_vector.tolist(),
                    limit=top_k,
                    score_threshold=score_threshold,
                ),
            )

            documents = []
            for result in results:
                doc = Document(
                    id=result.id,
                    content=result.payload.get("content", ""),
                    doc_id=result.payload.get("doc_id", ""),
                    title=result.payload.get("title", ""),
                    page=result.payload.get("page", 0),
                    section=result.payload.get("section", ""),
                    chunk_type=result.payload.get("chunk_type", "paragraph"),
                    metadata={
                        k: v
                        for k, v in result.payload.items()
                        if k not in ["content", "doc_id", "title", "page", "section", "chunk_type"]
                    },
                )
                documents.append((doc, result.score))

            return documents

        except Exception as e:
            print(f"向量搜索失败: {e}")
            return []

    async def upsert(self, documents: List[DocumentChunk], vectors: np.ndarray) -> bool:
        """插入或更新文档"""
        if not self.is_available():
            return False

        try:
            points = []
            for i, doc in enumerate(documents):
                point = PointStruct(
                    id=doc.id,
                    vector=vectors[i].tolist(),
                    payload={
                        "content": doc.content,
                        "doc_id": doc.doc_id,
                        "title": doc.doc_title,
                        "page": doc.page,
                        "section": doc.section,
                        "chunk_type": doc.chunk_type,
                        **doc.metadata,
                    },
                )
                points.append(point)

            # 将同步的client.upsert调用转移到线程池执行
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self._client.upsert(
                    collection_name=self.config.collection_name, points=points
                ),
            )
            return True

        except Exception as e:
            print(f"向量插入失败: {e}")
            return False

    async def delete(self, doc_ids: List[str]) -> bool:
        """删除文档"""
        if not self.is_available():
            return False

        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            # 将同步的client.delete调用转移到线程池执行
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self._client.delete(
                    collection_name=self.config.collection_name,
                    points_selector=Filter(
                        must=[
                            FieldCondition(key="doc_id", match=MatchValue(value=doc_id))
                            for doc_id in doc_ids
                        ]
                    ),
                ),
            )
            return True

        except Exception as e:
            print(f"向量删除失败: {e}")
            return False


class MemoryVectorStoreAdapter(VectorStorePort):
    """
    内存向量存储适配器

    用于测试和开发环境
    """

    def __init__(self, config: VectorStoreConfig | None = None):
        self._storage: dict[str, tuple[DocumentChunk, np.ndarray]] = {}

    def is_available(self) -> bool:
        return True

    async def search(
        self, query_vector: np.ndarray, top_k: int = 30, score_threshold: float = 0.6
    ) -> List[Tuple[Document, float]]:
        """内存搜索 - 手动计算余弦相似度"""
        query_norm = np.linalg.norm(query_vector)

        scores = []
        for doc_id, (doc, vector) in self._storage.items():
            # 计算余弦相似度
            dot_product = np.dot(query_vector, vector)
            doc_norm = np.linalg.norm(vector)

            if doc_norm == 0 or query_norm == 0:
                similarity = 0.0
            else:
                similarity = dot_product / (query_norm * doc_norm)

            if similarity >= score_threshold:
                document = Document(
                    id=doc.id,
                    content=doc.content,
                    doc_id=doc.doc_id,
                    title=doc.doc_title,
                    page=doc.page,
                    section=doc.section,
                    chunk_type=doc.chunk_type,
                    metadata=doc.metadata,
                )
                scores.append((document, similarity))

        # 按分数排序
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    async def upsert(self, documents: List[DocumentChunk], vectors: np.ndarray) -> bool:
        """插入到内存"""
        for i, doc in enumerate(documents):
            self._storage[doc.id] = (doc, vectors[i])
        return True

    async def delete(self, doc_ids: List[str]) -> bool:
        """从内存删除"""
        for doc_id in doc_ids:
            keys_to_delete = [
                k for k in self._storage.keys() if self._storage[k][0].doc_id == doc_id
            ]
            for k in keys_to_delete:
                del self._storage[k]
        return True
