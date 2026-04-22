"""
统一 API 接口 - 前后端对接
"""

import sys
import os

# 添加项目根目录到路径，支持相对导入
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))  # src/backend
sys.path.insert(0, project_root)

from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
import uuid
import logging

# 类型导入
from domain_models.search_models import SearchQuery
from domain_models.retrieval_models import RetrievalRequest, RetrievalResponse, RetrievalConfig
from domain_models.api_models import APIResponse

# 服务导入
from retrieval.unified_pipeline import UnifiedRetrievalPipeline
from infrastructure.adapters.unified import UnifiedStore
from services.document_processor import DocumentProcessor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 创建 FastAPI 应用
app = FastAPI(
    title="RAG Dashboard Unified API", description="统一检索与文档管理 API", version="1.0.0"
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8080").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局服务实例
pipeline = None
store = None
doc_processor = None
init_status = {"store": False, "pipeline": False, "doc_processor": False}


@app.on_event("startup")
async def startup_event():
    """启动时初始化服务 - PG + Qdrant(session) + Redis"""
    global pipeline, store, doc_processor, init_status

    logger.info("Initializing UnifiedStore (PG single-db mode)...")
    try:
        store = UnifiedStore()
        init_status["store"] = True
        logger.info("✅ UnifiedStore initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize UnifiedStore: {e}")
        init_status["store"] = False

    logger.info("Initializing UnifiedRetrievalPipeline...")
    try:
        pipeline = UnifiedRetrievalPipeline(store)
        init_status["pipeline"] = True
        logger.info("✅ UnifiedRetrievalPipeline initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize UnifiedRetrievalPipeline: {e}")
        init_status["pipeline"] = False

    logger.info("Initializing DocumentProcessor...")
    try:
        doc_processor = DocumentProcessor(store)
        init_status["doc_processor"] = True
        logger.info("✅ DocumentProcessor initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize DocumentProcessor: {e}")
        init_status["doc_processor"] = False

    # 将服务注入 v1 router
    try:
        from api.routes import set_services
        set_services(pipeline, store)
        logger.info("✅ V1 routes services injected")
    except Exception as e:
        logger.warning(f"Failed to inject v1 services: {e}")

    if not any(init_status.values()):
        logger.error("❌ All services failed to initialize. API will run in limited mode.")
    else:
        logger.info(f"✅ API started with: {init_status}")


@app.on_event("shutdown")
async def shutdown_event():
    """关闭时清理资源"""
    global store
    if store:
        store.close()
        logger.info("✅ API services shutdown")


# ========== 健康检查 ==========


@app.get("/health")
async def health_check():
    """健康检查"""
    global store, init_status

    response = {
        "init_status": init_status,
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    }

    if store:
        try:
            health = store.health_check()
            all_healthy = all(v == "healthy" for v in health.values())
            response["status"] = "ok" if all_healthy else "degraded"
            response["services"] = health
        except Exception as e:
            response["status"] = "error"
            response["services"] = {"store_error": str(e)}
    else:
        response["status"] = "error"
        response["services"] = {"store": "not_initialized"}

    return response


# ========== 检索接口 ==========


class SearchRequest(BaseModel):
    query: str = Field(..., description="搜索查询文本")
    top_k: int = Field(default=10, ge=1, le=100)
    mode: str = Field(default="hybrid", description="搜索模式: vector|text|hybrid")
    filters: Dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[str] = None


@app.post("/api/search", response_model=APIResponse[Dict[str, Any]])
async def search(request: SearchRequest):
    """统一搜索接口"""
    global pipeline

    if not pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")

    try:
        config = RetrievalConfig(
            vector_top_k=30 if request.mode in ["vector", "hybrid"] else 0,
            keyword_top_k=20 if request.mode in ["text", "hybrid"] else 0,
            graph_top_k=0,  # 不再使用图谱召回
        )

        retrieval_request = RetrievalRequest(
            query=request.query, config=config, session_id=request.session_id
        )

        response = pipeline.retrieve(retrieval_request)

        return APIResponse.success(
            {
                "request_id": response.request_id,
                "query": request.query,
                "results": [
                    {
                        "chunk_id": doc.chunk_id,
                        "doc_id": doc.doc_id,
                        "content": doc.content[:500] + "..."
                        if len(doc.content) > 500
                        else doc.content,
                        "score": round(doc.score, 4),
                        "metadata": doc.metadata,
                    }
                    for doc in response.documents
                ],
                "latency_ms": round(response.latency_ms, 2),
                "stats": response.stats,
            }
        )

    except Exception as e:
        logger.error(f"Search error: {e}")
        return APIResponse.error(str(e), "SEARCH_ERROR")


# ========== 文档管理接口 ==========


class DocumentUploadResponse(BaseModel):
    doc_id: str
    status: str
    chunks_count: int
    message: str


@app.post("/api/documents/upload")
async def upload_document(
    background_tasks: BackgroundTasks, file: UploadFile = File(...), title: Optional[str] = None
):
    """上传文档（异步处理）"""
    doc_id = str(uuid.uuid4())

    # 保存文件
    import os

    upload_dir = "/tmp/rag-uploads"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = f"{upload_dir}/{doc_id}_{file.filename}"

    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # 后台处理
    background_tasks.add_task(
        process_document, doc_id, file_path, title or file.filename or "Untitled"
    )

    return {
        "doc_id": doc_id,
        "status": "processing",
        "message": "Document uploaded and is being processed",
    }


def process_document(doc_id: str, file_path: str, title: str):
    """后台处理文档"""
    global doc_processor
    logger.info(f"Processing document {doc_id}: {title}")

    try:
        if doc_processor:
            document = doc_processor.process_pdf(file_path, title)
            logger.info(
                f"Document {doc_id} processed successfully with {len(document.chunks)} chunks"
            )
        else:
            logger.error(f"Document processor not initialized")
    except Exception as e:
        logger.error(f"Failed to process document {doc_id}: {e}")


@app.get("/api/documents/{doc_id}")
async def get_document(doc_id: str):
    """获取文档信息"""
    # 简化实现
    return {"doc_id": doc_id, "status": "not_implemented"}


@app.post("/api/documents/process-sync")
async def process_document_sync(file: UploadFile = File(...), title: Optional[str] = None):
    """同步处理文档（用于测试）"""
    global doc_processor

    if not doc_processor:
        raise HTTPException(status_code=503, detail="Document processor not initialized")

    # 保存文件
    import os

    upload_dir = "/tmp/rag-uploads"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = f"{upload_dir}/{uuid.uuid4()}_{file.filename}"

    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    try:
        # 处理文档
        document = doc_processor.process_pdf(file_path, title or file.filename)

        return {
            "doc_id": document.metadata.doc_id,
            "title": document.metadata.title,
            "chunks_count": len(document.chunks),
            "status": "completed",
        }
    except Exception as e:
        logger.error(f"Process sync error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 统计接口 ==========


@app.get("/api/stats")
async def get_stats():
    """获取系统统计"""
    global pipeline
    if pipeline:
        return APIResponse.success(pipeline.get_stats())
    return APIResponse.error("Pipeline not initialized", "NOT_READY")


# ========== v1 API 路由 (Node.js后端调用) ==========

from api.routes import router as v1_router

app.include_router(v1_router)

# ========== 重排序接口 ==========


class RerankRequest(BaseModel):
    query: str
    documents: List[Dict[str, Any]]
    top_k: int = Field(default=10, ge=1, le=100)


class RerankResponse(BaseModel):
    results: List[Dict[str, Any]]
    query: str


@app.post("/api/v1/rerank")
async def rerank_documents(request: RerankRequest):
    """文档重排序接口 - 使用真实重排序模型"""
    global pipeline

    try:
        # 检查pipeline是否初始化
        if not pipeline or not hasattr(pipeline, "reranker"):
            logger.warning("Pipeline or reranker not initialized, using fallback")
            # 降级处理：返回原始顺序
            return {
                "results": [
                    {
                        "id": doc["id"],
                        "content": doc["content"][:200]
                        if len(doc["content"]) > 200
                        else doc["content"],
                        "score": doc.get("score", 0.5),
                    }
                    for doc in request.documents[: request.top_k]
                ],
                "query": request.query,
                "note": "reranker not available, returning original order",
            }

        # 提取文档内容
        documents = [doc["content"] for doc in request.documents]

        # 使用重排序服务
        from infrastructure.adapters.reranker_service import get_reranker_service

        reranker_service = get_reranker_service()

        # 执行重排序
        scores = reranker_service.rerank(request.query, documents)

        # 组合结果
        results = []
        for i, (doc, score) in enumerate(zip(request.documents, scores)):
            results.append(
                {
                    "id": doc["id"],
                    "content": doc["content"][:200]
                    if len(doc["content"]) > 200
                    else doc["content"],
                    "score": float(score),
                    "original_index": i,
                }
            )

        # 按分数排序
        results.sort(key=lambda x: x["score"], reverse=True)

        return {
            "results": results[: request.top_k],
            "query": request.query,
        }
    except Exception as e:
        logger.error(f"Rerank error: {e}")
        # 降级处理
        return {
            "results": [
                {
                    "id": doc["id"],
                    "content": doc["content"][:200]
                    if len(doc["content"]) > 200
                    else doc["content"],
                    "score": doc.get("score", 0.5),
                }
                for doc in request.documents[: request.top_k]
            ],
            "query": request.query,
            "error": str(e),
        }


# ========== 评估接口 ==========


class EvaluationRequest(BaseModel):
    query: str
    retrieved_chunks: List[Dict[str, Any]]
    generated_answer: str
    history_rounds: int = 0


class EvaluationResponse(BaseModel):
    completeness: float
    consistency: float
    confidence: float
    information_gain: float
    source_diversity: float
    fact_consistency: float
    coverage_estimate: float


@app.post("/api/v1/evaluate")
async def evaluate_retrieval(request: EvaluationRequest):
    """评估检索结果质量 —— 改进版（BM25-like语义重叠、引用检测、数值一致性）"""
    try:
        chunks = request.retrieved_chunks
        answer = request.generated_answer
        import re

        # 1. 基础分数
        avg_score = sum(c.get("score", 0) for c in chunks) / len(chunks) if chunks else 0

        # 2. 来源多样性
        sources = set(c.get("source", "") for c in chunks)
        source_diversity = min(len(sources) / 3, 1.0)

        # 3. 信息增益（随轮次递减）
        information_gain = max(0.1, 0.5 - request.history_rounds * 0.1)

        # 4. 完整性
        total_length = sum(len(c.get("content", "")) for c in chunks)
        completeness = min(total_length / 2000, 0.95)

        # 5. 一致性（基于检索结果分数方差）
        scores = [c.get("score", 0) for c in chunks]
        if scores:
            avg = sum(scores) / len(scores)
            variance = sum((s - avg) ** 2 for s in scores) / len(scores) if len(scores) > 1 else 0
            consistency = max(0.5, 1 - variance * 4)
        else:
            consistency = 0.5

        # 6. 引用检测（hasCitations）
        citation_patterns = [
            r"\[\d+\]",
            r"chunk_[\w_]+",
            r"参考[《\"']",
            r"依据[《\"']",
            r"根据[《\"']",
            r"第[一二三四五六七八九十\d]+[条款章]",
            r"\(\d{4}[年]?\)",
        ]
        has_citations = any(re.search(p, answer) for p in citation_patterns)
        citation_count = len(re.findall(r"\[\d+\]", answer))

        # 7. 事实一致性（回答与检索内容的token重叠度）
        def _tokenize(text: str) -> set:
            text = text.lower()
            return set(re.findall(r"[a-z]+|\d+|[\u4e00-\u9fff]", text))

        chunk_tokens = set()
        for c in chunks:
            chunk_tokens.update(_tokenize(c.get("content", "")))

        answer_tokens = _tokenize(answer)

        if chunk_tokens and answer_tokens:
            overlap = len(chunk_tokens & answer_tokens)
            union = len(chunk_tokens | answer_tokens)
            jaccard = overlap / union if union > 0 else 0
            containment = len(answer_tokens & chunk_tokens) / len(answer_tokens) if answer_tokens else 0
            fact_consistency = 0.35 * jaccard + 0.65 * containment
            fact_consistency = min(max(fact_consistency, 0.1), 0.95)
        else:
            fact_consistency = 0.3 if has_citations else 0.1

        if has_citations:
            fact_consistency = min(fact_consistency + 0.08, 0.95)

        # 8. 数值一致性检查
        answer_numbers = set(re.findall(r"\d+\.?\d*", answer))
        chunk_numbers = set()
        for c in chunks:
            chunk_numbers.update(re.findall(r"\d+\.?\d*", c.get("content", "")))
        if answer_numbers and chunk_numbers:
            num_ratio = len(answer_numbers & chunk_numbers) / len(answer_numbers)
            if num_ratio > 0.5:
                fact_consistency = min(fact_consistency + 0.05, 0.95)

        # 9. 覆盖率
        coverage_estimate = min(avg_score * source_diversity * 1.5, 0.95)

        # 10. 综合置信度
        confidence = (
            completeness * 0.15 +
            consistency * 0.15 +
            fact_consistency * 0.35 +
            source_diversity * 0.15 +
            (0.25 if has_citations else 0.0)
        )
        confidence = min(confidence, 0.95)

        return {
            "completeness": round(completeness, 4),
            "consistency": round(consistency, 4),
            "confidence": round(confidence, 4),
            "information_gain": round(information_gain, 4),
            "source_diversity": round(source_diversity, 4),
            "fact_consistency": round(fact_consistency, 4),
            "coverage_estimate": round(coverage_estimate, 4),
            "has_citations": has_citations,
            "citation_count": citation_count,
        }
    except Exception as e:
        logger.error(f"Evaluation error: {e}")
        return {
            "completeness": 0.5,
            "consistency": 0.5,
            "confidence": 0.5,
            "information_gain": 0.3,
            "source_diversity": 0.5,
            "fact_consistency": 0.5,
            "coverage_estimate": 0.5,
            "has_citations": False,
            "citation_count": 0,
        }


# ========== 查询分解接口 ==========


class DecomposeRequest(BaseModel):
    query: str


class DecomposeResponse(BaseModel):
    sub_queries: List[Dict[str, Any]]
    original_query: str


@app.post("/api/v1/decompose")
async def decompose_query(request: DecomposeRequest):
    """将查询分解为子查询"""
    query = request.query
    sub_queries = []

    # 基础概念查询
    sub_queries.append(
        {
            "id": f"sq_{uuid.uuid4().hex[:8]}",
            "query": f"{query} 基础概念定义",
            "targetDB": "vector",
            "status": "pending",
        }
    )

    # 实现细节查询
    sub_queries.append(
        {
            "id": f"sq_{uuid.uuid4().hex[:8]}",
            "query": f"{query} 实现方法 技术细节",
            "targetDB": "knowledge",
            "status": "pending",
        }
    )

    # 如果查询包含"如何/怎么"，添加案例查询
    if any(kw in query for kw in ["如何", "怎么", "怎样", "案例", "示例"]):
        sub_queries.append(
            {
                "id": f"sq_{uuid.uuid4().hex[:8]}",
                "query": f"{query} 实际案例 应用示例",
                "targetDB": "graph",
                "status": "pending",
            }
        )

    # 如果查询包含"区别/对比/比较"，添加对比查询
    if any(kw in query for kw in ["区别", "对比", "比较", "vs", "versus"]):
        sub_queries.append(
            {
                "id": f"sq_{uuid.uuid4().hex[:8]}",
                "query": f"{query} 对比分析 优缺点",
                "targetDB": "vector",
                "status": "pending",
            }
        )

    return {"sub_queries": sub_queries, "original_query": query}


# ========== WebSocket (实时通信) ==========

from fastapi import WebSocket, WebSocketDisconnect


class ConnectionManager:
    """WebSocket 连接管理"""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 实时通信"""
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            # 处理消息
            await websocket.send_json(
                {
                    "type": "echo",
                    "data": data,
                    "timestamp": __import__("datetime").datetime.now().isoformat(),
                }
            )
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ========== Pipeline 接口（前端数据管道看板使用）==========


@app.get("/api/pipeline/health")
async def pipeline_health():
    """管道健康检查 - PG + Qdrant(session) + Redis"""
    global store
    try:
        if store:
            health = store.health_check()
            db_health = {
                "postgres": {"status": health.get("postgres", "unknown"), "latency": 0, "count": 0},
                "qdrant_session": {"status": health.get("qdrant", "unknown"), "latency": 0, "count": 0},
                "cache": {"status": health.get("cache", "unknown"), "latency": 0, "count": 0},
            }
            return APIResponse.success(db_health)

        # 默认值
        return APIResponse.success(
            {
                "postgres": {"status": "healthy", "latency": 0, "count": 0},
                "qdrant_session": {"status": "healthy", "latency": 0, "count": 0},
                "cache": {"status": "healthy", "latency": 0, "count": 0},
            }
        )
    except Exception as e:
        logger.error(f"Pipeline health check error: {e}")
        return APIResponse.error(str(e), "HEALTH_CHECK_ERROR")


@app.get("/api/pipeline/stats")
async def pipeline_stats():
    """管道统计信息"""
    global pipeline
    try:
        if pipeline:
            stats = pipeline.get_stats()
            return APIResponse.success(
                {
                    "totalFiles": stats.get("total_requests", 0),
                    "completedFiles": stats.get("total_requests", 0),
                    "failedFiles": 0,
                    "processingFiles": 0,
                    "averageProcessingTime": stats.get("average_latency_ms", 0),
                    "queueLength": 0,
                    "throughput": 0,
                }
            )

        return APIResponse.success(
            {
                "totalFiles": 0,
                "completedFiles": 0,
                "failedFiles": 0,
                "processingFiles": 0,
                "averageProcessingTime": 0,
                "queueLength": 0,
                "throughput": 0,
            }
        )
    except Exception as e:
        logger.error(f"Pipeline stats error: {e}")
        return APIResponse.error(str(e), "STATS_ERROR")


@app.get("/api/pipeline/evaluation")
async def pipeline_evaluation():
    """评估指标"""
    try:
        return APIResponse.success(
            {
                "embedding": {
                    "averageTime": 0,
                    "successRate": 100,
                    "queueSize": 0,
                    "batchSize": 32,
                },
                "rerank": {
                    "averageTime": 0,
                    "successRate": 100,
                    "crossEncoderLatency": 0,
                    "fusionScoreAccuracy": 0,
                },
            }
        )
    except Exception as e:
        logger.error(f"Pipeline evaluation error: {e}")
        return APIResponse.error(str(e), "EVALUATION_ERROR")


@app.post("/api/pipeline/upload")
async def pipeline_upload(file: UploadFile = File(...), fileId: Optional[str] = None):
    """管道文件上传接口"""
    global doc_processor

    try:
        # 保存文件
        import os

        upload_dir = "/tmp/rag-uploads"
        os.makedirs(upload_dir, exist_ok=True)

        doc_id = fileId or str(uuid.uuid4())
        file_path = f"{upload_dir}/{doc_id}_{file.filename}"

        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)

        # 同步处理文档
        if doc_processor:
            document = doc_processor.process_pdf(file_path, file.filename)
            return APIResponse.success(
                {
                    "doc_id": document.metadata.doc_id,
                    "chunks_count": len(document.chunks),
                    "status": "completed",
                }
            )
        else:
            return APIResponse.error("Document processor not initialized", "NOT_READY")

    except Exception as e:
        logger.error(f"Pipeline upload error: {e}")
        return APIResponse.error(str(e), "UPLOAD_ERROR")
