"""
存储配置
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import os
import yaml


@dataclass
class VectorStoreConfig:
    host: str = "localhost"
    port: int = 6333
    collection_name: str = "documents"
    vector_size: int = 768
    distance: str = "Cosine"
    timeout: int = 30
    pool_size: int = 10


@dataclass
class KeywordStoreConfig:
    hosts: list = field(default_factory=lambda: ["http://localhost:9200"])
    index_name: str = "documents"
    username: Optional[str] = None
    password: Optional[str] = None
    max_connections: int = 20
    timeout: int = 30


@dataclass
class GraphStoreConfig:
    uri: str = "bolt://localhost:7687"
    username: str = "neo4j"
    password: str = "password"
    database: str = "neo4j"
    max_connection_pool_size: int = 50
    connection_acquisition_timeout: int = 60


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
    vector: VectorStoreConfig = field(default_factory=VectorStoreConfig)
    keyword: KeywordStoreConfig = field(default_factory=KeywordStoreConfig)
    graph: GraphStoreConfig = field(default_factory=GraphStoreConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)

    @classmethod
    def from_yaml(cls, path: str) -> "StoreConfig":
        """从 YAML 文件加载配置"""
        if not os.path.exists(path):
            return cls()

        with open(path, "r") as f:
            config = yaml.safe_load(f)

        return cls(
            vector=VectorStoreConfig(**config.get("vector_store", {})),
            keyword=KeywordStoreConfig(**config.get("keyword_store", {})),
            graph=GraphStoreConfig(**config.get("graph_store", {})),
            cache=CacheConfig(**config.get("cache", {})),
        )

    @classmethod
    def from_env(cls) -> "StoreConfig":
        """从环境变量加载配置"""
        return cls(
            vector=VectorStoreConfig(
                host=os.getenv("QDRANT_HOST", "localhost"),
                port=int(os.getenv("QDRANT_PORT", "6333")),
                timeout=int(os.getenv("QDRANT_TIMEOUT", "30")),
                pool_size=int(os.getenv("QDRANT_POOL_SIZE", "10")),
            ),
            keyword=KeywordStoreConfig(
                hosts=[os.getenv("ES_HOST", "http://localhost:9200")],
                username=os.getenv("ES_USERNAME"),
                password=os.getenv("ES_PASSWORD"),
                max_connections=int(os.getenv("ES_MAX_CONNECTIONS", "20")),
                timeout=int(os.getenv("ES_TIMEOUT", "30")),
            ),
            graph=GraphStoreConfig(
                uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
                password=os.getenv("NEO4J_PASSWORD", "password"),
                max_connection_pool_size=int(os.getenv("NEO4J_MAX_CONNECTION_POOL_SIZE", "50")),
                connection_acquisition_timeout=int(
                    os.getenv("NEO4J_CONNECTION_ACQUISITION_TIMEOUT", "60")
                ),
            ),
            cache=CacheConfig(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", "6379")),
                password=os.getenv("REDIS_PASSWORD"),
                max_connections=int(os.getenv("REDIS_MAX_CONNECTIONS", "50")),
                socket_timeout=int(os.getenv("REDIS_SOCKET_TIMEOUT", "10")),
            ),
        )
