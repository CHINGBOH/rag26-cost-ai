"""
基础设施层 - 向量存储适配器
实现 VectorStorePort 接口
"""

from typing import Any, List, Tuple
import asyncio
import inspect
import json
import numpy as np
from qdrant_client import QdrantClient as Qdrant
from qdrant_client.models import Distance, VectorParams, PointStruct

from domain.models import Document, DocumentChunk
from domain.ports import VectorStorePort
from config.settings import VectorStoreConfig

try:
    from pymilvus import MilvusClient
except ImportError:
    MilvusClient = None


def _call_with_supported_kwargs(target: Any, **kwargs: Any) -> Any:
    clean_kwargs = {key: value for key, value in kwargs.items() if value is not None}
    try:
        signature = inspect.signature(target)
    except (TypeError, ValueError):
        return target(**clean_kwargs)

    if any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    ):
        return target(**clean_kwargs)

    supported_kwargs = {
        key: value for key, value in clean_kwargs.items() if key in signature.parameters
    }
    return target(**supported_kwargs)


def _build_document_from_payload(record_id: str | int, payload: dict[str, Any]) -> Document:
    return Document(
        id=str(record_id),
        content=payload.get("content", ""),
        doc_id=payload.get("doc_id", ""),
        title=payload.get("title", ""),
        page=payload.get("page", 0),
        section=payload.get("section", ""),
        chunk_type=payload.get("chunk_type", "paragraph"),
        metadata={
            key: value
            for key, value in payload.items()
            if key not in {"content", "doc_id", "title", "page", "section", "chunk_type"}
        },
    )


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
                doc = _build_document_from_payload(result.id, result.payload)
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


class MilvusVectorStoreAdapter(VectorStorePort):
    """Milvus 向量存储适配器。"""

    def __init__(self, config: VectorStoreConfig):
        self.config = config
        self._client: Any | None = None
        self._connect()

    def _build_uri(self) -> str:
        if self.config.uri:
            return self.config.uri
        scheme = "https" if self.config.secure else "http"
        port = self.config.port if self.config.port != 6333 else 19530
        return f"{scheme}://{self.config.host}:{port}"

    def _connect(self) -> None:
        """连接到 Milvus 并确保集合存在。"""
        if MilvusClient is None:
            print("Milvus 客户端不可用: pymilvus 未安装")
            return

        password = self.config.password.get_secret_value() if self.config.password else ""
        token = f"{self.config.username}:{password}" if self.config.username and password else None

        try:
            self._client = _call_with_supported_kwargs(
                MilvusClient,
                uri=self._build_uri(),
                token=token,
                user=self.config.username or None,
                password=password or None,
                db_name=self.config.database,
                database=self.config.database,
            )
            self._ensure_collection()
        except Exception as e:
            print(f"Milvus 连接失败: {e}")
            self._client = None

    def _ensure_collection(self) -> None:
        if self._client is None:
            return

        try:
            exists = _call_with_supported_kwargs(
                self._client.has_collection,
                collection_name=self.config.collection_name,
            )
            if not exists:
                _call_with_supported_kwargs(
                    self._client.create_collection,
                    collection_name=self.config.collection_name,
                    dimension=self.config.vector_size,
                    metric_type=self.config.metric_type,
                    consistency_level=self.config.consistency_level,
                )
        except Exception as e:
            print(f"Milvus 集合初始化失败: {e}")
            self._client = None

    def _normalize_hits(self, results: Any) -> list[Any]:
        if isinstance(results, list) and results and isinstance(results[0], list):
            return results[0]
        if isinstance(results, list):
            return results
        return []

    def _extract_hit(self, hit: Any) -> tuple[str, dict[str, Any], float]:
        if isinstance(hit, dict):
            entity = hit.get("entity")
            payload = dict(entity) if isinstance(entity, dict) else {
                key: value
                for key, value in hit.items()
                if key not in {"id", "distance", "score", "entity", "vector"}
            }
            record_id = hit.get("id") or payload.get("id") or ""
            score = hit.get("distance", hit.get("score", 0.0))
            return str(record_id), payload, float(score or 0.0)

        entity = getattr(hit, "entity", None)
        payload = dict(entity) if isinstance(entity, dict) else {}
        record_id = getattr(hit, "id", payload.get("id", ""))
        score = getattr(hit, "distance", getattr(hit, "score", 0.0))
        return str(record_id), payload, float(score or 0.0)

    def is_available(self) -> bool:
        if self._client is None:
            return False
        try:
            _call_with_supported_kwargs(
                self._client.describe_collection,
                collection_name=self.config.collection_name,
            )
            return True
        except Exception:
            try:
                return bool(
                    _call_with_supported_kwargs(
                        self._client.has_collection,
                        collection_name=self.config.collection_name,
                    )
                )
            except Exception:
                return False

    async def search(
        self, query_vector: np.ndarray, top_k: int = 30, score_threshold: float = 0.6
    ) -> List[Tuple[Document, float]]:
        if not self.is_available():
            return []

        try:
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                lambda: _call_with_supported_kwargs(
                    self._client.search,
                    collection_name=self.config.collection_name,
                    data=[query_vector.tolist()],
                    limit=top_k,
                    search_params={"metric_type": self.config.metric_type},
                    output_fields=["content", "doc_id", "title", "page", "section", "chunk_type"],
                ),
            )

            documents = []
            for hit in self._normalize_hits(results):
                record_id, payload, score = self._extract_hit(hit)
                if self.config.metric_type != "L2" and score < score_threshold:
                    continue
                documents.append((_build_document_from_payload(record_id, payload), score))
            return documents
        except Exception as e:
            print(f"Milvus 向量搜索失败: {e}")
            return []

    async def upsert(self, documents: List[DocumentChunk], vectors: np.ndarray) -> bool:
        if not self.is_available():
            return False

        try:
            rows = []
            for index, doc in enumerate(documents):
                rows.append(
                    {
                        "id": doc.id,
                        "vector": vectors[index].tolist(),
                        "content": doc.content,
                        "doc_id": doc.doc_id,
                        "title": doc.doc_title,
                        "page": doc.page,
                        "section": doc.section,
                        "chunk_type": doc.chunk_type,
                        **doc.metadata,
                    }
                )

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: _call_with_supported_kwargs(
                    self._client.upsert,
                    collection_name=self.config.collection_name,
                    data=rows,
                ),
            )
            return True
        except Exception as e:
            print(f"Milvus 向量插入失败: {e}")
            return False

    async def delete(self, doc_ids: List[str]) -> bool:
        if not self.is_available():
            return False
        if not doc_ids:
            return True

        expression = "doc_id in [" + ", ".join(json.dumps(doc_id) for doc_id in doc_ids) + "]"

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: _call_with_supported_kwargs(
                    self._client.delete,
                    collection_name=self.config.collection_name,
                    filter=expression,
                    expr=expression,
                ),
            )
            return True
        except Exception as e:
            print(f"Milvus 向量删除失败: {e}")
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


def create_vector_store_adapter(config: VectorStoreConfig) -> VectorStorePort:
    """根据配置创建向量存储适配器。"""
    if config.type == "qdrant":
        return QdrantVectorStoreAdapter(config)
    if config.type == "milvus":
        return MilvusVectorStoreAdapter(config)
    if config.type == "memory":
        return MemoryVectorStoreAdapter(config)
    raise ValueError(f"Unsupported vector store type: {config.type}")
