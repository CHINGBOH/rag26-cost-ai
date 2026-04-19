#!/usr/bin/env python3
"""
召回精排架构核心模块
实现多路召回 + Cross-Encoder 精排 + 分数融合
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import numpy as np
from abc import ABC, abstractmethod
import hashlib
import time


class QueryType(Enum):
    """查询类型"""

    SEMANTIC = "semantic"  # 语义查询
    KEYWORD = "keyword"  # 关键词查询
    ENTITY = "entity"  # 实体查询
    HYBRID = "hybrid"  # 混合查询


@dataclass
class Document:
    """文档候选"""

    id: str
    content: str
    doc_id: str
    title: str = ""
    page: int = 0
    section: str = ""
    chunk_type: str = "paragraph"

    # 召回分数
    vector_score: float = 0.0  # 向量相似度 [-1, 1]
    bm25_score: float = 0.0  # BM25 分数
    graph_score: float = 0.0  # 图谱关联度

    # 精排分数
    rerank_score: float = 0.0  # Cross-Encoder 分数

    # 融合分数
    final_score: float = 0.0  # 最终融合分数

    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    publish_date: Optional[str] = None

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, other):
        if isinstance(other, Document):
            return self.id == other.id
        return False


@dataclass
class RetrievalResult:
    """检索结果"""

    query: str
    query_type: QueryType
    documents: List[Document]
    total_candidates: int
    retrieval_time_ms: float

    # 各召回源统计
    vector_count: int = 0
    keyword_count: int = 0
    graph_count: int = 0


class BaseRetriever(ABC):
    """召回器基类"""

    @abstractmethod
    def retrieve(
        self, query: str, query_embedding: Optional[np.ndarray], top_k: int
    ) -> List[Document]:
        """召回文档"""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查是否可用"""
        pass


class VectorRetriever(BaseRetriever):
    """向量召回器 - 基于余弦相似度"""

    def __init__(self, client=None, collection_name: str = "documents"):
        self.client = client
        self.collection_name = collection_name
        self._available = client is not None

    def is_available(self) -> bool:
        return self._available

    def retrieve(
        self,
        query: str,
        query_embedding: Optional[np.ndarray],
        top_k: int = 30,
        score_threshold: float = 0.6,
    ) -> List[Document]:
        """
        向量召回 - 使用余弦相似度

        原理: cos(θ) = (A·B) / (||A|| × ||B||)
        范围: [-1, 1]，通常归一化到 [0, 1]
        """
        if not self.is_available() or query_embedding is None:
            return []

        try:
            # 这里接入实际的 Qdrant 查询
            # 模拟召回结果
            results = self._mock_search(query_embedding, top_k, score_threshold)
            return results
        except Exception as e:
            print(f"向量召回失败: {e}")
            return []

    def _mock_search(
        self, query_embedding: np.ndarray, top_k: int, threshold: float
    ) -> List[Document]:
        """向量搜索"""
        if not self.client:
            return []

        try:
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding.tolist(),
                limit=top_k,
                score_threshold=threshold
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
                    vector_score=result.score,
                    metadata={
                        k: v
                        for k, v in result.payload.items()
                        if k not in ["content", "doc_id", "title", "page", "section", "chunk_type"]
                    },
                )
                documents.append(doc)

            return documents
        except Exception as e:
            print(f"向量搜索失败: {e}")
            return []


