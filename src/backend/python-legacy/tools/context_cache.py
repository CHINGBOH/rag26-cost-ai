#!/usr/bin/env python3
"""
Context Cache for PG Single-Database RAG System
使用 Qdrant 缓存会话上下文，避免重复查询
"""

import os
import json
import hashlib
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import logging

from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Qdrant 配置
QDRANT_HOST = os.environ.get("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", 6333))
QDRANT_COLLECTION = "session_context"

class ContextCache:
    """
    会话上下文缓存管理器
    使用 Qdrant 存储和检索会话上下文
    """

    def __init__(self):
        self.client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        self._ensure_collection()

    def _ensure_collection(self):
        """确保集合存在"""
        try:
            collections = [c.name for c in self.client.get_collections().collections]
            if QDRANT_COLLECTION not in collections:
                logger.info(f"Creating Qdrant collection: {QDRANT_COLLECTION}")
                self.client.create_collection(
                    collection_name=QDRANT_COLLECTION,
                    vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
                )
                logger.info(f"Collection {QDRANT_COLLECTION} created")
            else:
                logger.info(f"Collection {QDRANT_COLLECTION} exists")
        except Exception as e:
            logger.error(f"Failed to ensure collection: {e}")
            raise

    def _generate_cache_key(self, query: str, filters: Dict[str, Any]) -> str:
        """生成缓存键"""
        key_data = {
            "query": query,
            "filters": filters
        }
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()

    def _get_cache_ttl(self) -> int:
        """获取缓存过期时间（秒）"""
        # 默认缓存 1 小时
        return int(os.environ.get("CACHE_TTL_SECONDS", 3600))

    def get_cached_result(self, query: str, filters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        获取缓存的结果

        从 Qdrant 向量数据库中根据查询字符串和过滤条件检索缓存的结果。
        如果找到缓存且未过期，则返回缓存的数据；否则返回 None。

        Args:
            query: 查询字符串，用于生成缓存键
            filters: 查询过滤条件字典，与 query 共同生成唯一缓存键

        Returns:
            成功时返回包含 result, cached_at, query, filters 的字典；
            未找到缓存或缓存已过期时返回 None
        """
        cache_key = self._generate_cache_key(query, filters)

        try:
            # 使用 scroll 方法查找缓存
            scroll_result = self.client.scroll(
                collection_name=QDRANT_COLLECTION,
                filter=Filter(
                    must=[
                        FieldCondition(
                            key="cache_key",
                            match=MatchValue(value=cache_key)
                        )
                    ]
                ),
                limit=1
            )

            if not scroll_result or not scroll_result[0]:
                return None

            point = scroll_result[0][0]
            payload = point.payload

            # 检查是否过期
            created_at = datetime.fromisoformat(payload.get("created_at", ""))
            ttl = self._get_cache_ttl()
            if datetime.now() - created_at > timedelta(seconds=ttl):
                # 缓存过期，删除
                self.client.delete(
                    collection_name=QDRANT_COLLECTION,
                    points_selector=Filter(
                        must=[
                            FieldCondition(
                                key="cache_key",
                                match=MatchValue(value=cache_key)
                            )
                        ]
                    )
                )
                return None

            # 返回缓存的结果
            return {
                "result": payload.get("result"),
                "cached_at": payload.get("created_at"),
                "query": payload.get("query"),
                "filters": payload.get("filters")
            }

        except Exception as e:
            logger.warning(f"Failed to get cached result: {e}")
            return None

    def set_cached_result(self, query: str, filters: Dict[str, Any],
                         result: Dict[str, Any], embedding: Optional[List[float]] = None) -> bool:
        """
        缓存查询结果

        Args:
            query: 查询字符串
            filters: 查询过滤条件
            result: 查询结果
            embedding: 可选的查询向量（用于语义缓存）

        Returns:
            是否成功缓存
        """
        cache_key = self._generate_cache_key(query, filters)

        try:
            # 如果没有提供 embedding，使用零向量
            if embedding is None:
                embedding = [0.0] * 1024

            # 准备 payload
            payload = {
                "cache_key": cache_key,
                "query": query,
                "filters": json.dumps(filters),
                "result": json.dumps(result),
                "created_at": datetime.now().isoformat(),
                "ttl": self._get_cache_ttl()
            }

            # 创建点
            point = PointStruct(
                id=hash(cache_key) % (2**63),  # 使用 hash 作为 ID
                vector=embedding,
                payload=payload
            )

            # 先删除旧的缓存（如果存在）
            self.client.delete(
                collection_name=QDRANT_COLLECTION,
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="cache_key",
                            match=MatchValue(value=cache_key)
                        )
                    ]
                )
            )

            # 插入新的缓存
            self.client.upsert(
                collection_name=QDRANT_COLLECTION,
                points=[point]
            )

            logger.info(f"Cached result for query: {query}")
            return True

        except Exception as e:
            logger.error(f"Failed to cache result: {e}")
            return False

    def get_similar_queries(self, query: str, embedding: List[float],
                           limit: int = 5) -> List[Dict[str, Any]]:
        """
        获取语义相似的查询（用于推荐或缓存预热）

        Args:
            query: 当前查询
            embedding: 查询的向量表示
            limit: 返回数量限制

        Returns:
            相似的查询列表
        """
        try:
            search_result = self.client.query_points(
                collection_name=QDRANT_COLLECTION,
                query=embedding,
                limit=limit,
                score_threshold=0.7  # 相似度阈值
            ).points

            similar_queries = []
            for point in search_result:
                payload = point.payload
                similar_queries.append({
                    "query": payload.get("query"),
                    "filters": json.loads(payload.get("filters", "{}")),
                    "similarity": point.score,
                    "cached_at": payload.get("created_at")
                })

            return similar_queries

        except Exception as e:
            logger.warning(f"Failed to get similar queries: {e}")
            return []

    def clear_expired_cache(self) -> int:
        """
        清理过期的缓存

        Returns:
            清理的缓存条目数量
        """
        try:
            ttl = self._get_cache_ttl()
            cutoff_time = datetime.now() - timedelta(seconds=ttl)

            # 查找过期的缓存
            expired_points = self.client.scroll(
                collection_name=QDRANT_COLLECTION,
                filter=Filter(
                    must=[
                        FieldCondition(
                            key="created_at",
                            match=MatchValue(value=cutoff_time.isoformat())
                        )
                    ]
                ),
                limit=1000
            )

            if expired_points and expired_points[0]:
                point_ids = [point.id for point in expired_points[0]]

                # 删除过期缓存
                self.client.delete(
                    collection_name=QDRANT_COLLECTION,
                    points_selector=point_ids
                )

                logger.info(f"Cleared {len(point_ids)} expired cache entries")
                return len(point_ids)

            return 0

        except Exception as e:
            logger.error(f"Failed to clear expired cache: {e}")
            return 0

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息

        Returns:
            缓存统计数据
        """
        try:
            collection_info = self.client.get_collection(QDRANT_COLLECTION)

            return {
                "collection_name": QDRANT_COLLECTION,
                "total_points": collection_info.points_count,
                "vector_size": collection_info.config.params.vectors.size,
                "distance": collection_info.config.params.vectors.distance,
                "ttl_seconds": self._get_cache_ttl()
            }

        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}")
            return {"error": str(e)}

