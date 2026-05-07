"""
存储配置 - 单库改造后
只保留 PostgreSQL + pgvector、Qdrant(session_context)、Redis
"""

from dataclasses import dataclass, field
from typing import Optional
import os
from urllib.parse import urlparse
import yaml

from app.runtime_config import postgres_connection_kwargs, read_runtime_config, redis_connection_kwargs


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
        runtime = read_runtime_config()
        postgres = postgres_connection_kwargs()
        redis = redis_connection_kwargs()
        qdrant = urlparse(runtime.qdrant_url)
        return cls(
            qdrant=QdrantConfig(
                host=qdrant.hostname or "localhost",
                port=qdrant.port or 6333,
                collection_name=runtime.qdrant_session_collection,
                timeout=runtime.qdrant_timeout_seconds,
                pool_size=runtime.qdrant_pool_size,
            ),
            postgres=PostgresConfig(
                host=str(postgres["host"]),
                port=int(postgres["port"]),
                database=str(postgres["dbname"]),
                user=str(postgres["user"]),
                password=str(postgres["password"]),
                max_connections=runtime.postgres_max_connections,
            ),
            cache=CacheConfig(
                host=str(redis["host"]),
                port=int(redis["port"]),
                db=int(redis["db"]),
                password=redis["password"],
                max_connections=runtime.redis_max_connections,
                socket_timeout=runtime.redis_socket_timeout_seconds,
            ),
        )
