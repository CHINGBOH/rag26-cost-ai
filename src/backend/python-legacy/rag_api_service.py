#!/usr/bin/env python3
"""
RAG系统FastAPI服务
整合所有服务：Embedding、四库、Rerank、LLM、高并发处理
提供完整的RAG系统API
"""

import os
import asyncio
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# 导入服务
from services.embedding_service import get_embedding_service, EmbeddingService
from services.four_database_service import get_four_db_service, FourDatabaseService
from services.rerank_service import get_rerank_service, RerankService
from services.llm_service import get_llm_service, UnifiedLLMService, Message
from services.model_caller import get_model_caller, UnifiedModelCaller, EmbeddingResult, RerankResult

# 配置
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", 8000))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# 日志配置
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 全局服务实例
embedding_service: Optional[EmbeddingService] = None
four_db_service: Optional[FourDatabaseService] = None
rerank_service: Optional[RerankService] = None
llm_service: Optional[UnifiedLLMService] = None
model_caller: Optional[UnifiedModelCaller] = None

# Pydantic模型
class QueryRequest(BaseModel):
    """查询请求"""
    query: str = Field(..., description="查询文本")
    top_k: int = Field(10, description="返回结果数量")
    filters: Optional[Dict[str, Any]] = Field(None, description="过滤条件")
    use_rerank: bool = Field(True, description="是否使用Rerank")
    use_llm: bool = Field(False, description="是否使用LLM生成答案")

class EmbeddingRequest(BaseModel):
    """Embedding请求"""
    texts: List[str] = Field(..., description="待向量化的文本列表")
    model_name: str = Field("default", description="模型名称")
    normalize: bool = Field(True, description="是否归一化")

class RerankRequest(BaseModel):
    """Rerank请求"""
    query: str = Field(..., description="查询文本")
    candidates: List[str] = Field(..., description="候选文本列表")
    model_name: str = Field("default", description="模型名称")
    top_k: Optional[int] = Field(None, description="返回结果数量")

class LLMRequest(BaseModel):
    """LLM请求"""
    messages: List[Dict[str, str]] = Field(..., description="消息列表")
    max_tokens: int = Field(512, description="最大生成token数")
    temperature: float = Field(0.7, description="温度参数")
    stream: bool = Field(False, description="是否流式输出")
    backend: Optional[str] = Field(None, description="指定后端(vllm/llama_cpp)")

class DocumentProcessRequest(BaseModel):
    """文档处理请求"""
    file_path: str = Field(..., description="文件路径")
    file_name: str = Field(..., description="文件名称")
    ocr_result: Dict[str, Any] = Field(..., description="OCR结果")

class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    services: Dict[str, bool]
    timestamp: datetime

class QueryResponse(BaseModel):
    """查询响应"""
    query: str
    results: List[Dict[str, Any]]
    total_candidates: int
    processing_time: float
    search_stats: Dict[str, Any]
    llm_response: Optional[str] = None

