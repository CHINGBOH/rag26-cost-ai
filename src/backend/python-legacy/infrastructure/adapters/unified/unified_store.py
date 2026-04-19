"""
统一存储层 - 实现四库联动操作
"""

import uuid
import json
import logging
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime

# 类型导入
import sys
import os

# 添加项目根目录到路径，支持相对导入
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_dir))))
)  # ../../../../.. -> rag-dashboard
sys.path.insert(0, project_root)

from domain_models.document_models import Document, DocumentChunk, DocumentMetadata, ChunkType
from domain_models.search_models import SearchQuery, SearchResultItem, SearchContext
from domain_models.retrieval_models import RetrievalConfig

# 存储客户端
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from elasticsearch import Elasticsearch
from neo4j import GraphDatabase
from neo4j import Auth
import redis
import httpx

from .store_config import StoreConfig

logger = logging.getLogger(__name__)


class UnifiedStore:
    """统一存储层 - 管理四库联动"""

    def __init__(self, config: Optional[StoreConfig] = None):
        self.config = config or StoreConfig.from_env()

        # 初始化连接
        self._init_vector_store()
        self._init_keyword_store()
        self._init_graph_store()
        self._init_cache()

        logger.info("UnifiedStore initialized successfully")

    def _init_vector_store(self):
        """初始化 Qdrant 向量库"""
        try:
            self.vector_client = QdrantClient(
                host=self.config.vector.host,
                port=self.config.vector.port,
                timeout=self.config.vector.timeout,
                limits=httpx.Limits(max_connections=self.config.vector.pool_size)
                if self.config.vector.pool_size
                else None,
            )
            # 确保集合存在
            self._ensure_vector_collection()
            logger.info(
                f"✅ Vector store connected: {self.config.vector.host}:{self.config.vector.port}"
            )
        except Exception as e:
            logger.error(f"❌ Vector store connection failed: {e}")
            self.vector_client = None

    def _init_keyword_store(self):
        """初始化 Elasticsearch 关键词库"""
        try:
            es_config = {
                "hosts": self.config.keyword.hosts,
                "retry_on_timeout": True,
                "max_retries": 3,
            }
            if self.config.keyword.username and self.config.keyword.password:
                es_config["basic_auth"] = (self.config.keyword.username, self.config.keyword.password)
            self.keyword_client = Elasticsearch(**es_config)
            # 确保索引存在
            self._ensure_keyword_index()
            logger.info(f"✅ Keyword store connected: {self.config.keyword.hosts}")
        except Exception as e:
            logger.error(f"❌ Keyword store connection failed: {e}")
            self.keyword_client = None

    def _init_graph_store(self):
        """初始化 Neo4j 图库"""
        try:
            self.graph_driver = GraphDatabase.driver(
                self.config.graph.uri,
                auth=(self.config.graph.username, self.config.graph.password),
                max_connection_pool_size=self.config.graph.max_connection_pool_size,
                connection_acquisition_timeout=self.config.graph.connection_acquisition_timeout,
            )
            # 测试连接
            with self.graph_driver.session() as session:
                session.run("RETURN 1")
            logger.info(f"✅ Graph store connected: {self.config.graph.uri}")
        except Exception as e:
            logger.error(f"❌ Graph store connection failed: {e}")
            self.graph_driver = None

    def _init_cache(self):
        """初始化 Redis 缓存"""
        try:
            self.cache_client = redis.Redis(
                host=self.config.cache.host,
                port=self.config.cache.port,
                db=self.config.cache.db,
                decode_responses=True,
                max_connections=self.config.cache.max_connections,
                socket_timeout=self.config.cache.socket_timeout,
                retry_on_timeout=True,
            )
            self.cache_client.ping()
            logger.info(f"✅ Cache connected: {self.config.cache.host}:{self.config.cache.port}")
        except Exception as e:
            logger.error(f"❌ Cache connection failed: {e}")
            self.cache_client = None

    def _ensure_vector_collection(self):
        """确保向量集合存在"""
        try:
            collections = self.vector_client.get_collections()
            collection_names = [c.name for c in collections.collections]

            if self.config.vector.collection_name not in collection_names:
                self.vector_client.create_collection(
                    collection_name=self.config.vector.collection_name,
                    vectors_config=VectorParams(
                        size=self.config.vector.vector_size, distance=Distance.COSINE
                    ),
                )
                logger.info(f"Created vector collection: {self.config.vector.collection_name}")
        except Exception as e:
            logger.warning(f"Vector collection check failed: {e}")

    def _ensure_keyword_index(self):
        """确保关键词索引存在"""
        try:
            if not self.keyword_client.indices.exists(index=self.config.keyword.index_name):
                self.keyword_client.indices.create(
                    index=self.config.keyword.index_name,
                    body={
                        "mappings": {
                            "properties": {
                                "content": {
                                    "type": "text",
                                    "analyzer": "ik_max_word",
                                    "search_analyzer": "ik_smart",
                                },
                                "keywords": {"type": "keyword"},
                                "doc_id": {"type": "keyword"},
                                "chunk_id": {"type": "keyword"},
                                "timestamp": {"type": "date"},
                            }
                        }
                    },
                )
                logger.info(f"Created keyword index: {self.config.keyword.index_name}")
        except Exception as e:
            logger.warning(f"Keyword index check failed: {e}")

    # ========== 统一写入接口 ==========

    def index_document(self, document: Document) -> Dict[str, Any]:
        """将文档索引到四库"""
        results = {"doc_id": document.metadata.doc_id, "chunks_indexed": 0, "errors": []}

        # 1. 写入向量库
        if self.vector_client:
            try:
                vector_count = self._index_to_vector(document)
                results["vector_indexed"] = vector_count
            except Exception as e:
                results["errors"].append(f"Vector: {e}")

        # 2. 写入关键词库
        if self.keyword_client:
            try:
                keyword_count = self._index_to_keyword(document)
                results["keyword_indexed"] = keyword_count
            except Exception as e:
                results["errors"].append(f"Keyword: {e}")

        # 3. 写入图库
        if self.graph_driver:
            try:
                graph_count = self._index_to_graph(document)
                results["graph_indexed"] = graph_count
            except Exception as e:
                results["errors"].append(f"Graph: {e}")

        # 4. 更新缓存
        if self.cache_client:
            try:
                self._cache_document(document)
            except Exception as e:
                results["errors"].append(f"Cache: {e}")

        results["chunks_indexed"] = len(document.chunks)
        return results

    def _index_to_vector(self, document: Document) -> int:
        """索引到向量库"""
        points = []
        for chunk in document.chunks:
            if chunk.embedding:
                points.append(
                    PointStruct(
                        id=chunk.chunk_id,
                        vector=chunk.embedding,
                        payload={
                            "doc_id": chunk.doc_id,
                            "content": chunk.content,
                            "page_number": chunk.page_number,
                            "section": chunk.section,
                            "keywords": chunk.keywords,
                            "confidence": chunk.confidence,
                        },
                    )
                )

        if points:
            self.vector_client.upsert(
                collection_name=self.config.vector.collection_name, points=points
            )
        return len(points)

    def _index_to_keyword(self, document: Document) -> int:
        """索引到关键词库"""
        for chunk in document.chunks:
            self.keyword_client.index(
                index=self.config.keyword.index_name,
                id=chunk.chunk_id,
                document={
                    "doc_id": chunk.doc_id,
                    "chunk_id": chunk.chunk_id,
                    "content": chunk.content,
                    "keywords": chunk.keywords,
                    "page_number": chunk.page_number,
                    "section": chunk.section,
                    "timestamp": datetime.now().isoformat(),
                },
            )
        self.keyword_client.indices.refresh(index=self.config.keyword.index_name)
        return len(document.chunks)

    def _index_to_graph(self, document: Document) -> int:
        """索引到图库"""
        with self.graph_driver.session() as session:
            # 创建文档节点
            session.run(
                """
                MERGE (d:Document {doc_id: $doc_id})
                SET d.title = $title, d.source = $source, d.timestamp = $timestamp
            """,
                {
                    "doc_id": document.metadata.doc_id,
                    "title": document.metadata.title,
                    "source": document.metadata.source,
                    "timestamp": datetime.now().isoformat(),
                },
            )

            # 创建块节点和关系
            for chunk in document.chunks:
                session.run(
                    """
                    MATCH (d:Document {doc_id: $doc_id})
                    MERGE (c:Chunk {chunk_id: $chunk_id})
                    SET c.content = $content, c.page = $page, c.section = $section
                    MERGE (c)-[:BELONGS_TO]->(d)
                """,
                    {
                        "doc_id": chunk.doc_id,
                        "chunk_id": chunk.chunk_id,
                        "content": chunk.content[:500],  # 限制长度
                        "page": chunk.page_number,
                        "section": chunk.section or "",
                    },
                )

                # 创建实体关系
                for entity in chunk.entities:
                    if entity.get("name"):
                        session.run(
                            """
                            MATCH (c:Chunk {chunk_id: $chunk_id})
                            MERGE (e:Entity {name: $name, type: $type})
                            MERGE (c)-[:CONTAINS {confidence: $confidence}]->(e)
                        """,
                            {
                                "chunk_id": chunk.chunk_id,
                                "name": entity.get("name"),
                                "type": entity.get("type", "UNKNOWN"),
                                "confidence": entity.get("confidence", 1.0),
                            },
                        )

        return len(document.chunks)

    def _cache_document(self, document: Document):
        """缓存文档"""
        key = f"doc:{document.metadata.doc_id}"
        value = json.dumps(
            {
                "metadata": {
                    "doc_id": document.metadata.doc_id,
                    "title": document.metadata.title,
                    "source": document.metadata.source,
                },
                "chunk_count": len(document.chunks),
                "timestamp": datetime.now().isoformat(),
            }
        )
        self.cache_client.setex(key, 3600, value)

    # ========== 统一检索接口 ==========

    def search(self, query: SearchQuery, config: RetrievalConfig) -> SearchContext:
        """统一检索接口"""
        context_id = str(uuid.uuid4())
        start_time = datetime.now()

        context = SearchContext(context_id=context_id, query=query, results=[])

        # 1. 多路召回
        candidates = self._multi_recall(query, config)
        context.recall_stats = {
            "vector_count": len(candidates.get("vector", [])),
            "keyword_count": len(candidates.get("keyword", [])),
            "graph_count": len(candidates.get("graph", [])),
        }

        # 2. 合并去重
        merged = self._merge_candidates(candidates)
        context.total_chunks_searched = len(merged)

        # 3. 精排
        if config.enable_rerank and len(merged) > 0:
            reranked = self._rerank(query, merged, config)
        else:
            reranked = merged

        # 4. 分数融合
        if config.enable_fusion:
            final_results = self._fuse_scores(reranked, config)
        else:
            final_results = reranked

        context.results = final_results[: query.top_k]
        context.completed_at = datetime.now().isoformat()
        context.latency_ms = (datetime.now() - start_time).total_seconds() * 1000

        return context

    def _multi_recall(
        self, query: SearchQuery, config: RetrievalConfig
    ) -> Dict[str, List[SearchResultItem]]:
        """多路召回"""
        candidates = {}

        # 向量召回
        if self.vector_client and query.mode in ["vector", "hybrid"] and config.vector_top_k > 0:
            try:
                from infrastructure.adapters.embedding_service import get_embedding_service

                # 使用mock embedding service避免加载模型
                embedding_service = get_embedding_service(use_mock=True)

                # 生成查询向量
                query_vector = embedding_service.encode_single(query.text)

                # 搜索向量库 (使用REST API以兼容旧版Qdrant)
                import requests

                search_response = requests.post(
                    f"http://{self.config.vector.host}:{self.config.vector.port}/collections/{self.config.vector.collection_name}/points/search",
                    json={
                        "vector": query_vector,
                        "limit": config.vector_top_k,
                        "with_payload": True,
                    },
                )



                candidates["vector"] = []
                if search_response.status_code == 200:
                    search_result = search_response.json().get("result", [])
                    for point in search_result:
                        payload = point.get("payload", {}) or {}
                        chunk = DocumentChunk(
                            chunk_id=point.get("id"),
                            doc_id=payload.get("doc_id", ""),
                            content=payload.get("content", ""),
                            chunk_type=ChunkType.TEXT,
                            page_number=payload.get("page_number", 1),
                            section=payload.get("section"),
                            keywords=payload.get("keywords", []),
                            confidence=payload.get("confidence", 1.0),
                        )
                        candidates["vector"].append(
                            SearchResultItem(
                                result_id=str(uuid.uuid4()),
                                chunk=chunk,
                                vector_score=point.get("score", 0),
                            )
                        )
            except Exception as e:
                logger.error(f"Vector recall failed: {e}")

        # 关键词召回
        if self.keyword_client and query.mode in ["keyword", "hybrid"]:
            try:
                response = self.keyword_client.search(
                    index=self.config.keyword.index_name,
                    body={
                        "query": {"match": {"content": query.text}},
                        "size": config.keyword_top_k,
                    },
                )


                candidates["keyword"] = []
                for hit in response["hits"]["hits"]:
                    source = hit["_source"]
                    chunk = DocumentChunk(
                        chunk_id=source.get("chunk_id", hit["_id"]),
                        doc_id=source.get("doc_id", ""),
                        content=source.get("content", ""),
                        chunk_type=ChunkType.TEXT,
                        page_number=source.get("page_number", 1),
                        section=source.get("section"),
                        keywords=source.get("keywords", []),
                    )
                    candidates["keyword"].append(
                        SearchResultItem(
                            result_id=str(uuid.uuid4()),
                            chunk=chunk,
                            keyword_score=hit["_score"],
                        )
                    )
            except Exception as e:
                logger.error(f"Keyword recall failed: {e}")

        # 图谱召回
        if self.graph_driver:
            try:
                logger.info(f"Executing graph recall for query: {query.text}, top_k: {config.graph_top_k}")
                with self.graph_driver.session() as session:
                    # 通过关系获取Document的doc_id
                    result = session.run(
                        """
                        MATCH (c:Chunk)-[:BELONGS_TO]->(d:Document)
                        WHERE c.content CONTAINS $query
                        RETURN c.chunk_id as chunk_id, c.content as content, 
                               c.page as page, c.section as section,
                               d.doc_id as doc_id, d.title as title
                        LIMIT $top_k
                    """,
                        {"query": query.text, "top_k": config.graph_top_k},
                    )

    

                    candidates["graph"] = []
                    for record in result:
                        chunk = DocumentChunk(
                            chunk_id=record["chunk_id"],
                            doc_id=record["doc_id"] or "",
                            content=record["content"] or "",
                            chunk_type=ChunkType.TEXT,
                            page_number=record["page"] or 1,
                            section=record["section"],
                        )
                        candidates["graph"].append(
                            SearchResultItem(
                                result_id=str(uuid.uuid4()),
                                chunk=chunk,
                                graph_score=1.0,  # 简化评分
                            )
                        )
                    logger.info(f"Graph recall found {len(candidates['graph'])} results")
            except Exception as e:
                logger.error(f"Graph recall failed: {e}")

        return candidates

    def _merge_candidates(
        self, candidates: Dict[str, List[SearchResultItem]]
    ) -> List[SearchResultItem]:
        """合并候选结果"""
        seen = set()
        merged = []

        for source, items in candidates.items():
            for item in items:
                # 去重逻辑
                key = item.chunk.chunk_id if item.chunk else item.result_id
                if key not in seen:
                    seen.add(key)
                    merged.append(item)

        return merged

    def _rerank(
        self, query: SearchQuery, candidates: List[SearchResultItem], config: RetrievalConfig
    ) -> List[SearchResultItem]:
        """精排 - 使用Cross-Encoder Reranker"""
        if not candidates:
            return []

        try:
            from infrastructure.adapters.reranker_service import get_reranker_service

            # 获取reranker服务
            reranker = get_reranker_service()

            # 提取候选文档内容
            documents = []
            for item in candidates:
                # 组合chunk内容和metadata信息用于rerank
                content = item.chunk.content if item.chunk else ""
                # 添加文档标题信息（如果有）
                doc_name = item.doc_name or ""
                section = item.chunk.section if item.chunk and item.chunk.section else ""

                # 构建富文本表示
                rich_content = f"{doc_name} {section} {content}".strip()
                documents.append(rich_content)

            # 调用reranker模型
            scores = reranker.rerank(query.text, documents)

            # 更新每个候选的rerank_score
            for i, item in enumerate(candidates):
                item.rerank_score = float(scores[i])

            # 按rerank_score排序并返回Top-K
            return sorted(candidates, key=lambda x: x.rerank_score, reverse=True)[
                : config.rerank_top_k
            ]

        except Exception as e:
            logger.error(f"Reranking failed: {e}")
            # Fallback: 使用加权融合，包括graph_score
            for item in candidates:
                # 考虑所有得分来源
                keyword_score = item.keyword_score or 0
                vector_score = item.vector_score or 0
                graph_score = item.graph_score or 0
                
                # 计算综合得分
                item.rerank_score = keyword_score * 0.33 + vector_score * 0.33 + graph_score * 0.34
            
            # 按得分排序并返回Top-K
            return sorted(candidates, key=lambda x: x.rerank_score, reverse=True)[
                : config.rerank_top_k
            ]

    def _fuse_scores(
        self, candidates: List[SearchResultItem], config: RetrievalConfig
    ) -> List[SearchResultItem]:
        """分数融合"""
        weights = config.fusion_weights

        for item in candidates:
            item.final_score = (
                weights.get("rerank", 0.4) * item.rerank_score
                + weights.get("vector", 0.3) * item.vector_score
                + weights.get("keyword", 0.2) * item.keyword_score
                + weights.get("graph", 0.05) * item.graph_score
            )

        return sorted(candidates, key=lambda x: x.final_score, reverse=True)

    # ========== 健康检查 ==========

    def health_check(self) -> Dict[str, Any]:
        """四库健康检查"""
        status = {}

        # 向量库
        try:
            self.vector_client.get_collections()
            status["vector"] = "healthy"
        except Exception as e:
            status["vector"] = f"unhealthy: {e}"

        # 关键词库
        try:
            self.keyword_client.cluster.health()
            status["keyword"] = "healthy"
        except Exception as e:
            status["keyword"] = f"unhealthy: {e}"

        # 图库
        try:
            with self.graph_driver.session() as session:
                session.run("RETURN 1")
            status["graph"] = "healthy"
        except Exception as e:
            status["graph"] = f"unhealthy: {e}"

        # 缓存
        try:
            self.cache_client.ping()
            status["cache"] = "healthy"
        except Exception as e:
            status["cache"] = f"unhealthy: {e}"

        return status

    def close(self):
        """关闭连接"""
        if self.graph_driver:
            self.graph_driver.close()
        if self.cache_client:
            self.cache_client.close()