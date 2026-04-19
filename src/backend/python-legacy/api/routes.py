"""
API层 - FastAPI路由
实现RESTful API接口
"""

from fastapi import APIRouter, Depends, HTTPException, status
from dependency_injector.wiring import inject, Provide

from domain.models import (
    SearchRequest,
    SearchResponse,
    IndexRequest,
    IndexResponse,
    HealthResponse,
    StatsResponse,
)
from application.usecases import SearchUsecase, IndexUsecase
from container import Container


router = APIRouter(prefix="/api/v1", tags=["retrieval"])


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="搜索文档",
    description="执行多路召回 + 精排 + 分数融合的完整检索流程",
)
@inject
async def search(
    request: SearchRequest, usecase: SearchUsecase = Depends(Provide[Container.search_usecase])
):
    """
    搜索文档

    - **query**: 查询文本
    - **top_k**: 返回结果数量 (1-100)
    - **enable_rerank**: 是否启用精排
    - **enable_fusion**: 是否启用分数融合
    """
    result = await usecase.execute(request)

    if result.is_failure():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(result.failure())
        )

    return result.unwrap()


@router.post(
    "/index",
    response_model=IndexResponse,
    summary="索引文档",
    description="将文档索引到向量存储、关键词存储和知识图谱",
)
@inject
async def index(
    request: IndexRequest, usecase: IndexUsecase = Depends(Provide[Container.index_usecase])
):
    """
    索引文档

    - **doc_id**: 文档唯一标识
    - **title**: 文档标题
    - **chunks**: 文档片段列表
    - **build_graph**: 是否构建知识图谱
    """
    result = await usecase.execute(request)

    if result.is_failure():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(result.failure())
        )

    return result.unwrap()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="健康检查",
    description="检查服务及各组件健康状态",
)
async def health():
    """健康检查"""
    from datetime import datetime
    from container import get_container

    container = get_container()

    # 检查各服务状态
    services = {
        "vector_store": False,
        "keyword_store": False,
        "graph_store": False,
        "embedding_model": False,
        "rerank_model": False,
    }

    try:
        vector_store = container.vector_store()
        services["vector_store"] = vector_store.is_available()
    except Exception:
        pass

    try:
        keyword_store = container.keyword_store()
        services["keyword_store"] = keyword_store.is_available()
    except Exception:
        pass

    try:
        graph_store = container.graph_store()
        services["graph_store"] = graph_store.is_available()
    except Exception:
        pass

    try:
        embedding_model = container.embedding_model()
        services["embedding_model"] = True  # 已加载即可用
    except Exception:
        pass

    try:
        rerank_model = container.rerank_model()
        services["rerank_model"] = rerank_model.is_loaded()
    except Exception:
        pass

    return HealthResponse(
        status="healthy" if all(services.values()) else "degraded",
        version="0.1.0",
        timestamp=datetime.now(),
        services=services,
    )


@router.get(
    "/stats", response_model=StatsResponse, summary="统计信息", description="获取各存储的统计信息"
)
async def stats():
    """统计信息"""
    from container import get_container

    container = get_container()

    stats = StatsResponse()

    # 获取向量存储统计
    try:
        vector_store = container.vector_store()
        if vector_store.is_available():
            stats.vector_store = {"status": "connected"}
    except Exception as e:
        stats.vector_store = {"status": "error", "message": str(e)}

    # 获取关键词存储统计
    try:
        keyword_store = container.keyword_store()
        if keyword_store.is_available():
            stats.keyword_store = {"status": "connected"}
    except Exception as e:
        stats.keyword_store = {"status": "error", "message": str(e)}

    # 获取图存储统计
    try:
        graph_store = container.graph_store()
        if graph_store.is_available():
            stats.graph_store = {"status": "connected"}
    except Exception as e:
        stats.graph_store = {"status": "error", "message": str(e)}

    return stats
