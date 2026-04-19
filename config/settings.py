"""
配置管理模块
使用 Pydantic Settings + YAML 实现类型安全的配置管理
"""

from typing import Literal, List
from pydantic import Field, field_validator, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
import yaml


class ServerConfig(BaseSettings):
    """服务器配置"""

    model_config = SettingsConfigDict(extra="forbid")

    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    workers: int = Field(default=1, ge=1)
    reload: bool = False


class VectorStoreConfig(BaseSettings):
    """向量存储配置"""

    model_config = SettingsConfigDict(extra="forbid")

    type: Literal["qdrant", "chroma", "memory"] = "qdrant"
    host: str = "localhost"
    port: int = Field(default=6333, ge=1, le=65535)
    collection_name: str = "documents"
    vector_size: int = Field(default=1024, ge=1)

    @field_validator("vector_size")
    @classmethod
    def validate_vector_size(cls, v: int) -> int:
        """验证向量维度与模型匹配"""
        valid_sizes = [768, 1024, 1536]  # bge-m3=1024, bge-large=1024, openai=1536
        if v not in valid_sizes:
            raise ValueError(f"vector_size must be one of {valid_sizes}")
        return v


class KeywordStoreConfig(BaseSettings):
    """关键词存储配置"""

    model_config = SettingsConfigDict(extra="forbid")

    type: Literal["elasticsearch", "meilisearch", "memory"] = "elasticsearch"
    hosts: List[str] = ["http://localhost:9200"]
    index_name: str = "documents"


class GraphStoreConfig(BaseSettings):
    """图存储配置"""

    model_config = SettingsConfigDict(extra="forbid")

    type: Literal["neo4j", "memory"] = "neo4j"
    uri: str = "bolt://localhost:7687"
    username: str = "neo4j"
    password: SecretStr = SecretStr("password")
    database: str = "neo4j"

    @field_validator("uri")
    @classmethod
    def validate_uri(cls, v: str) -> str:
        """验证URI格式"""
        if not v.startswith(("bolt://", "neo4j://")):
            raise ValueError("URI must start with bolt:// or neo4j://")
        return v


class EmbeddingModelConfig(BaseSettings):
    """Embedding模型配置"""

    model_config = SettingsConfigDict(extra="forbid")

    name: str = "BAAI/bge-m3"
    device: Literal["cpu", "cuda", "mps"] = "cpu"
    batch_size: int = Field(default=32, ge=1, le=256)
    normalize_embeddings: bool = True


class RerankModelConfig(BaseSettings):
    """Rerank模型配置"""

    model_config = SettingsConfigDict(extra="forbid")

    name: str = "BAAI/bge-reranker-large"
    device: Literal["cpu", "cuda", "mps"] = "cpu"
    batch_size: int = Field(default=8, ge=1, le=64)
    max_length: int = Field(default=512, ge=128, le=2048)


class ModelsConfig(BaseSettings):
    """模型配置集合"""

    model_config = SettingsConfigDict(extra="forbid")

    embedding: EmbeddingModelConfig = Field(default_factory=EmbeddingModelConfig)
    rerank: RerankModelConfig = Field(default_factory=RerankModelConfig)


class RetrievalConfig(BaseSettings):
    """召回配置"""

    model_config = SettingsConfigDict(extra="forbid")

    vector_top_k: int = Field(default=30, ge=1, le=100)
    keyword_top_k: int = Field(default=20, ge=1, le=100)
    graph_top_k: int = Field(default=10, ge=1, le=50)
    score_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    enable_rerank: bool = True
    enable_fusion: bool = True


class FusionWeightsConfig(BaseSettings):
    """分数融合权重配置"""

    model_config = SettingsConfigDict(extra="forbid")

    rerank: float = Field(default=0.4, ge=0.0, le=1.0)
    vector: float = Field(default=0.3, ge=0.0, le=1.0)
    keyword: float = Field(default=0.2, ge=0.0, le=1.0)
    graph: float = Field(default=0.05, ge=0.0, le=1.0)
    time: float = Field(default=0.05, ge=0.0, le=1.0)

    @field_validator("rerank", "vector", "keyword", "graph", "time")
    @classmethod
    def validate_weights(cls, v: float) -> float:
        """验证权重在合理范围"""
        return round(v, 2)  # 保留两位小数


class ContextConfig(BaseSettings):
    """上下文增强配置"""

    model_config = SettingsConfigDict(extra="forbid")

    max_length: int = Field(default=2000, ge=100, le=10000)
    surrounding_window: int = Field(default=2, ge=0, le=10)
    strategy: Literal["none", "surrounding", "section", "hierarchy", "entity_link", "full"] = (
        "surrounding"
    )


class LoggingConfig(BaseSettings):
    """日志配置"""

    model_config = SettingsConfigDict(extra="forbid")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    format: Literal["json", "text"] = "json"
    output: Literal["stdout", "file"] = "stdout"


