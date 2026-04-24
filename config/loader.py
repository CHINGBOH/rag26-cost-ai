"""
统一配置加载器
整合 Pydantic Settings + YAML + .env + 环境变量
提供类型安全、热重载、层级覆盖的配置管理
"""

import sys
import yaml
from pathlib import Path
from typing import Any, Dict, Optional, TypeVar
from pydantic import Field, field_validator, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# 将项目根目录加入路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


T = TypeVar("T", bound="BaseSettings")


class ServerConfig(BaseSettings):
    """服务器配置"""
    model_config = SettingsConfigDict(extra="forbid")
    
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    workers: int = Field(default=1, ge=1)
    reload: bool = False
    cors_origins: list = Field(default_factory=lambda: ["http://localhost:3000"])


class VectorStoreConfig(BaseSettings):
    """向量存储配置"""
    model_config = SettingsConfigDict(extra="forbid")
    
    type: str = "qdrant"
    host: str = "localhost"
    port: int = Field(default=6333, ge=1, le=65535)
    collection_name: str = "documents"
    vector_size: int = Field(default=1024, ge=1)
    timeout: int = 30
    pool_size: int = 10


class KeywordStoreConfig(BaseSettings):
    """关键词存储配置"""
    model_config = SettingsConfigDict(extra="forbid")
    
    type: str = "elasticsearch"
    hosts: list = Field(default_factory=lambda: ["http://localhost:9200"])
    index_name: str = "documents"
    username: Optional[str] = None
    password: SecretStr = SecretStr("")


class GraphStoreConfig(BaseSettings):
    """图存储配置"""
    model_config = SettingsConfigDict(extra="forbid")
    
    type: str = "neo4j"
    uri: str = "bolt://localhost:7687"
    username: str = "neo4j"
    password: SecretStr = SecretStr("password")
    database: str = "neo4j"


class StructuredStoreConfig(BaseSettings):
    """结构化存储配置 (PostgreSQL)"""
    model_config = SettingsConfigDict(extra="forbid")
    
    type: str = "postgresql"
    host: str = "localhost"
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = "rag_db"
    username: str = "rag_user"
    password: SecretStr = SecretStr("")
    table_formats: list = Field(default_factory=lambda: ["json", "markdown", "csv"])


class EmbeddingModelConfig(BaseSettings):
    """Embedding模型配置"""
    model_config = SettingsConfigDict(extra="forbid")
    
    name: str = "BAAI/bge-m3"
    device: str = "cpu"
    batch_size: int = Field(default=32, ge=1, le=256)
    normalize_embeddings: bool = True


class RerankModelConfig(BaseSettings):
    """Rerank模型配置"""
    model_config = SettingsConfigDict(extra="forbid")
    
    name: str = "BAAI/bge-reranker-v2-m3"
    device: str = "cpu"
    batch_size: int = Field(default=8, ge=1, le=64)
    max_length: int = Field(default=512, ge=128, le=2048)


class LLMConfig(BaseSettings):
    """LLM配置"""
    model_config = SettingsConfigDict(extra="forbid")
    
    provider: str = "kimi"  # openai | claude | kimi | ollama | custom
    api_key: SecretStr = SecretStr("")
    base_url: str = "https://api.kimi.com/coding/v1"
    model: str = "kimi-for-coding"
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2000, ge=1, le=8000)


class OCRQualityConfig(BaseSettings):
    """OCR质量配置"""
    model_config = SettingsConfigDict(extra="forbid")
    
    confidence_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    table_integrity_threshold: float = Field(default=0.90, ge=0.0, le=1.0)
    layout_consistency_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    max_retries: int = Field(default=3, ge=1, le=5)
    enable_llm_verify: bool = True
    retry_strategies: list = Field(default_factory=lambda: [
        "increase_contrast",
        "deskew_correction",
        "enhance_table_detection"
    ])


class QueryAnalysisConfig(BaseSettings):
    """查询分析配置"""
    model_config = SettingsConfigDict(extra="forbid")
    
    enable_intent_classification: bool = True
    enable_entity_extraction: bool = True
    enable_subquery_decomposition: bool = True
    max_subqueries: int = Field(default=5, ge=1, le=10)
    
    class IntentThresholds(BaseSettings):
        trend: float = 0.7
        comparison: float = 0.7
        numeric: float = 0.6
        list: float = 0.6
        procedure: float = 0.6
    
    intent_thresholds: IntentThresholds = Field(default_factory=IntentThresholds)