class KeywordRetriever(BaseRetriever):
    """关键词召回器 - 基于 BM25"""

    def __init__(self, client=None, index_name: str = "documents"):
        self.client = client
        self.index_name = index_name
        self._available = client is not None

    def is_available(self) -> bool:
        return self._available

    def retrieve(
        self,
        query: str,
        query_embedding: Optional[np.ndarray] = None,
        top_k: int = 20,
        min_score: float = 1.0,
    ) -> List[Document]:
        """
        关键词召回 - 使用 BM25

        BM25 公式:
        score(D,Q) = Σ IDF(q_i) × [f(q_i,D) × (k1+1)] / [f(q_i,D) + k1 × (1-b+b×|D|/avgdl)]
        """
        if not self.is_available():
            return []

        try:
            results = self._mock_search(query, top_k, min_score)
            return results
        except Exception as e:
            print(f"关键词召回失败: {e}")
            return []

    def _mock_search(self, query: str, top_k: int, min_score: float) -> List[Document]:
        """关键词搜索"""
        if not self.client:
            return []

        try:
            results = self.client.search(
                index=self.index_name,
                body={
                    "query": {"match": {"content": query}},
                    "size": top_k,
                    "min_score": min_score
                }
            )

            documents = []
            for hit in results["hits"]["hits"]:
                source = hit["_source"]
                doc = Document(
                    id=hit["_id"],
                    content=source.get("content", ""),
                    doc_id=source.get("doc_id", ""),
                    title=source.get("title", ""),
                    page=source.get("page", 0),
                    section=source.get("section", ""),
                    chunk_type=source.get("chunk_type", "paragraph"),
                    bm25_score=hit["_score"],
                    metadata=source,
                )
                documents.append(doc)

            return documents
        except Exception as e:
            print(f"关键词搜索失败: {e}")
            return []


class GraphRetriever(BaseRetriever):
    """图谱召回器 - 基于实体扩展"""

    def __init__(self, client=None):
        self.client = client
        self._available = client is not None

    def is_available(self) -> bool:
        return self._available

    def retrieve(
        self,
        query: str,
        query_embedding: Optional[np.ndarray] = None,
        top_k: int = 10,
        entities: Optional[List[str]] = None,
        depth: int = 2,
    ) -> List[Document]:
        """
        图谱召回 - 基于实体关系扩展

        原理: 从查询中提取实体，在图谱中扩展相关实体，
              找到与这些实体相关的文档
        """
        if not self.is_available():
            return []

        try:
            if entities is None:
                entities = self._extract_entities(query)

            results = self._expand_entities(entities, depth, top_k)
            return results
        except Exception as e:
            print(f"图谱召回失败: {e}")
            return []

    def _extract_entities(self, query: str) -> List[str]:
        """从查询中提取实体（简化版）"""
        # 实际实现应使用 NER 模型
        return []

    def _expand_entities(
        self, entities: List[str], depth: int, top_k: int
    ) -> List[Document]:
        """实体扩展（实际使用时替换为真实 Neo4j 调用）"""
        # 实际实现:
        # query = """
        # MATCH (e:Entity)-[:RELATED*1..{depth}]-(related:Entity)
        # WHERE e.name IN $entities
        # MATCH (related)-[:MENTIONED_IN]->(d:Document)
        # RETURN d, count(*) as relevance
        # ORDER BY relevance DESC
        # LIMIT $top_k
        # """
        return []


