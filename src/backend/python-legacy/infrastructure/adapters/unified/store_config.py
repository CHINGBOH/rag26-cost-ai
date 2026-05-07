"""
存储配置 - 单库改造后
只保留 PostgreSQL + pgvector、Qdrant(session_context)、Redis
"""

from dataclasses import dataclass, field
from typing import Optional
import yaml

from config.runtime import read_runtime_config


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
        """从规范化运行时配置加载配置"""
        runtime_config = read_runtime_config()
        return cls(
            qdrant=QdrantConfig(
                host=runtime_config.qdrant_host,
                port=runtime_config.qdrant_port,
                collection_name="session_context",
                timeout=runtime_config.qdrant_timeout,
                pool_size=runtime_config.qdrant_pool_size,
            ),
            postgres=PostgresConfig(
                host=runtime_config.postgres_host,
                port=runtime_config.postgres_port,
                database=runtime_config.postgres_db,
                user=runtime_config.postgres_user,
                password=runtime_config.postgres_password,
                max_connections=runtime_config.postgres_max_connections,
            ),
            cache=CacheConfig(
                host=runtime_config.redis_host,
                port=runtime_config.redis_port,
                db=runtime_config.redis_db,
                password=runtime_config.redis_password,
                max_connections=runtime_config.redis_max_connections,
                socket_timeout=runtime_config.redis_socket_timeout,
            ),
        )