class ServiceConfig(BaseSettings):
    """服务开关配置"""
    model_config = SettingsConfigDict(extra="forbid")
    
    enabled: bool = True
    port: int = Field(default=8000, ge=1, le=65535)
    gpu: bool = False
    language: str = "ch"
    detect_tables: bool = True
    detect_figures: bool = False
    websocket: bool = False
    max_depth: int = Field(default=3, ge=1, le=10)
    timeout_seconds: int = Field(default=300, ge=30)
    cors_origins: list = Field(default_factory=lambda: ["http://localhost:3000"])


class ServicesConfig(BaseSettings):
    """服务配置集合"""
    model_config = SettingsConfigDict(extra="forbid")
    
    api: ServiceConfig = Field(default_factory=lambda: ServiceConfig(enabled=True, port=8000))
    ocr: ServiceConfig = Field(default_factory=lambda: ServiceConfig(enabled=True, port=8001, detect_tables=True))
    recursion: ServiceConfig = Field(default_factory=lambda: ServiceConfig(enabled=False, port=3001, websocket=True))


class RetrievalConfig(BaseSettings):
    """检索配置"""
    model_config = SettingsConfigDict(extra="forbid")
    
    vector_top_k: int = Field(default=30, ge=1, le=100)
    keyword_top_k: int = Field(default=20, ge=1, le=100)
    graph_top_k: int = Field(default=10, ge=1, le=50)
    score_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    enable_rerank: bool = True
    rerank_top_k: int = Field(default=10, ge=1, le=50)
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
        return round(v, 2)


class ContextConfig(BaseSettings):
    """上下文增强配置"""
    model_config = SettingsConfigDict(extra="forbid")
    
    max_length: int = Field(default=2000, ge=100, le=10000)
    surrounding_window: int = Field(default=2, ge=0, le=10)
    strategy: str = "surrounding"
    enable_table_summary: bool = True


class MetricsConfig(BaseSettings):
    """监控指标配置"""
    model_config = SettingsConfigDict(extra="forbid")
    
    enabled: bool = True
    port: int = Field(default=9090, ge=1, le=65535)
    path: str = "/metrics"


class CacheConfig(BaseSettings):
    """缓存配置"""
    model_config = SettingsConfigDict(extra="forbid")
    
    type: str = "redis"
    host: str = "localhost"
    port: int = Field(default=6379, ge=1, le=65535)
    db: int = Field(default=0, ge=0, le=15)
    ttl: int = Field(default=3600, ge=60)
    max_connections: int = Field(default=50, ge=1)


class LoggingConfig(BaseSettings):
    """日志配置"""
    model_config = SettingsConfigDict(extra="forbid")
    
    level: str = "INFO"
    format: str = "json"  # json | text
    output: str = "stdout"  # stdout | file
    file_path: str = "logs/app.log"
    rotation: str = "daily"
    retention: int = 30


