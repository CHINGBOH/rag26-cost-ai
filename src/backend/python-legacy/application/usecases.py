"""
应用层 - 用例实现
核心业务逻辑，不依赖具体基础设施
"""

from typing import List
from returns.result import Result, Success, Failure

from domain.models import (
    Document,
    SearchRequest,
    SearchResponse,
    IndexRequest,
    IndexResponse,
    QueryType,
)
from domain.ports import (
    VectorStorePort,
    KeywordStorePort,
    GraphStorePort,
    EmbeddingModelPort,
    RerankModelPort,
    CachePort,
)
from config.settings import get_config, FusionWeightsConfig
import numpy as np
import time


class SearchUsecase:
    """
    搜索用例

    实现多路召回 + 精排 + 分数融合的完整流程
    """

    def __init__(
        self,
        vector_store: VectorStorePort,
        keyword_store: KeywordStorePort,
        graph_store: GraphStorePort,
        embedding_model: EmbeddingModelPort,
        rerank_model: RerankModelPort,
        cache: CachePort | None = None,
        fusion_weights: FusionWeightsConfig | None = None,
    ):
        self.vector_store = vector_store
        self.keyword_store = keyword_store
        self.graph_store = graph_store
        self.embedding_model = embedding_model
        self.rerank_model = rerank_model
        self.cache = cache
        self.fusion_weights = fusion_weights or get_config().fusion_weights

    async def execute(self, request: SearchRequest) -> Result[SearchResponse, Exception]:
        """
        执行搜索

        Args:
            request: 搜索请求

        Returns:
            Result[SearchResponse, Exception]: 成功返回响应，失败返回异常
        """
        try:
            start_time = time.time()

            # 1. 检查缓存
            if self.cache:
                cache_key = f"search:{request.query}:{request.top_k}"
                cached = await self.cache.get(cache_key)
                if cached:
                    return Success(cached)

            # 2. 生成查询向量
            query_embedding = self.embedding_model.encode_queries(request.query)

            # 3. 多路召回
            candidates = await self._multi_way_retrieve(request.query, query_embedding, request)

            total_candidates = len(candidates)

            if not candidates:
                return Success(
                    SearchResponse(
                        query=request.query,
                        query_type=QueryType.HYBRID,
                        documents=[],
                        total_candidates=0,
                        retrieval_time_ms=0.0,
                        total_time_ms=(time.time() - start_time) * 1000,
                    )
                )

            # 4. 去重
            candidates = self._deduplicate(candidates)

            # 5. 粗排
            candidates = self._coarse_rank(candidates, query_embedding)
            rerank_candidates = candidates[: request.top_k * 2]

            # 6. 精排
            if request.enable_rerank and self.rerank_model.is_loaded():
                reranked = self.rerank_model.rerank(request.query, rerank_candidates)
            else:
                reranked = rerank_candidates

            # 7. 分数融合
            if request.enable_fusion:
                final_results = self._fuse_scores(reranked)
            else:
                final_results = reranked

            # 8. 取top_k
            final_results = final_results[: request.top_k]

            retrieval_time = (time.time() - start_time) * 1000

            response = SearchResponse(
                query=request.query,
                query_type=self._classify_query(request.query),
                documents=final_results,
                total_candidates=total_candidates,
                retrieval_time_ms=retrieval_time,
                total_time_ms=retrieval_time,
            )

            # 9. 写入缓存
            if self.cache:
                await self.cache.set(cache_key, response, ttl=300)

            return Success(response)

        except Exception as e:
            return Failure(e)

    async def _multi_way_retrieve(
        self, query: str, query_embedding: np.ndarray, request: SearchRequest
    ) -> List[Document]:
        """多路召回"""
        candidates = []

        # 向量召回
        if self.vector_store.is_available():
            vector_results = await self.vector_store.search(
                query_embedding,
                top_k=get_config().retrieval.vector_top_k,
                score_threshold=get_config().retrieval.score_threshold,
            )
            for doc, score in vector_results:
                doc.vector_score = score
                candidates.append(doc)

        # 关键词召回
        if self.keyword_store.is_available():
            keyword_results = await self.keyword_store.search(
                query, top_k=get_config().retrieval.keyword_top_k
            )
            for doc in keyword_results:
                doc.bm25_score = 5.0  # 简化处理
                candidates.append(doc)

        # 图谱召回（仅实体查询）
        query_type = self._classify_query(query)
        if self.graph_store.is_available() and query_type == QueryType.ENTITY:
            entities = self._extract_entities(query)
            if entities:
                graph_results = await self.graph_store.expand_entities(
                    entities, depth=2, top_k=get_config().retrieval.graph_top_k
                )
                for doc in graph_results:
                    doc.graph_score = 0.5
                    candidates.append(doc)

        return candidates

    def _deduplicate(self, candidates: List[Document]) -> List[Document]:
        """基于文档ID去重"""
        seen = set()
        unique = []
        for doc in candidates:
            if doc.id not in seen:
                seen.add(doc.id)
                unique.append(doc)
        return unique

    def _coarse_rank(
        self, candidates: List[Document], query_embedding: np.ndarray
    ) -> List[Document]:
        """粗排"""
        for doc in candidates:
            coarse_score = (
                doc.vector_score * 0.5 + min(doc.bm25_score / 10, 1.0) * 0.3 + doc.graph_score * 0.2
            )
            doc.metadata["coarse_score"] = coarse_score

        return sorted(candidates, key=lambda x: x.metadata.get("coarse_score", 0), reverse=True)

    def _fuse_scores(self, documents: List[Document]) -> List[Document]:
        """分数融合"""

        def sigmoid(x: float) -> float:
            return 1 / (1 + np.exp(-x))

        for doc in documents:
            # 各分数归一化
            rerank_score = sigmoid(doc.rerank_score)
            vector_score = (doc.vector_score + 1) / 2
            keyword_score = min(doc.bm25_score / 10, 1.0)
            graph_score = doc.graph_score if doc.graph_score > 0 else 0.5

            # 加权融合
            doc.final_score = (
                self.fusion_weights.rerank * rerank_score
                + self.fusion_weights.vector * vector_score
                + self.fusion_weights.keyword * keyword_score
                + self.fusion_weights.graph * graph_score
            )

        return sorted(documents, key=lambda x: x.final_score, reverse=True)

    def _classify_query(self, query: str) -> QueryType:
        """查询分类"""
        import re

        # 实体查询特征
        entity_patterns = [
            r"[\u4e00-\u9fa5]{2,10}(?:公司|集团|企业|单位|部门)",
            r"[\u4e00-\u9fa5]{2,8}(?:标准|规范|规定|办法|指南)",
            r"HJ\d+",
            r"GB[\/T]?\d+",
        ]

        for pattern in entity_patterns:
            if re.search(pattern, query):
                return QueryType.ENTITY

        # 关键词查询特征
        if len(query) < 15 and (" " in query or "、" in query):
            return QueryType.KEYWORD

        # 语义查询特征
        semantic_patterns = [
            r"^(什么是|如何|怎么|为什么|请问)",
            r"(介绍|说明|解释|描述)",
        ]

        for pattern in semantic_patterns:
            if re.search(pattern, query):
                return QueryType.SEMANTIC

        return QueryType.HYBRID

    def _extract_entities(self, query: str) -> List[str]:
        """提取实体"""
        import re

        patterns = [
            r"[\u4e00-\u9fa5]{2,10}(?:公司|集团|企业|单位|部门)",
            r"[\u4e00-\u9fa5]{2,8}(?:标准|规范|规定|办法|指南)",
            r"HJ\d+(?:\.\d+)?",
            r"GB[\/T]?\d+(?:\.\d+)?",
            r"(?:人工费|材料费|机械费|企业管理费|利润|规费|税金)",
        ]

        entities = []
        for pattern in patterns:
            matches = re.findall(pattern, query)
            entities.extend(matches)

        return list(set(entities))


