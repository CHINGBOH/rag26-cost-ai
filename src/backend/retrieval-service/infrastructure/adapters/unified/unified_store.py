"""
统一存储层 - 单库改造后 (retrieval-service)
PostgreSQL + pgvector 作为主数据库
Qdrant 仅用于 session_context
"""

import uuid
import json
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime

from domain_models.document import Document, DocumentChunk, DocumentMetadata
from domain_models.search import SearchQuery, SearchResultItem, SearchContext
from domain_models.retrieval import RetrievalConfig

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
import redis
import httpx

from .store_config import StoreConfig

logger = logging.getLogger(__name__)


class UnifiedStore:
    """统一存储层 - PG + pgvector 为主，Qdrant 仅 session_context"""

    def __init__(self, config: Optional[StoreConfig] = None):
        self.config = config or StoreConfig.from_env()

        self._init_pg_pool()
        self._init_qdrant()
        self._init_cache()

        logger.info("UnifiedStore initialized (PG single-db mode)")

    def _init_pg_pool(self):
        """初始化 PostgreSQL 连接池"""
        try:
            import psycopg2
            from psycopg2.pool import ThreadedConnectionPool

            dsn = (
                f"host={self.config.postgres.host} "
                f"port={self.config.postgres.port} "
                f"dbname={self.config.postgres.database} "
                f"user={self.config.postgres.user} "
                f"password={self.config.postgres.password}"
            )
            self.pg_pool = ThreadedConnectionPool(
                minconn=1,
                maxconn=self.config.postgres.max_connections,
                dsn=dsn,
            )
            conn = self.pg_pool.getconn()
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            self.pg_pool.putconn(conn)
            logger.info(f"✅ PostgreSQL connected")
        except Exception as e:
            logger.error(f"❌ PostgreSQL connection failed: {e}")
            self.pg_pool = None

    def _init_qdrant(self):
        """初始化 Qdrant - 仅用于 session_context"""
        try:
            self.qdrant_client = QdrantClient(
                host=self.config.qdrant.host,
                port=self.config.qdrant.port,
                timeout=self.config.qdrant.timeout,
                limits=httpx.Limits(max_connections=self.config.qdrant.pool_size)
                if self.config.qdrant.pool_size
                else None,
            )
            self._ensure_qdrant_collection()
            logger.info(f"✅ Qdrant connected (session_context only)")
        except Exception as e:
            logger.error(f"❌ Qdrant connection failed: {e}")
            self.qdrant_client = None

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
            logger.info(f"✅ Cache connected")
        except Exception as e:
            logger.error(f"❌ Cache connection failed: {e}")
            self.cache_client = None

    def _ensure_qdrant_collection(self):
        try:
            collections = self.qdrant_client.get_collections()
            collection_names = [c.name for c in collections.collections]
            if self.config.qdrant.collection_name not in collection_names:
                self.qdrant_client.create_collection(
                    collection_name=self.config.qdrant.collection_name,
                    vectors_config=VectorParams(
                        size=self.config.qdrant.vector_size, distance=Distance.COSINE
                    ),
                )
        except Exception as e:
            logger.warning(f"Qdrant collection check failed: {e}")

    def index_document(self, document: Document) -> Dict[str, Any]:
        """将文档索引到 PostgreSQL"""
        results = {"doc_id": document.metadata.doc_id, "chunks_indexed": 0, "errors": []}
        if self.pg_pool:
            try:
                pg_count = self._index_to_postgres(document)
                results["postgres_indexed"] = pg_count
            except Exception as e:
                results["errors"].append(f"PostgreSQL: {e}")
        if self.cache_client:
            try:
                self._cache_document(document)
            except Exception as e:
                results["errors"].append(f"Cache: {e}")
        results["chunks_indexed"] = len(document.chunks)
        return results

    def _index_to_postgres(self, document: Document) -> int:
        """索引到 PostgreSQL text_chunks 表"""
        conn = self.pg_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO documents (file_name, status, created_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT DO NOTHING
                    RETURNING id
                """,
                    (document.metadata.title, "imported"),
                )
                doc_row = cur.fetchone()
                document_id = doc_row[0] if doc_row else None
                if not document_id:
                    cur.execute(
                        "SELECT id FROM documents WHERE file_name = %s LIMIT 1",
                        (document.metadata.title,),
                    )
                    row = cur.fetchone()
                    document_id = row[0] if row else None

                inserted = 0
                for i, chunk in enumerate(document.chunks):
                    if chunk.embedding:
                        cur.execute(
                            """
                            INSERT INTO text_chunks
                            (document_id, chunk_index, content, page_number, embedding, created_at)
                            VALUES (%s, %s, %s, %s, %s, NOW())
                            ON CONFLICT DO NOTHING
                        """,
                            (document_id, i, chunk.content, chunk.page_number, chunk.embedding),
                        )
                        inserted += 1
                conn.commit()
                return inserted
        finally:
            self.pg_pool.putconn(conn)

    def _cache_document(self, document: Document):
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

    def search(self, query: SearchQuery, config: RetrievalConfig) -> SearchContext:
        """统一检索接口 - PG 双路召回"""
        context_id = str(uuid.uuid4())
        start_time = datetime.now()
        context = SearchContext(context_id=context_id, query=query, results=[])

        candidates = self._multi_recall(query, config)
        context.recall_stats = {
            "vector_count": len(candidates.get("vector", [])),
            "text_count": len(candidates.get("text", [])),
        }

        merged = self._merge_candidates(candidates)
        context.total_chunks_searched = len(merged)

        if config.enable_rerank and len(merged) > 0:
            reranked = self._rerank(query, merged, config)
        else:
            reranked = merged

        if config.enable_fusion:
            final_results = self._fuse_scores(reranked, config)
        else:
            final_results = reranked

        context.results = final_results[: query.top_k]
        context.completed_at = datetime.now().isoformat()
        context.latency_ms = (datetime.now() - start_time).total_seconds() * 1000
        return context

    def _multi_recall(self, query: SearchQuery, config: RetrievalConfig) -> Dict[str, List[SearchResultItem]]:
        candidates = {}
        if self.pg_pool and query.mode in ["vector", "hybrid"] and config.vector_top_k > 0:
            try:
                query_vector = self._get_query_embedding(query.text)
                if query_vector:
                    candidates["vector"] = self._pg_vector_search(query_vector, config.vector_top_k)
            except Exception as e:
                logger.error(f"Vector recall failed: {e}")
        if self.pg_pool and query.mode in ["keyword", "hybrid"] and config.keyword_top_k > 0:
            try:
                candidates["text"] = self._pg_fulltext_search(query.text, config.keyword_top_k)
            except Exception as e:
                logger.error(f"Fulltext recall failed: {e}")
        return candidates

    def _get_query_embedding(self, text: str) -> Optional[List[float]]:
        try:
            from infrastructure.embedding_service import get_embedding_service
            embedding_service = get_embedding_service()
            return embedding_service.encode_query(text)
        except Exception as e:
            logger.error(f"Failed to get query embedding: {e}")
            return None

    def _pg_vector_search(self, query_vector: List[float], top_k: int) -> List[SearchResultItem]:
        conn = self.pg_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, document_id, content, page_number, period, doc_type,
                           embedding <=> %s::vector AS distance
                    FROM text_chunks
                    WHERE embedding IS NOT NULL
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """,
                    (query_vector, query_vector, top_k),
                )
                results = []
                for row in cur.fetchall():
                    from domain_models.document import DocumentChunk, ChunkType
                    chunk = DocumentChunk(
                        chunk_id=str(row[0]),
                        doc_id=str(row[1]) if row[1] else "",
                        content=row[2] or "",
                        chunk_type=ChunkType.TEXT,
                        page_number=row[3] or 1,
                        section=row[4] or "",
                    )
                    distance = row[6] if row[6] is not None else 1.0
                    score = max(0.0, 1.0 - distance)
                    results.append(
                        SearchResultItem(
                            result_id=str(uuid.uuid4()),
                            chunk=chunk,
                            vector_score=score,
                        )
                    )
                return results
        finally:
            self.pg_pool.putconn(conn)

    def _pg_fulltext_search(self, query_text: str, top_k: int) -> List[SearchResultItem]:
        conn = self.pg_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, document_id, content, page_number, period, doc_type,
                           ts_rank(tsv, plainto_tsquery('simple', %s)) AS rank
                    FROM text_chunks
                    WHERE tsv @@ plainto_tsquery('simple', %s)
                    ORDER BY rank DESC
                    LIMIT %s
                """,
                    (query_text, query_text, top_k),
                )
                results = []
                for row in cur.fetchall():
                    from domain_models.document import DocumentChunk, ChunkType
                    chunk = DocumentChunk(
                        chunk_id=str(row[0]),
                        doc_id=str(row[1]) if row[1] else "",
                        content=row[2] or "",
                        chunk_type=ChunkType.TEXT,
                        page_number=row[3] or 1,
                        section=row[4] or "",
                    )
                    rank = row[6] if row[6] is not None else 0.0
                    results.append(
                        SearchResultItem(
                            result_id=str(uuid.uuid4()),
                            chunk=chunk,
                            keyword_score=float(rank),
                        )
                    )
                return results
        finally:
            self.pg_pool.putconn(conn)

    def _merge_candidates(self, candidates: Dict[str, List[SearchResultItem]]) -> List[SearchResultItem]:
        seen = {}
        for source, items in candidates.items():
            for item in items:
                key = item.chunk.chunk_id if item.chunk else item.result_id
                if key not in seen:
                    seen[key] = item
                else:
                    existing = seen[key]
                    existing.vector_score = max(existing.vector_score, item.vector_score)
                    existing.keyword_score = max(existing.keyword_score, item.keyword_score)
        return list(seen.values())

    def _rerank(self, query: SearchQuery, candidates: List[SearchResultItem], config: RetrievalConfig) -> List[SearchResultItem]:
        if not candidates:
            return []
        try:
            from infrastructure.reranker_service import get_reranker_service
            reranker = get_reranker_service()
            documents = []
            for item in candidates:
                content = item.chunk.content if item.chunk else ""
                doc_name = getattr(item, "doc_name", "") or ""
                section = item.chunk.section if item.chunk and item.chunk.section else ""
                documents.append(f"{doc_name} {section} {content}".strip())
            scores = reranker.rerank(query.text, documents)
            for i, item in enumerate(candidates):
                item.rerank_score = float(scores[i])
            return sorted(candidates, key=lambda x: x.rerank_score, reverse=True)[: config.rerank_top_k]
        except Exception as e:
            logger.error(f"Reranking failed: {e}")
            for item in candidates:
                item.rerank_score = item.vector_score * 0.6 + item.keyword_score * 0.4
            return sorted(candidates, key=lambda x: x.rerank_score, reverse=True)[: config.rerank_top_k]

    def _fuse_scores(self, candidates: List[SearchResultItem], config: RetrievalConfig) -> List[SearchResultItem]:
        weights = getattr(config, "fusion_weights", {}) or {"rerank": 0.5, "vector": 0.3, "text": 0.2}
        for item in candidates:
            item.final_score = (
                weights.get("rerank", 0.5) * item.rerank_score
                + weights.get("vector", 0.3) * item.vector_score
                + weights.get("text", 0.2) * item.keyword_score
            )
        return sorted(candidates, key=lambda x: x.final_score, reverse=True)

    def health_check(self) -> Dict[str, Any]:
        status = {}
        try:
            conn = self.pg_pool.getconn()
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            self.pg_pool.putconn(conn)
            status["postgres"] = "healthy"
        except Exception as e:
            status["postgres"] = f"unhealthy: {e}"
        try:
            self.qdrant_client.get_collections()
            status["qdrant"] = "healthy"
        except Exception as e:
            status["qdrant"] = f"unhealthy: {e}"
        try:
            self.cache_client.ping()
            status["cache"] = "healthy"
        except Exception as e:
            status["cache"] = f"unhealthy: {e}"
        return status

    def close(self):
        if self.pg_pool:
            self.pg_pool.closeall()
        if self.cache_client:
            self.cache_client.close()