class RAGConfig(BaseSettings):
    """
    RAG Dashboard 主配置类
    
    加载优先级:
    1. 环境变量 (RAG__SECTION__KEY=value)
    2. .env 文件 (从 config/.env 加载)
    3. config.yaml 文件
    4. 代码默认值
    """
    
    model_config = SettingsConfigDict(
        env_prefix="RAG__",
        env_nested_delimiter="__",
        extra="forbid",
        validate_assignment=True,
    )
    
    # 基础配置
    env: str = "dev"  # dev | staging | production
    debug: bool = False
    
    # 子配置
    server: ServerConfig = Field(default_factory=ServerConfig)
    services: ServicesConfig = Field(default_factory=ServicesConfig)
    vector_store: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    keyword_store: KeywordStoreConfig = Field(default_factory=KeywordStoreConfig)
    graph_store: GraphStoreConfig = Field(default_factory=GraphStoreConfig)
    structured_store: StructuredStoreConfig = Field(default_factory=StructuredStoreConfig)
    models: Dict[str, Any] = Field(default_factory=lambda: {
        "embedding": EmbeddingModelConfig(),
        "rerank": RerankModelConfig(),
        "llm": LLMConfig()
    })
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    ocr_quality: OCRQualityConfig = Field(default_factory=OCRQualityConfig)
    query_analysis: QueryAnalysisConfig = Field(default_factory=QueryAnalysisConfig)
    fusion_weights: FusionWeightsConfig = Field(default_factory=FusionWeightsConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    
    @field_validator("debug")
    @classmethod
    def validate_debug_in_prod(cls, v: bool, info) -> bool:
        """生产环境强制关闭 debug"""
        if info.data.get("env") == "production" and v:
            raise ValueError("Production environment must have debug=False")
        return v
    
    @classmethod
    def from_yaml(cls, path: Optional[Path] = None) -> "RAGConfig":
        """
        从 YAML 文件加载配置
        
        Args:
            path: 配置文件路径，默认 config/config.yaml
        
        Returns:
            RAGConfig 实例
        """
        if path is None:
            path = PROJECT_ROOT / "config" / "config.yaml"
        
        if not path.exists():
            # 返回默认配置
            return cls()
        
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        if not isinstance(data, dict):
            raise ValueError(f"配置文件 {path} 格式错误: 必须是 YAML 对象")
        
        return cls.model_validate(data)
    
    def to_yaml(self, path: Optional[Path] = None) -> None:
        """
        保存配置到 YAML 文件
        
        Args:
            path: 输出文件路径
        """
        if path is None:
            path = PROJECT_ROOT / "config" / "config.yaml"
        
        # 确保目录存在
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # 序列化配置
        data = self.model_dump()
        
        # 处理 SecretStr
        def process_secrets(obj):
            if isinstance(obj, dict):
                return {k: process_secrets(v) for k, v in obj.items()}
            elif hasattr(obj, "get_secret_value"):
                return obj.get_secret_value()
            elif isinstance(obj, list):
                return [process_secrets(item) for item in obj]
            return obj
        
        data = process_secrets(data)
        
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    
    def get_service_url(self, service_name: str) -> str:
        """
        获取服务 URL
        
        Args:
            service_name: 服务名称 (api, ocr, recursion)
        
        Returns:
            服务 URL
        """
        service = getattr(self.services, service_name, None)
        if service is None:
            raise ValueError(f"Unknown service: {service_name}")
        return f"http://localhost:{service.port}"


# 全局配置实例 (单例)
_config: Optional[RAGConfig] = None


def get_config() -> RAGConfig:
    """
    获取全局配置实例 (懒加载)
    
    Returns:
        RAGConfig 实例
    """
    global _config
    if _config is None:
        _config = RAGConfig.from_yaml()
    return _config


def reload_config() -> RAGConfig:
    """
    重新加载配置 (热重载)
    
    Returns:
        新的 RAGConfig 实例
    """
    global _config
    _config = RAGConfig.from_yaml()
    return _config


def init_config(path: Optional[Path] = None) -> RAGConfig:
    """
    初始化配置，如果不存在则创建默认配置
    
    Args:
        path: 配置文件路径
    
    Returns:
        RAGConfig 实例
    """
    if path is None:
        path = PROJECT_ROOT / "config" / "config.yaml"
    
    if not path.exists():
        config = RAGConfig()
        config.to_yaml(path)
        print(f"✅ 已创建默认配置文件: {path}")
    
    return RAGConfig.from_yaml(path)


# 便捷导入
__all__ = [
    "RAGConfig",
    "get_config",
    "reload_config",
    "init_config",
    "ServerConfig",
    "VectorStoreConfig",
    "KeywordStoreConfig",
    "GraphStoreConfig",
    "StructuredStoreConfig",
    "OCRQualityConfig",
    "QueryAnalysisConfig",
    "RetrievalConfig",
]


if __name__ == "__main__":
    # 测试配置加载
    print("=" * 60)
    print("配置加载器测试")
    print("=" * 60)
    
    config = get_config()
    print("\n✅ 配置加载成功")
    print(f"   环境: {config.env}")
    print(f"   Debug: {config.debug}")
    print(f"   API服务: {config.services.api.port}")
    print(f"   OCR服务: {config.services.ocr.port}")
    print(f"   递归服务: {config.services.recursion.port}")
    print(f"\n   OCR质量阈值: {config.ocr_quality.confidence_threshold}")
    print(f"   最大重试次数: {config.ocr_quality.max_retries}")
    print(f"\n   检索向量top_k: {config.retrieval.vector_top_k}")
    print(f"   融合权重 - Rerank: {config.fusion_weights.rerank}")
    
    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)
