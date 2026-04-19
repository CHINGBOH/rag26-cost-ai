"""
依赖注入容器
使用 dependency-injector 实现 IoC 容器
"""

from dependency_injector import containers, providers

from config.settings import AppConfig, get_config
from domain.ports import (
    VectorStorePort,
    KeywordStorePort,
    GraphStorePort,
    EmbeddingModelPort,
    RerankModelPort,
    CachePort,
)
from application.usecases import SearchUsecase, IndexUsecase
from infrastructure.adapters.vector_store import QdrantVectorStoreAdapter, MemoryVectorStoreAdapter
from infrastructure.adapters.keyword_store import (
    ElasticsearchKeywordStoreAdapter,
    MemoryKeywordStoreAdapter,
)
from infrastructure.adapters.graph_store import Neo4jGraphStoreAdapter, MemoryGraphStoreAdapter
from infrastructure.adapters.ai_models import EmbeddingModelAdapter, RerankModelAdapter
from infrastructure.adapters.cache import MemoryCacheAdapter, RedisCacheAdapter


class Container(containers.DeclarativeContainer):
    """
    依赖注入容器

    集中管理所有依赖的创建和注入
    """

    # 配置
    config: providers.Singleton[AppConfig] = providers.Singleton(get_config)

    # ============ 基础设施层 ============

    # 向量存储
    vector_store: providers.Factory[VectorStorePort] = providers.Factory(
        lambda cfg: (
            QdrantVectorStoreAdapter(cfg.vector_store)
            if cfg.vector_store.type == "qdrant"
            else MemoryVectorStoreAdapter()
        ),
        config=config,
    )

    # 关键词存储
    keyword_store: providers.Factory[KeywordStorePort] = providers.Factory(
        lambda cfg: (
            ElasticsearchKeywordStoreAdapter(cfg.keyword_store)
            if cfg.keyword_store.type == "elasticsearch"
            else MemoryKeywordStoreAdapter()
        ),
        config=config,
    )

    # 图存储
    graph_store: providers.Factory[GraphStorePort] = providers.Factory(
        lambda cfg: (
            Neo4jGraphStoreAdapter(cfg.graph_store)
            if cfg.graph_store.type == "neo4j"
            else MemoryGraphStoreAdapter()
        ),
        config=config,
    )

    # 缓存适配器
    cache_adapter: providers.Factory[CachePort] = providers.Factory(
        lambda cfg: (
            RedisCacheAdapter(cfg.cache)
            if cfg.cache.type == "redis"
            else MemoryCacheAdapter(cfg.cache)
        ),
        config=config,
    )

    # Embedding模型
    embedding_model: providers.Singleton[EmbeddingModelPort] = providers.Singleton(
        EmbeddingModelAdapter, config=config.provided.models.embedding
    )

    # Rerank模型
    rerank_model: providers.Singleton[RerankModelPort] = providers.Singleton(
        RerankModelAdapter, config=config.provided.models.rerank
    )

    # ============ 应用层 ============

    # 搜索用例
    search_usecase: providers.Factory[SearchUsecase] = providers.Factory(
        SearchUsecase,
        vector_store=vector_store,
        keyword_store=keyword_store,
        graph_store=graph_store,
        embedding_model=embedding_model,
        rerank_model=rerank_model,
        cache=cache_adapter,
        fusion_weights=config.provided.fusion_weights,
    )

    # 索引用例
    index_usecase: providers.Factory[IndexUsecase] = providers.Factory(
        IndexUsecase,
        vector_store=vector_store,
        keyword_store=keyword_store,
        graph_store=graph_store,
        embedding_model=embedding_model,
    )


# 全局容器实例
_container: Container | None = None


def get_container() -> Container:
    """
    获取全局容器实例（单例模式）

    Returns:
        Container实例
    """
    global _container
    if _container is None:
        _container = Container()
    return _container


def init_container(config: AppConfig | None = None) -> Container:
    """
    初始化容器

    Args:
        config: 可选的配置对象

    Returns:
        Container实例
    """
    global _container
    _container = Container()

    if config:
        _container.config.override(providers.Singleton(lambda: config))

    return _container


# 快捷获取方法
def get_search_usecase() -> SearchUsecase:
    """获取搜索用例"""
    return get_container().search_usecase()


def get_index_usecase() -> IndexUsecase:
    """获取索引用例"""
    return get_container().index_usecase()