# FastAPI应用
app = FastAPI(
    title="RAG System API",
    description="完整的RAG系统API，支持Embedding、四库搜索、Rerank、LLM推理",
    version="1.0.0"
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化服务
    logger.info("启动RAG系统API...")
    
    global embedding_service, four_db_service, rerank_service, llm_service, model_caller
    
    try:
        # 初始化各个服务
        embedding_service = await get_embedding_service()
        logger.info("✓ Embedding服务已启动")
        
        four_db_service = await get_four_db_service()
        logger.info("✓ 四库服务已启动")
        
        rerank_service = await get_rerank_service()
        logger.info("✓ Rerank服务已启动")
        
        llm_service = await get_llm_service()
        logger.info("✓ LLM服务已启动")
        
        model_caller = await get_model_caller()
        logger.info("✓ 模型调用器已启动")
        
        logger.info("✓ RAG系统API启动完成")
        
    except Exception as e:
        logger.error(f"服务初始化失败: {e}")
        raise
    
    yield
    
    # 关闭时清理资源
    logger.info("关闭RAG系统API...")
    
    try:
        if embedding_service:
            await embedding_service.close()
        
        if four_db_service:
            await four_db_service.close()
        
        if rerank_service:
            pass  # Rerank服务无需特殊关闭
        
        if llm_service:
            await llm_service.close()
        
        if model_caller:
            await model_caller.close()
        
        logger.info("✓ RAG系统API已关闭")
        
    except Exception as e:
        logger.error(f"服务关闭失败: {e}")

app.router.lifespan_context = lifespan

# 健康检查
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查"""
    return HealthResponse(
        status="healthy",
        services={
            "embedding": embedding_service is not None,
            "four_database": four_db_service is not None,
            "rerank": rerank_service is not None,
            "llm": llm_service is not None,
            "model_caller": model_caller is not None
        },
        timestamp=datetime.now()
    )

# Embedding端点
@app.post("/api/v1/embedding")
async def create_embeddings(request: EmbeddingRequest):
    """生成文本向量"""
    try:
        results = await model_caller.embed(
            texts=request.texts,
            model_name=request.model_name,
            normalize=request.normalize
        )
        
        return {
            "status": "success",
            "results": [
                {
                    "embedding_id": result.embedding_id,
                    "vector": result.vector,
                    "dimension": result.dimension,
                    "model_name": result.model_name,
                    "processing_time": result.processing_time
                }
                for result in (results if isinstance(results, list) else [results])
            ]
        }
        
    except Exception as e:
        logger.error(f"生成向量失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Rerank端点
@app.post("/api/v1/rerank")
async def rerank_candidates(request: RerankRequest):
    """重排候选结果"""
    try:
        result = await model_caller.rerank(
            query=request.query,
            candidates=request.candidates,
            model_name=request.model_name,
            top_k=request.top_k
        )
        
        return {
            "status": "success",
            "query": result.query,
            "reranked_candidates": result.candidates,
            "scores": result.scores,
            "model_name": result.model_name,
            "processing_time": result.processing_time
        }
        
    except Exception as e:
        logger.error(f"重排失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 四库搜索端点
@app.post("/api/v1/search", response_model=QueryResponse)
async def search_documents(request: QueryRequest):
    """四库联合搜索"""
    try:
        start_time = datetime.now()
        
        # 执行四库搜索
        search_results = await four_db_service.search_four_databases(
            query_text=request.query,
            top_k=request.top_k,
            filters=request.filters
        )
        
        # Rerank重排
        if request.use_rerank and search_results.get('final_results'):
            candidates = [
                {
                    'chunk_id': result.chunk_id,
                    'content': result.content,
                    'score': result.final_score,
                    'metadata': result.metadata
                }
                for result in search_results['final_results']
            ]
            
            rerank_result = await model_caller.rerank(
                query=request.query,
                candidates=[c['content'] for c in candidates],
                top_k=request.top_k
            )
            
            # 更新搜索结果
            for i, score in enumerate(rerank_result.scores):
                if i < len(search_results['final_results']):
                    search_results['final_results'][i].final_score = score
        
        # LLM生成答案
        llm_response = None
        if request.use_llm:
            # 构建提示词
            context = "\n\n".join([
                f"文档片段{i+1}: {result.content}"
                for i, result in enumerate(search_results['final_results'][:5])
            ])
            
            prompt = f"""基于以下文档片段回答问题：

问题：{request.query}

文档片段：
{context}

请提供准确、简洁的答案。"""
            
            messages = [Message(role="user", content=prompt)]
            llm_result = await llm_service.generate(
                messages=messages,
                max_tokens=512,
                temperature=0.7
            )
            llm_response = llm_result.text
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        return QueryResponse(
            query=request.query,
            results=[
                {
                    "chunk_id": result.chunk_id,
                    "content": result.content,
                    "score": result.final_score,
                    "source": result.source,
                    "metadata": result.metadata
                }
                for result in search_results['final_results']
            ],
            total_candidates=search_results.get('total_candidates', 0),
            processing_time=processing_time,
            search_stats=search_results.get('search_stats', {}),
            llm_response=llm_response
        )
        
    except Exception as e:
        logger.error(f"搜索失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# LLM推理端点
@app.post("/api/v1/llm/generate")
async def generate_text(request: LLMRequest):
    """LLM文本生成"""
    try:
        # 转换消息格式
        messages = [
            Message(role=msg["role"], content=msg["content"])
            for msg in request.messages
        ]
        
        if request.stream:
            # 流式生成
            from fastapi.responses import StreamingResponse
            
            async def generate_stream():
                async for chunk in llm_service.generate_stream(
                    messages=messages,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                    backend=request.backend
                ):
                    yield chunk
            
            return StreamingResponse(generate_stream(), media_type="text/plain")
        else:
            # 非流式生成
            result = await llm_service.generate(
                messages=messages,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                backend=request.backend
            )
            
            return {
                "status": "success",
                "text": result.text,
                "model": result.model,
                "tokens_used": result.tokens_used,
                "generation_time": result.generation_time,
                "finish_reason": result.finish_reason,
                "metadata": result.metadata
            }
        
    except Exception as e:
        logger.error(f"LLM生成失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 文档处理端点
@app.post("/api/v1/documents/process")
async def process_document(request: DocumentProcessRequest, background_tasks: BackgroundTasks):
    """处理文档并存储到四库"""
    try:
        # 后台处理文档
        async def process_task():
            try:
                result = await four_db_service.process_document(
                    file_path=request.file_path,
                    file_name=request.file_name,
                    ocr_result=request.ocr_result
                )
                logger.info(f"文档处理完成: {result}")
            except Exception as e:
                logger.error(f"文档处理失败: {e}")
        
        background_tasks.add_task(process_task)
        
        return {
            "status": "submitted",
            "message": "文档处理任务已提交",
            "file_name": request.file_name
        }
        
    except Exception as e:
        logger.error(f"提交文档处理任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 系统统计端点
@app.get("/api/v1/stats")
async def get_system_stats():
    """获取系统统计信息"""
    try:
        stats = await four_db_service.get_system_statistics()
        
        return {
            "status": "success",
            "statistics": stats,
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        logger.error(f"获取系统统计失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 模型信息端点
@app.get("/api/v1/models")
async def get_models_info():
    """获取可用模型信息"""
    try:
        model_info = await model_caller.get_model_info()
        llm_backends = await llm_service.get_available_backends()
        
        return {
            "status": "success",
            "embedding_models": model_info["embedding"],
            "rerank_models": model_info["rerank"],
            "llm_backends": llm_backends,
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        logger.error(f"获取模型信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 启动服务
if __name__ == "__main__":
    uvicorn.run(
        "rag_api_service:app",
        host=API_HOST,
        port=API_PORT,
        log_level=LOG_LEVEL.lower(),
        reload=True
    )