# 全局缓存实例
_cache_instance = None

def get_context_cache() -> ContextCache:
    """获取全局上下文缓存实例"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = ContextCache()
    return _cache_instance

# 便捷函数
def cache_query_result(query: str, filters: Dict[str, Any], result: Dict[str, Any],
                      embedding: Optional[List[float]] = None) -> bool:
    """缓存查询结果"""
    cache = get_context_cache()
    return cache.set_cached_result(query, filters, result, embedding)

def get_cached_query_result(query: str, filters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """获取缓存的查询结果"""
    cache = get_context_cache()
    return cache.get_cached_result(query, filters)



def find_similar_queries(query: str, embedding: List[float], limit: int = 5) -> List[Dict[str, Any]]:
    """查找相似的查询"""
    cache = get_context_cache()
    return cache.get_similar_queries(query, embedding, limit)

# 测试函数
def test_context_cache():
    """测试上下文缓存功能"""
    print("=== 测试 Context Cache ===")

    cache = get_context_cache()

    # 测试缓存统计
    stats = cache.get_cache_stats()
    print(f"缓存统计: {stats}")

    # 测试缓存操作
    test_query = "钢筋价格"
    test_filters = {"period": "2024-01"}
    test_result = {"price": 4500, "unit": "吨"}

    # 缓存结果
    success = cache.set_cached_result(test_query, test_filters, test_result)
    print(f"缓存结果: {'成功' if success else '失败'}")

    # 获取缓存结果
    cached = cache.get_cached_result(test_query, test_filters)
    print(f"获取缓存: {'成功' if cached else '失败'}")

    if cached:
        print(f"缓存内容: {cached['result']}")

    # 测试相似查询（需要 embedding）
    # 注意：这里只是演示，实际使用需要真实的 embedding
    print("相似查询测试: 需要真实的 embedding 向量")

if __name__ == "__main__":
    test_context_cache()