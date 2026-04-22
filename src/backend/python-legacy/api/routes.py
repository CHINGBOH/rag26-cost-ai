"""
API层 - FastAPI路由 (v1)
直接调用 UnifiedStore / UnifiedRetrievalPipeline，不再依赖 DDD 层
"""

from fastapi import APIRouter, HTTPException, status
from typing import Dict, Any
from datetime import datetime

from domain_models.api_models import APIResponse
from domain_models.search_models import SearchQuery
from domain_models.retrieval_models import RetrievalRequest, RetrievalConfig

router = APIRouter(prefix="/api/v1", tags=["retrieval"])

# 全局服务实例由 unified_api.py 在启动时注入
pipeline = None
store = None


def set_services(pipeline_instance, store_instance):
    global pipeline, store
    pipeline = pipeline_instance
    store = store_instance


@router.post("/search", summary="搜索文档", description="执行 pgvector + tsvector 混合检索")
async def search(request: Dict[str, Any]):
    """搜索文档"""
    global pipeline

    if not pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")

    try:
        query = request.get("query", "")
        top_k = request.get("top_k", 10)
        mode = request.get("mode", "hybrid")
        session_id = request.get("session_id")
        filters = request.get("filters", {})

        config = RetrievalConfig(
            vector_top_k=30 if mode in ["vector", "hybrid"] else 0,
            keyword_top_k=20 if mode in ["text", "hybrid"] else 0,
            graph_top_k=0,
        )

        retrieval_request = RetrievalRequest(
            query=query, config=config, session_id=session_id, filters=filters
        )

        response = pipeline.retrieve(retrieval_request)

        return APIResponse.success(
            {
                "request_id": response.request_id,
                "query": query,
                "results": [
                    {
                        "chunk_id": doc.chunk_id,
                        "doc_id": doc.doc_id,
                        "content": doc.content[:500] + "..." if len(doc.content) > 500 else doc.content,
                        "score": round(doc.score, 4),
                        "metadata": doc.metadata,
                    }
                    for doc in response.documents[:top_k]
                ],
                "latency_ms": round(response.latency_ms, 2),
                "stats": response.stats,
            }
        )

    except Exception as e:
        return APIResponse.error(str(e), "SEARCH_ERROR")


@router.post("/index", summary="索引文档", description="将文档索引到 PostgreSQL")
async def index(request: Dict[str, Any]):
    """索引文档"""
    global store

    if not store:
        raise HTTPException(status_code=503, detail="Store not initialized")

    try:
        from domain_models.document_models import Document, DocumentMetadata, DocumentType

        doc = Document(
            metadata=DocumentMetadata(
                doc_id=request.get("doc_id", ""),
                title=request.get("title", "Untitled"),
                source=request.get("source", ""),
                doc_type=DocumentType.PDF,
            ),
            chunks=[],
        )

        result = store.index_document(doc)
        return APIResponse.success(result)

    except Exception as e:
        return APIResponse.error(str(e), "INDEX_ERROR")


@router.get("/health", summary="健康检查", description="检查 PG + Qdrant + Redis 健康状态")
async def health():
    """健康检查"""
    global store

    from datetime import datetime

    services = {
        "postgres": {"status": "unknown", "latency": 0},
        "qdrant": {"status": "unknown", "latency": 0},
        "cache": {"status": "unknown", "latency": 0},
    }

    if store:
        try:
            health = store.health_check()
            for key in services:
                if key in health:
                    services[key]["status"] = health[key]
        except Exception as e:
            services["error"] = str(e)

    all_healthy = all(v["status"] == "healthy" for v in services.values() if isinstance(v, dict))

    return {
        "status": "healthy" if all_healthy else "degraded",
        "version": "1.0.0-pg-single-db",
        "timestamp": datetime.now().isoformat(),
        "services": services,
    }


@router.get("/stats", summary="统计信息", description="获取存储统计信息")
async def stats():
    """统计信息"""
    global pipeline

    stats_data = {
        "postgres": {"status": "unknown"},
        "qdrant": {"status": "unknown"},
        "cache": {"status": "unknown"},
    }

    if pipeline:
        try:
            pipeline_stats = pipeline.get_stats()
            stats_data["total_requests"] = pipeline_stats.get("total_requests", 0)
            stats_data["average_latency_ms"] = pipeline_stats.get("average_latency_ms", 0)
            if "store_health" in pipeline_stats:
                for key in stats_data:
                    if key in pipeline_stats["store_health"]:
                        stats_data[key]["status"] = pipeline_stats["store_health"][key]
        except Exception as e:
            stats_data["error"] = str(e)

    return stats_data