class Reranker:
    """
    精排器 - 使用 Cross-Encoder

    Cross-Encoder vs Bi-Encoder:
    - Bi-Encoder: 分别编码 query 和 doc，用余弦相似度比较
    - Cross-Encoder: 拼接 query+doc 一起编码，通过 Transformer 交互

    Cross-Encoder 优势:
    - 能捕捉 query 和 doc 之间的细粒度交互
    - 精度更高，但计算成本也更高
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-large",
        device: str = "cpu",
        batch_size: int = 8,
        max_length: int = 512,
    ):
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self.max_length = max_length
        self.model = None
        self.tokenizer = None
        self._load_model()

    def _load_model(self):
        """加载模型"""
        try:
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            import torch
            import os

            # 设置模型缓存路径
            cache_dir = os.environ.get("HF_HOME", "/home/l/models")

            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_name, cache_dir=cache_dir
            )
            self.model = AutoModelForSequenceClassification.from_pretrained(
                self.model_name, cache_dir=cache_dir
            )
            self.model.to(self.device)
            self.model.eval()
            print(f"✓ 精排模型加载完成: {self.model_name}")
        except Exception as e:
            print(f"⚠ 精排模型加载失败: {e}")
            self.model = None

    def rerank(self, query: str, candidates: List[Document]) -> List[Document]:
        """
        精排候选文档

        Args:
            query: 查询文本
            candidates: 召回的候选文档列表

        Returns:
            按精排分数排序的文档列表
        """
        if not candidates:
            return []

        if self.model is None:
            # 模型未加载，返回原始顺序
            return candidates

        try:
            import torch

            # 构造 (query, doc) 对
            pairs = [[query, doc.content] for doc in candidates]

            # 批量推理
            all_scores = []
            for i in range(0, len(pairs), self.batch_size):
                batch = pairs[i : i + self.batch_size]

                inputs = self.tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    return_tensors="pt",
                    max_length=self.max_length,
                )
                inputs = {k: v.to(self.device) for k, v in inputs.items()}

                with torch.no_grad():
                    outputs = self.model(**inputs)
                    scores = outputs.logits.squeeze(-1)
                    all_scores.extend(scores.cpu().tolist())

            # 设置精排分数
            for doc, score in zip(candidates, all_scores):
                doc.rerank_score = score

            # 按精排分数排序
            return sorted(candidates, key=lambda x: x.rerank_score, reverse=True)

        except Exception as e:
            print(f"精排失败: {e}")
            return candidates


class FusionScorer:
    """分数融合器"""

    def __init__(
        self,
        rerank_weight: float = 0.4,
        vector_weight: float = 0.3,
        keyword_weight: float = 0.2,
        graph_weight: float = 0.05,
        time_weight: float = 0.05,
    ):
        self.weights = {
            "rerank": rerank_weight,
            "vector": vector_weight,
            "keyword": keyword_weight,
            "graph": graph_weight,
            "time": time_weight,
        }

    def sigmoid(self, x: float) -> float:
        """Sigmoid 函数，将分数映射到 [0, 1]"""
        return 1 / (1 + np.exp(-x))

    def time_decay(self, date_str: Optional[str], half_life_days: int = 365) -> float:
        """
        时间衰减函数

        越新的文档分数越高，使用指数衰减
        score = exp(-λ × t)，其中 λ = ln(2) / half_life
        """
        if date_str is None:
            return 0.5  # 默认中等分数

        try:
            from datetime import datetime

            pub_date = datetime.strptime(date_str, "%Y-%m-%d")
            days_old = (datetime.now() - pub_date).days
            decay = np.exp(-np.log(2) * days_old / half_life_days)
            return decay
        except Exception:
            return 0.5

    def compute_final_score(self, doc: Document) -> float:
        """
        计算最终融合分数

        公式:
        final_score = 0.4 × rerank_score + 0.3 × vector_score +
                      0.2 × keyword_score + 0.05 × graph_score + 0.05 × time_score
        """
        # 1. 精排分数 (Cross-Encoder 输出，用 sigmoid 映射到 [0,1])
        rerank_score = self.sigmoid(doc.rerank_score)

        # 2. 向量分数 (余弦相似度 [-1,1] -> [0,1])
        vector_score = (doc.vector_score + 1) / 2

        # 3. 关键词分数 (BM25，假设已归一化)
        keyword_score = min(doc.bm25_score / 10, 1.0)  # 简单归一化

        # 4. 图谱分数
        graph_score = doc.graph_score if doc.graph_score > 0 else 0.5

        # 5. 时间分数
        time_score = self.time_decay(doc.publish_date)

        # 加权融合
        final_score = (
            self.weights["rerank"] * rerank_score
            + self.weights["vector"] * vector_score
            + self.weights["keyword"] * keyword_score
            + self.weights["graph"] * graph_score
            + self.weights["time"] * time_score
        )

        doc.final_score = final_score
        return final_score

    def fuse(self, documents: List[Document]) -> List[Document]:
        """对文档列表进行分数融合并排序"""
        for doc in documents:
            self.compute_final_score(doc)

        return sorted(documents, key=lambda x: x.final_score, reverse=True)


class QueryClassifier:
    """查询分类器"""

    def classify(self, query: str) -> QueryType:
        """
        分类查询类型

        规则:
        - 包含特定实体名称 -> ENTITY
        - 明显是关键词组合 -> KEYWORD
        - 自然语言问题 -> SEMANTIC
        - 其他 -> HYBRID
        """
        # 实体查询特征
        entity_patterns = [
            r"[\u4e00-\u9fa5]{2,10}(?:公司|集团|企业|单位|部门)",
            r"[\u4e00-\u9fa5]{2,8}(?:标准|规范|规定|办法)",
            r"HJ\d+",  # 标准编号
        ]

        for pattern in entity_patterns:
            if re.search(pattern, query):
                return QueryType.ENTITY

        # 关键词查询特征（短查询、多个关键词）
        if len(query) < 15 and (" " in query or "、" in query):
            return QueryType.KEYWORD

        # 语义查询特征（自然语言问题）
        semantic_patterns = [
            r"^(什么是|如何|怎么|为什么|请问)",
            r"(介绍|说明|解释|描述)",
        ]

        for pattern in semantic_patterns:
            if re.search(pattern, query):
                return QueryType.SEMANTIC

        return QueryType.HYBRID


import re


class MultiStageRetriever:
    """
    多阶段召回器

    完整流程:
    1. 查询理解 (分类、嵌入)
    2. 多路召回 (向量、关键词、图谱)
    3. 候选池合并 (去重、粗排)
    4. 精排 (Cross-Encoder)
    5. 分数融合 (加权排序)
    6. 上下文增强 (添加前后段落)
    """

    def __init__(
        self,
        vector_retriever: Optional[VectorRetriever] = None,
        keyword_retriever: Optional[KeywordRetriever] = None,
        graph_retriever: Optional[GraphRetriever] = None,
        reranker: Optional[Reranker] = None,
        fusion_scorer: Optional[FusionScorer] = None,
        embedding_model: Any = None,
        vector_store: Any = None,
        keyword_store: Any = None,
        graph_store: Any = None,
    ):
        self.vector_retriever = vector_retriever or VectorRetriever()
        self.keyword_retriever = keyword_retriever or KeywordRetriever()
        self.graph_retriever = graph_retriever or GraphRetriever()
        self.reranker = reranker or Reranker()
        self.fusion_scorer = fusion_scorer or FusionScorer()
        self.query_classifier = QueryClassifier()
        self.embedding_model = embedding_model
        self.vector_store = vector_store
        self.keyword_store = keyword_store
        self.graph_store = graph_store

    def embed(self, text: str) -> np.ndarray:
        """生成文本嵌入"""
        if self.embedding_model:
            return self.embedding_model.encode(text)
        # 模拟嵌入
        return np.random.randn(768).astype(np.float32)

    def deduplicate(self, candidates: List[Document]) -> List[Document]:
        """基于文档 ID 去重"""
        seen = set()
        unique = []
        for doc in candidates:
            if doc.id not in seen:
                seen.add(doc.id)
                unique.append(doc)
        return unique

    def coarse_rank(
        self, candidates: List[Document], query_embedding: np.ndarray
    ) -> List[Document]:
        """
        粗排 - 轻量级排序，减少精排压力

        策略: 优先使用已有分数，简单加权
        """
        for doc in candidates:
            # 简单加权粗排分数
            coarse_score = (
                doc.vector_score * 0.5
                + min(doc.bm25_score / 10, 1.0) * 0.3
                + doc.graph_score * 0.2
            )
            doc.metadata["coarse_score"] = coarse_score

        return sorted(
            candidates, key=lambda x: x.metadata.get("coarse_score", 0), reverse=True
        )

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        enable_rerank: bool = True,
        enable_fusion: bool = True,
    ) -> RetrievalResult:
        """
        执行多阶段检索

        Args:
            query: 查询文本
            top_k: 返回结果数量
            enable_rerank: 是否启用精排
            enable_fusion: 是否启用分数融合

        Returns:
            检索结果
        """
        start_time = time.time()

        # 1. 查询理解
        query_type = self.query_classifier.classify(query)
        query_embedding = self.embed(query)

        print(f"查询: {query}")
        print(f"查询类型: {query_type.value}")

        # 2. 多路召回
        candidates = []
        vector_results = []
        keyword_results = []
        graph_results = []

        # 向量召回 - top-30 (使用内存存储)
        if hasattr(self, "vector_store") and self.vector_store:
            # 使用内存模式搜索
            from retrieval.vector_store import VectorDocument

            results = self.vector_store._memory_search(
                query_embedding, top_k=30, threshold=0.0
            )
            for vec_doc, score in results:
                doc = Document(
                    id=vec_doc.id,
                    content=vec_doc.content,
                    doc_id=vec_doc.doc_id,
                    title=vec_doc.title,
                    page=vec_doc.page,
                    section=vec_doc.section,
                    chunk_type=vec_doc.chunk_type,
                    vector_score=score,
                    metadata=vec_doc.metadata,
                )
                vector_results.append(doc)
            candidates.extend(vector_results)
            print(f"向量召回: {len(vector_results)} 个")

        # 关键词召回 - top-20 (使用内存存储)
        if hasattr(self, "keyword_store") and self.keyword_store:
            # 使用内存模式搜索
            results = self.keyword_store._memory_search(query, top_k=20, min_score=0.0)
            keyword_results = results
            candidates.extend(keyword_results)
            print(f"关键词召回: {len(keyword_results)} 个")

        # 图谱召回 - top-10（仅实体查询）
        if self.graph_retriever.is_available() and query_type == QueryType.ENTITY:
            entities = self._extract_entities(query)
            graph_results = self.graph_retriever.retrieve(
                query, entities=entities, depth=2, top_k=10
            )
            for doc in graph_results:
                doc.graph_score = doc.metadata.get("relevance", 0.5)
            candidates.extend(graph_results)
            print(f"图谱召回: {len(graph_results)} 个")

        total_candidates = len(candidates)
        print(f"召回候选总数: {total_candidates}")

        if not candidates:
            return RetrievalResult(
                query=query,
                query_type=query_type,
                documents=[],
                total_candidates=0,
                retrieval_time_ms=(time.time() - start_time) * 1000,
            )

        # 3. 去重
        candidates = self.deduplicate(candidates)
        print(f"去重后候选: {len(candidates)}")

        # 4. 粗排（取 top_k * 2 给精排）
        candidates = self.coarse_rank(candidates, query_embedding)
        rerank_candidates = candidates[: top_k * 2]

        # 5. 精排
        if enable_rerank and self.reranker.model is not None:
            print(f"精排候选: {len(rerank_candidates)}")
            reranked = self.reranker.rerank(query, rerank_candidates)
        else:
            reranked = rerank_candidates

        # 6. 分数融合
        if enable_fusion:
            final_results = self.fusion_scorer.fuse(reranked)
        else:
            final_results = reranked

        # 7. 取 top_k
        final_results = final_results[:top_k]

        retrieval_time = (time.time() - start_time) * 1000

        return RetrievalResult(
            query=query,
            query_type=query_type,
            documents=final_results,
            total_candidates=total_candidates,
            retrieval_time_ms=retrieval_time,
            vector_count=len(vector_results) if "vector_results" in locals() else 0,
            keyword_count=len(keyword_results) if "keyword_results" in locals() else 0,
            graph_count=len(graph_results) if "graph_results" in locals() else 0,
        )

    def _extract_entities(self, query: str) -> List[str]:
        """从查询中提取实体"""
        # 简化实现，实际应使用 NER 模型
        patterns = [
            r"[\u4e00-\u9fa5]{2,10}(?:公司|集团|企业|单位|部门)",
            r"[\u4e00-\u9fa5]{2,8}(?:标准|规范|规定|办法|指南)",
            r"HJ\d+(?:\.\d+)?",
            r"GB[\/T]?\d+(?:\.\d+)?",
        ]

        entities = []
        for pattern in patterns:
            matches = re.findall(pattern, query)
            entities.extend(matches)

        return entities


if __name__ == "__main__":
    # 测试代码
    print("=" * 60)
    print("召回精排架构测试")
    print("=" * 60)

    # 创建召回器（不连接实际数据库）
    retriever = MultiStageRetriever()

    # 测试查询
    test_queries = [
        "深圳市建设工程计价费率标准",
        "企业管理费怎么计算",
        "HJ 2023 标准规定",
    ]

    for query in test_queries:
        print(f"\n查询: {query}")
        result = retriever.retrieve(query, top_k=5)
        print(f"查询类型: {result.query_type.value}")
        print(f"召回候选: {result.total_candidates}")
        print(f"检索耗时: {result.retrieval_time_ms:.2f}ms")
        print("-" * 40)