class MetricsConfig(BaseSettings):
    """监控指标配置"""

    model_config = SettingsConfigDict(extra="forbid")

    enabled: bool = True
    port: int = Field(default=9090, ge=1, le=65535)


class CacheConfig(BaseSettings):
    """缓存配置"""

    model_config = SettingsConfigDict(extra="forbid")

    type: Literal["redis", "memory"] = "redis"
    host: str = "localhost"
    port: int = Field(default=6379, ge=1, le=65535)
    db: int = Field(default=0, ge=0, le=15)
    ttl: int = Field(default=3600, ge=60)


class AppConfig(BaseSettings):
    """
    应用主配置

    使用 Pydantic Settings 实现类型安全的配置管理
    支持 YAML 文件加载和环境变量覆盖
    """

    model_config = SettingsConfigDict(
        env_nested_delimiter="__",  # 环境变量语法: APP_VECTOR_STORE__HOST=xxx
        extra="forbid",  # 禁止额外字段，防止AI写错配置
        validate_assignment=True,  # 赋值时验证
    )

    # 基础配置
    env: Literal["dev", "staging", "production"] = "dev"
    debug: bool = False

    # 子配置
    server: ServerConfig = Field(default_factory=ServerConfig)
    vector_store: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    keyword_store: KeywordStoreConfig = Field(default_factory=KeywordStoreConfig)
    graph_store: GraphStoreConfig = Field(default_factory=GraphStoreConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    fusion_weights: FusionWeightsConfig = Field(default_factory=FusionWeightsConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)

    @field_validator("debug")
    @classmethod
    def validate_debug_in_prod(cls, v: bool, info) -> bool:
        """生产环境强制关闭debug"""
        if info.data.get("env") == "production" and v:
            raise ValueError("Production environment must have debug=False")
        return v

    @classmethod
    def from_yaml(cls, path: Path = Path("config.yaml")) -> "AppConfig":
        """
        从YAML文件加载配置

        Args:
            path: 配置文件路径

        Returns:
            AppConfig实例

        Raises:
            FileNotFoundError: 配置文件不存在
            ValidationError: 配置验证失败
        """
        if not path.exists():
            raise FileNotFoundError(f"配置文件 {path} 不存在! 请检查文件路径或创建默认配置文件")

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise ValueError(f"配置文件 {path} 格式错误: 必须是YAML对象")

        # 传入环境上下文给校验器
        return cls.model_validate(data, context={"env": data.get("env", "dev")})

    def to_yaml(self, path: Path = Path("config.yaml")) -> None:
        """
        保存配置到YAML文件

        Args:
            path: 输出文件路径
        """
        data = self.model_dump()

        # 处理SecretStr
        def process_secrets(obj):
            if isinstance(obj, dict):
                return {k: process_secrets(v) for k, v in obj.items()}
            elif isinstance(obj, SecretStr):
                return obj.get_secret_value()
            elif isinstance(obj, list):
                return [process_secrets(item) for item in obj]
            return obj

        data = process_secrets(data)

        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)


# 全局配置实例
_config: AppConfig | None = None


def get_config() -> AppConfig:
    """
    获取全局配置实例（单例模式）

    Returns:
        AppConfig实例
    """
    global _config
    if _config is None:
        _config = AppConfig.from_yaml()
    return _config


def reload_config(path: Path = Path("config.yaml")) -> AppConfig:
    """
    重新加载配置

    Args:
        path: 配置文件路径

    Returns:
        新的AppConfig实例
    """
    global _config
    _config = AppConfig.from_yaml(path)
    return _config


def init_config(path: Path = Path("config.yaml")) -> AppConfig:
    """
    初始化配置（如果不存在则创建默认配置）

    Args:
        path: 配置文件路径

    Returns:
        AppConfig实例
    """
    if not path.exists():
        # 创建默认配置
        config = AppConfig()
        config.to_yaml(path)
        print(f"已创建默认配置文件: {path}")

    return AppConfig.from_yaml(path)


if __name__ == "__main__":
    # 测试配置加载
    print("=" * 60)
    print("配置管理测试")
    print("=" * 60)

    # 创建默认配置
    config = AppConfig()
    print(f"\n默认配置:")
    print(f"  环境: {config.env}")
    print(f"  Debug: {config.debug}")
    print(
        f"  向量存储: {config.vector_store.type} ({config.vector_store.host}:{config.vector_store.port})"
    )
    print(f"  Embedding模型: {config.models.embedding.name}")
    print(f"  Rerank模型: {config.models.rerank.name}")

    # 保存到文件
    config.to_yaml("/tmp/test_config.yaml")
    print(f"\n已保存到: /tmp/test_config.yaml")

    # 从文件加载
    loaded = AppConfig.from_yaml(Path("/tmp/test_config.yaml"))
    print(f"\n加载验证: {'成功' if loaded.env == config.env else '失败'}")

    print("\n" + "=" * 60)
    print("配置管理测试完成!")
    print("=" * 60)