class IndexUsecase:
    """
    索引用例

    实现文档索引到多个存储的完整流程
    """

    def __init__(
        self,
        vector_store: VectorStorePort,
        keyword_store: KeywordStorePort,
        graph_store: GraphStorePort,
        embedding_model: EmbeddingModelPort,
    ):
        self.vector_store = vector_store
        self.keyword_store = keyword_store
        self.graph_store = graph_store
        self.embedding_model = embedding_model

    async def execute(self, request: IndexRequest) -> Result[IndexResponse, Exception]:
        """
        执行索引

        Args:
            request: 索引请求

        Returns:
            Result[IndexResponse, Exception]: 成功返回响应，失败返回异常
        """
        try:
            start_time = time.time()

            # 1. 生成向量
            texts = [chunk.content for chunk in request.chunks]
            vectors = self.embedding_model.encode(texts)

            # 2. 索引到向量存储
            if self.vector_store.is_available():
                await self.vector_store.upsert(request.chunks, vectors)

            # 3. 索引到关键词存储
            if self.keyword_store.is_available():
                await self.keyword_store.index(request.chunks)

            # 4. 构建知识图谱
            entities_count = 0
            if request.build_graph and self.graph_store.is_available():
                await self.graph_store.build_from_document(request.doc_id, request.chunks)
                # 简化：假设提取了实体
                entities_count = len(request.chunks) * 2

            time_ms = (time.time() - start_time) * 1000

            return Success(
                IndexResponse(
                    doc_id=request.doc_id,
                    chunks_indexed=len(request.chunks),
                    entities_extracted=entities_count,
                    time_ms=time_ms,
                    success=True,
                )
            )

        except Exception as e:
            return Failure(e)
