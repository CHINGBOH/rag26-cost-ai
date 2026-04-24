"""
存储配置 - 单库改造后
只保留 PostgreSQL + pgvector、Qdrant(session_context)、Redis
"""

from dataclasses import dataclass, field
from typing import Optional
import os
import yaml


@dataclass
class QdrantConfig:
    """Qdrant 配置 - 仅用于 session_context"""
    host: str = "localhost"
    port: int = 6333
    collection_name: str = "session_context"
    vector_size: int = 1024
    distance: str = "Cosine"
    timeout: int = 30
    pool_size: int = 10


@dataclass
class PostgresConfig:
    """PostgreSQL 配置"""
    host: str = "localhost"
    port: int = 5432
    database: str = "rag_db"
    user: str = "rag_user"
    password: str = ""
    max_connections: int = 20
    command_timeout: int = 60


@dataclass
class CacheConfig:
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    max_connections: int = 50
    socket_timeout: int = 10


@dataclass
class StoreConfig:
    qdrant: QdrantConfig = field(default_factory=QdrantConfig)
    postgres: PostgresConfig = field(default_factory=PostgresConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)

    @classmethod
    def from_yaml(cls, path: str) -> "StoreConfig":
        """从 YAML 文件加载配置"""
        if not os.path.exists(path):
            return cls()

        with open(path, "r") as f:
            config = yaml.safe_load(f)

        return cls(
            qdrant=QdrantConfig(**config.get("qdrant", {})),
            postgres=PostgresConfig(**config.get("postgres", {})),
            cache=CacheConfig(**config.get("cache", {})),
        )

    @classmethod
    def from_env(cls) -> "StoreConfig":
        """从环境变量加载配置"""
        return cls(
            qdrant=QdrantConfig(
                host=os.getenv("QDRANT_HOST", "localhost"),
                port=int(os.getenv("QDRANT_PORT", "6333")),
                collection_name=os.getenv("QDRANT_COLLECTION_NAME", "session_context"),
                timeout=int(os.getenv("QDRANT_TIMEOUT", "30")),
                pool_size=int(os.getenv("QDRANT_POOL_SIZE", "10")),
            ),
            postgres=PostgresConfig(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                database=os.getenv("POSTGRES_DB", "rag_db"),
                user=os.getenv("POSTGRES_USER", "rag_user"),
                password=os.getenv("POSTGRES_PASSWORD", ""),
                max_connections=int(os.getenv("POSTGRES_MAX_CONNECTIONS", "20")),
            ),
            cache=CacheConfig(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", "6379")),
                password=os.getenv("REDIS_PASSWORD"),
                max_connections=int(os.getenv("REDIS_MAX_CONNECTIONS", "50")),
                socket_timeout=int(os.getenv("REDIS_SOCKET_TIMEOUT", "10")),
            ),
        )
