#!/usr/bin/env python3
"""
向量存储客户端 - Qdrant 实现
支持语义检索和向量相似度计算
"""

from typing import List, Dict, Any, Optional, Tuple
import numpy as np
from dataclasses import dataclass
import hashlib


@dataclass
class VectorDocument:
    """向量文档"""

    id: str
    content: str
    vector: np.ndarray
    doc_id: str
    title: str = ""
    page: int = 0
    section: str = ""
    chunk_type: str = "paragraph"
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class QdrantClient:
    """
    Qdrant 向量数据库客户端

    功能:
    - 文档向量存储
    - 余弦相似度检索
    - 批量操作
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        collection_name: str = "documents",
        vector_size: int = 768,
        timeout: int = 60,
    ):
        self.host = host
        self.port = port
        self.collection_name = collection_name
        self.vector_size = vector_size
        self.timeout = timeout
        self._client = None
        self._connect()

    def _connect(self):
        """连接到 Qdrant"""
        try:
            from qdrant_client import QdrantClient as QC
            from qdrant_client.models import Distance, VectorParams

            self._client = QC(host=self.host, port=self.port, timeout=self.timeout)

            # 检查集合是否存在
            collections = self._client.get_collections().collections
            collection_names = [c.name for c in collections]

            if self.collection_name not in collection_names:
                # 创建集合
                self._client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=self.vector_size, distance=Distance.COSINE
                    ),
                )
                print(f"✓ 创建集合: {self.collection_name}")

            print(f"✓ 连接到 Qdrant: {self.host}:{self.port}")

        except ImportError:
            print("⚠ 未安装 qdrant-client，使用内存存储模式")
            self._client = None
            self._memory_store: Dict[str, VectorDocument] = {}
        except Exception as e:
            print(f"⚠ Qdrant 连接失败: {e}，使用内存存储模式")
            self._client = None
            self._memory_store: Dict[str, VectorDocument] = {}

    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self._client is not None

    def upsert(self, documents: List[VectorDocument]) -> bool:
        """
        插入或更新文档

        Args:
            documents: 文档列表

        Returns:
            是否成功
        """
        if not documents:
            return True

        if self._client is None:
            # 内存模式
            for doc in documents:
                self._memory_store[doc.id] = doc
            return True

        try:
            from qdrant_client.models import PointStruct

            points = []
            for doc in documents:
                point = PointStruct(
                    id=doc.id,
                    vector=doc.vector.tolist(),
                    payload={
                        "content": doc.content,
                        "doc_id": doc.doc_id,
                        "title": doc.title,
                        "page": doc.page,
                        "section": doc.section,
                        "chunk_type": doc.chunk_type,
                        **doc.metadata,
                    },
                )
                points.append(point)

            self._client.upsert(collection_name=self.collection_name, points=points)
            return True

        except Exception as e:
            print(f"插入文档失败: {e}")
            return False

    def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 30,
        score_threshold: float = 0.6,
        filter_conditions: Optional[Dict] = None,
    ) -> List[Tuple[VectorDocument, float]]:
        """
        向量相似度搜索

        使用余弦相似度:
        cos(θ) = (A·B) / (||A|| × ||B||)

        Args:
            query_vector: 查询向量
            top_k: 返回结果数量
            score_threshold: 分数阈值
            filter_conditions: 过滤条件

        Returns:
            (文档, 相似度分数) 列表
        """
        if self._client is None:
            # 内存模式 - 手动计算余弦相似度
            return self._memory_search(query_vector, top_k, score_threshold)

        try:
            results = self._client.search(
                collection_name=self.collection_name,
                query_vector=query_vector.tolist(),
                limit=top_k,
                score_threshold=score_threshold,
                query_filter=filter_conditions,
            )

            documents = []
            for result in results:
                doc = VectorDocument(
                    id=result.id,
                    content=result.payload.get("content", ""),
                    vector=np.array([]),  # 不返回向量以节省带宽
                    doc_id=result.payload.get("doc_id", ""),
                    title=result.payload.get("title", ""),
                    page=result.payload.get("page", 0),
                    section=result.payload.get("section", ""),
                    chunk_type=result.payload.get("chunk_type", "paragraph"),
                    metadata={
                        k: v
                        for k, v in result.payload.items()
                        if k
                        not in [
                            "content",
                            "doc_id",
                            "title",
                            "page",
                            "section",
                            "chunk_type",
                        ]
                    },
                )
                documents.append((doc, result.score))

            return documents

        except Exception as e:
            print(f"搜索失败: {e}")
            return []

    def _memory_search(
        self, query_vector: np.ndarray, top_k: int, threshold: float
    ) -> List[Tuple[VectorDocument, float]]:
        """内存模式搜索 - 手动计算余弦相似度"""
        query_norm = np.linalg.norm(query_vector)

        scores = []
        for doc in self._memory_store.values():
            # 计算余弦相似度
            dot_product = np.dot(query_vector, doc.vector)
            doc_norm = np.linalg.norm(doc.vector)

            if doc_norm == 0 or query_norm == 0:
                similarity = 0.0
            else:
                similarity = dot_product / (query_norm * doc_norm)

            if similarity >= threshold:
                scores.append((doc, similarity))

        # 按分数排序
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def delete(self, doc_ids: List[str]) -> bool:
        """删除文档"""
        if not doc_ids:
            return True

        if self._client is None:
            for doc_id in doc_ids:
                if doc_id in self._memory_store:
                    del self._memory_store[doc_id]
            return True

        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            # 按 doc_id 删除
            self._client.delete(
                collection_name=self.collection_name,
                points_selector=Filter(
                    must=[
                        FieldCondition(key="doc_id", match=MatchValue(value=doc_id))
                        for doc_id in doc_ids
                    ]
                ),
            )
            return True

        except Exception as e:
            print(f"删除失败: {e}")
            return False

    def get_collection_info(self) -> Dict[str, Any]:
        """获取集合信息"""
        if self._client is None:
            return {
                "name": self.collection_name,
                "vectors_count": len(self._memory_store),
                "status": "memory_mode",
            }

        try:
            info = self._client.get_collection(self.collection_name)
            return {
                "name": info.config.params.vectors.size,
                "vectors_count": info.vectors_count,
                "status": info.status,
            }
        except Exception as e:
            return {"error": str(e)}


class EmbeddingService:
    """
    嵌入服务

    支持多种 embedding 模型:
    - BAAI/bge-m3 (推荐)
    - BAAI/bge-large-zh
    - text2vec-large-chinese
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        device: str = "cpu",
        normalize_embeddings: bool = True,
    ):
        self.model_name = model_name
        self.device = device
        self.normalize_embeddings = normalize_embeddings
        self.model = None
        self._load_model()

    def _load_model(self):
        """加载模型"""
        try:
            from sentence_transformers import SentenceTransformer
            import os
            import torch

            # 设置模型缓存路径
            cache_dir = os.environ.get("SENTENCE_TRANSFORMERS_HOME", "/home/l/models")

            self.model = SentenceTransformer(
                self.model_name, device=self.device, cache_folder=cache_dir
            )
            torch.set_num_threads(max(1, os.cpu_count() // 2))
            print(f"✓ Embedding 模型加载完成: {self.model_name} (threads={torch.get_num_threads()})")

        except ImportError:
            print("⚠ 未安装 sentence-transformers，使用模拟嵌入")
            self.model = None
        except Exception as e:
            print(f"⚠ 模型加载失败: {e}")
            self.model = None

    def encode(self, texts: str | List[str]) -> np.ndarray:
        """
        编码文本为向量

        Args:
            texts: 文本或文本列表

        Returns:
            向量或向量数组
        """
        if self.model is None:
            # 模拟嵌入
            if isinstance(texts, str):
                return np.random.randn(768).astype(np.float32)
            else:
                return np.random.randn(len(texts), 768).astype(np.float32)

        try:
            embeddings = self.model.encode(
                texts,
                normalize_embeddings=self.normalize_embeddings,
                show_progress_bar=False,
            )
            return embeddings

        except Exception as e:
            print(f"编码失败: {e}")
            if isinstance(texts, str):
                return np.random.randn(768).astype(np.float32)
            else:
                return np.random.randn(len(texts), 768).astype(np.float32)

    def encode_queries(self, queries: str | List[str]) -> np.ndarray:
        """
        编码查询（添加指令前缀）

        BGE 模型推荐为查询添加指令:
        "Represent this sentence for searching relevant passages:"
        """
        instruction = "Represent this sentence for searching relevant passages:"

        if isinstance(queries, str):
            texts = f"{instruction} {queries}"
        else:
            texts = [f"{instruction} {q}" for q in queries]

        return self.encode(texts)


class VectorStorePipeline:
    """
    向量存储管道

    整合 Embedding 生成和 Qdrant 存储
    """

    def __init__(
        self,
        qdrant_client: Optional[QdrantClient] = None,
        embedding_service: Optional[EmbeddingService] = None,
    ):
        self.qdrant = qdrant_client or QdrantClient()
        self.embedding = embedding_service or EmbeddingService()

    def index_documents(
        self, chunks: List[Dict[str, Any]], batch_size: int = 32
    ) -> bool:
        """
        索引文档片段

        Args:
            chunks: 文档片段列表，每个包含 content, doc_id, page 等
            batch_size: 批处理大小

        Returns:
            是否成功
        """
        total = len(chunks)
        print(f"开始索引 {total} 个文档片段...")

        for i in range(0, total, batch_size):
            batch = chunks[i : i + batch_size]

            # 生成嵌入
            texts = [c["content"] for c in batch]
            embeddings = self.embedding.encode(texts)

            # 构造文档
            documents = []
            for j, chunk in enumerate(batch):
                doc_id = chunk.get("doc_id", "unknown")
                content = chunk["content"]

                # 生成唯一 ID
                unique_id = hashlib.md5(f"{doc_id}:{content[:50]}".encode()).hexdigest()

                doc = VectorDocument(
                    id=unique_id,
                    content=content,
                    vector=embeddings[j],
                    doc_id=doc_id,
                    title=chunk.get("doc_title", ""),
                    page=chunk.get("page", 0),
                    section=chunk.get("section", ""),
                    chunk_type=chunk.get("chunk_type", "paragraph"),
                    metadata=chunk.get("metadata", {}),
                )
                documents.append(doc)

            # 存储
            success = self.qdrant.upsert(documents)
            if success:
                print(f"  索引进度: {min(i + batch_size, total)}/{total}")
            else:
                print(f"  ⚠ 批次 {i // batch_size} 索引失败")

        print(f"✓ 索引完成")
        return True

    def search(
        self, query: str, top_k: int = 30, score_threshold: float = 0.6
    ) -> List[Tuple[VectorDocument, float]]:
        """
        语义搜索

        Args:
            query: 查询文本
            top_k: 返回结果数量
            score_threshold: 分数阈值

        Returns:
            (文档, 相似度分数) 列表
        """
        # 生成查询向量
        query_embedding = self.embedding.encode_queries(query)

        # 搜索
        results = self.qdrant.search(
            query_embedding, top_k=top_k, score_threshold=score_threshold
        )

        return results


if __name__ == "__main__":
    # 测试代码
    print("=" * 60)
    print("向量存储测试")
    print("=" * 60)

    # 创建服务
    embedding = EmbeddingService()
    qdrant = QdrantClient()
    pipeline = VectorStorePipeline(qdrant, embedding)

    # 测试数据
    test_chunks = [
        {
            "content": "深圳市建设工程计价费率标准规定了企业管理费的计算方法",
            "doc_id": "sz_flbz_2023",
            "doc_title": "深圳市建设工程计价费率标准",
            "page": 1,
            "section": "总则",
            "chunk_type": "paragraph",
        },
        {
            "content": "企业管理费包括管理人员工资、办公费、差旅交通费等",
            "doc_id": "sz_flbz_2023",
            "doc_title": "深圳市建设工程计价费率标准",
            "page": 2,
            "section": "费用组成",
            "chunk_type": "paragraph",
        },
        {
            "content": "分部分项工程费由人工费、材料费、机械费组成",
            "doc_id": "sz_flbz_2023",
            "doc_title": "深圳市建设工程计价费率标准",
            "page": 3,
            "section": "工程费用",
            "chunk_type": "paragraph",
        },
    ]

    # 索引
    print("\n1. 索引测试文档...")
    pipeline.index_documents(test_chunks)

    # 搜索
    print("\n2. 测试搜索...")
    query = "企业管理费怎么计算"
    results = pipeline.search(query, top_k=5)

    print(f"\n查询: {query}")
    print(f"结果数: {len(results)}")

    for doc, score in results:
        print(f"\n  分数: {score:.4f}")
        print(f"  内容: {doc.content[:50]}...")
        print(f"  来源: {doc.title} 第{doc.page}页")
