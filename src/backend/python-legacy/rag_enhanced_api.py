#!/usr/bin/env python3
"""
增强RAG API服务 - 集成完整RAG+LLM管道
支持任务识别、编排、检索、精排和LLM生成
"""

import os
import sys
import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# 添加项目路径
sys.path.insert(0, '/home/l/rag-dashboard/src/backend/python-legacy')

from rag_llm_pipeline import (
    RAGLLMPipeline,
    TaskType,
    GenerationResult
)

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============ 数据模型 ============

class ChatRequest(BaseModel):
    """聊天请求"""
    query: str = Field(..., description="用户查询")
    session_id: Optional[str] = Field(None, description="会话ID")
    use_rag: bool = Field(True, description="是否使用RAG")
    top_k: int = Field(10, description="检索结果数量")
    context_window: int = Field(4000, description="上下文窗口大小")
    temperature: float = Field(0.7, description="生成温度")
    max_tokens: int = Field(512, description="最大生成token数")

class ChatResponse(BaseModel):
    """聊天响应"""
    status: str
    query: str
    answer: str
    task_type: str
    complexity: str
    confidence: float
    sources: List[Dict[str, Any]]
    processing_time: float
    metadata: Dict[str, Any]

class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    timestamp: str
    pipeline_ready: bool
    models_loaded: bool
    database_connected: bool

# ============ FastAPI应用 ============

# 全局管道实例
rag_pipeline = RAGLLMPipeline()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化
    await rag_pipeline.initialize()
    yield
    # 关闭时清理
    if rag_pipeline.db_pool:
        await rag_pipeline.db_pool.close()

app = FastAPI(
    title="增强RAG API服务",
    description="集成完整RAG+LLM管道的智能问答服务",
    version="2.0.0",
    lifespan=lifespan
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ API端点 ============

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查"""
    return HealthResponse(
        status="healthy" if all([
            rag_pipeline.models_loaded,
            rag_pipeline.db_connected
        ]) else "unhealthy",
        timestamp=datetime.now().isoformat(),
        pipeline_ready=True,
        models_loaded=rag_pipeline.models_loaded,
        database_connected=rag_pipeline.db_connected
    )

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """智能问答API"""
    import time
    start_time = time.time()
    
    try:
        # 处理查询
        result = await rag_pipeline.process_query(
            query=request.query,
            use_rag=request.use_rag,
            top_k=request.top_k,
            context_window=request.context_window
        )
        
        processing_time = time.time() - start_time
        
        return ChatResponse(
            status="success",
            query=request.query,
            answer=result.answer,
            task_type=result.metadata.get('task_type', 'unknown'),
            complexity=result.metadata.get('complexity', 'unknown'),
            confidence=result.confidence,
            sources=result.sources,
            processing_time=processing_time,
            metadata=result.metadata
        )
        
    except Exception as e:
        logger.error(f"聊天处理失败: {e}")
        raise HTTPException(status_code=500, detail=f"聊天处理失败: {str(e)}")

@app.post("/api/analyze")
async def analyze_query(query: str = Body(..., embed=True)):
    """分析查询意图"""
    try:
        from rag_llm_pipeline import TaskRecognizer
        
        recognizer = TaskRecognizer()
        intent = await recognizer.recognize(query)
        
        return {
            "status": "success",
            "query": query,
            "task_type": intent.task_type.value,
            "confidence": intent.confidence,
            "keywords": intent.keywords,
            "entities": intent.entities,
            "complexity": intent.complexity,
            "requires_rag": intent.requires_rag
        }
        
    except Exception as e:
        logger.error(f"查询分析失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询分析失败: {str(e)}")

@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "增强RAG API服务",
        "version": "2.0.0",
        "status": "running",
        "features": [
            "任务识别",
            "查询分解",
            "智能检索",
            "精确重排",
            "上下文构建",
            "LLM生成"
        ],
        "endpoints": {
            "health": "/health",
            "chat": "/api/chat",
            "analyze": "/api/analyze"
        }
    }

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8001,
        log_level="info"
    )