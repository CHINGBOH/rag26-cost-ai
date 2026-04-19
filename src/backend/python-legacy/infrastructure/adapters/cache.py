"""
缓存适配器
实现 CachePort 接口
支持内存缓存和Redis缓存
"""

import asyncio
import time
from typing import Any, Optional, Dict
import logging

from domain.ports import CachePort
from config.settings import CacheConfig

logger = logging.getLogger(__name__)


class MemoryCacheAdapter(CachePort):
    """内存缓存适配器"""

    def __init__(self, config: CacheConfig):
        self.config = config
        self._storage: Dict[str, tuple[Any, float]] = {}  # key -> (value, expiry_time)

    async def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        if key not in self._storage:
            return None

        value, expiry_time = self._storage[key]

        # 检查是否过期
        if expiry_time > 0 and time.time() > expiry_time:
            del self._storage[key]
            return None

        return value

    async def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        """设置缓存"""
        try:
            expiry_time = time.time() + ttl if ttl > 0 else 0
            self._storage[key] = (value, expiry_time)

            # 简单的内存清理（如果存储太大）
            if len(self._storage) > 10000:
                # 移除过期项
                current_time = time.time()
                keys_to_delete = [
                    k
                    for k, (_, expiry) in self._storage.items()
                    if expiry > 0 and expiry < current_time
                ]
                for k in keys_to_delete:
                    del self._storage[k]

            return True
        except Exception as e:
            logger.error(f"Memory cache set error: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """删除缓存"""
        try:
            if key in self._storage:
                del self._storage[key]
            return True
        except Exception as e:
            logger.error(f"Memory cache delete error: {e}")
            return False


class RedisCacheAdapter(CachePort):
    """Redis缓存适配器"""

    def __init__(self, config: CacheConfig):
        self.config = config
        self._client = None
        self._connect()

    def _connect(self):
        """连接到Redis"""
        try:
            import redis

            self._client = redis.Redis(
                host=self.config.host,
                port=self.config.port,
                db=self.config.db,
                decode_responses=True,  # 自动解码为字符串
            )
            # 测试连接
            self._client.ping()
            logger.info(f"✅ Redis cache connected: {self.config.host}:{self.config.port}")
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
            self._client = None

    async def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        if not self._client:
            return None

        try:
            # 将同步的redis.get调用转移到线程池执行
            loop = asyncio.get_event_loop()
            value = await loop.run_in_executor(None, self._client.get, key)
            return value
        except Exception as e:
            logger.error(f"Redis cache get error: {e}")
            return None

    async def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        """设置缓存"""
        if not self._client:
            return False

        try:
            loop = asyncio.get_event_loop()
            if ttl > 0:
                await loop.run_in_executor(None, self._client.setex, key, ttl, value)
            else:
                await loop.run_in_executor(None, self._client.set, key, value)
            return True
        except Exception as e:
            logger.error(f"Redis cache set error: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """删除缓存"""
        if not self._client:
            return False

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._client.delete, key)
            return result > 0
        except Exception as e:
            logger.error(f"Redis cache delete error: {e}")
            return False
