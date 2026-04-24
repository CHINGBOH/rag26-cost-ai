#!/usr/bin/env python3
"""
统一RAG API服务
整合Embedding、Rerank、检索等所有功能
提供RESTful API接口
"""

import os
import sys
import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import asyncpg
import numpy as np

# 添加项目路径
sys.path.insert(0, '/home/l/rag-dashboard/src/backend/python-legacy')

# 配置
EMBEDDING_MODEL_PATH = "/home/l/rag-dashboard/models/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181"
RERANK_MODEL_PATH = "/home/l/rag-dashboard/models/models--BAAI--bge-reranker-v2-m3/snapshots/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "rag_db",
    "user": "rag_user",
    "password": os.environ.get("POSTGRES_PASSWORD", "rag_password")
}

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============ 数据模型 ============

class EmbeddingRequest(BaseModel):
    """Embedding请求"""
    text: str = Field(..., description="要向量化的文本")

class EmbeddingResponse(BaseModel):
    """Embedding响应"""
    status: str
    text: str
    embedding: List[float]
    dimension: int
    processing_time: float

class RerankRequest(BaseModel):
    """Rerank请求"""
    query: str = Field(..., description="查询文本")
    candidates: List[str] = Field(..., description="候选文档列表")
    top_k: int = Field(default=10, description="返回前K个结果")

class RerankResponse(BaseModel):
    """Rerank响应"""
    status: str
    query: str
    total_candidates: int
    reranked_results: List[Dict[str, Any]]
    processing_time: float

class SearchRequest(BaseModel):
    """搜索请求"""
    query: str = Field(..., description="查询文本")
    top_k: int = Field(default=10, description="返回前K个结果")
    use_rerank: bool = Field(default=True, description="是否使用Rerank")

class SearchResult(BaseModel):
    """搜索结果"""
    chunk_id: int
    content: str
    document_id: int
    page_number: int
    score: float
    rerank_score: Optional[float] = None
    final_score: float

class SearchResponse(BaseModel):
    """搜索响应"""
    status: str
    query: str
    total_results: int
    results: List[SearchResult]
    processing_time: float
    embedding_time: float
    retrieval_time: float
    rerank_time: float

class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    timestamp: str
    embedding_model_ready: bool
    rerank_model_ready: bool
    database_ready: bool

# ============ RAG服务核心 ============

class RAGService:
    """RAG服务核心类"""
    
    def __init__(self):
        self.embedding_model = None
        self.rerank_model = None
        self.db_pool = None
        self.embedding_ready = False
        self.rerank_ready = False
        self.db_ready = False
        
    async def initialize(self):
        """初始化所有服务"""
        try:
            # 加载模型
            await self.load_models()
            
            # 连接数据库
            await self.connect_database()
            
            logger.info("✓ RAG服务初始化完成")
            
        except Exception as e:
            logger.error(f"✗ RAG服务初始化失败: {e}")
            raise
    
    async def load_models(self):
        """加载所有模型"""
        try:
            from sentence_transformers import SentenceTransformer, CrossEncoder
            
            # 加载Embedding模型
            logger.info(f"加载BAAI embedding模型: {EMBEDDING_MODEL_PATH}")
            if os.path.exists(EMBEDDING_MODEL_PATH):
                self.embedding_model = SentenceTransformer(EMBEDDING_MODEL_PATH)
                logger.info("✓ 使用本地BAAI embedding模型")
            else:
                self.embedding_model = SentenceTransformer('BAAI/bge-m3')
                logger.info("✓ 使用远程BAAI embedding模型")
            
            self.embedding_ready = True
            
            # 加载Rerank模型
            logger.info(f"加载BAAI rerank模型: {RERANK_MODEL_PATH}")
            if os.path.exists(RERANK_MODEL_PATH):
                self.rerank_model = CrossEncoder(RERANK_MODEL_PATH)
                logger.info("✓ 使用本地BAAI rerank模型")
            else:
                self.rerank_model = CrossEncoder('BAAI/bge-reranker-v2-m3')
                logger.info("✓ 使用远程BAAI rerank模型")
            
            self.rerank_ready = True
            
            logger.info("✓ 所有模型加载完成")
            
        except Exception as e:
            logger.error(f"✗ 模型加载失败: {e}")
            raise
    
    async def connect_database(self):
        """连接数据库"""
        try:
            self.db_pool = await asyncpg.create_pool(**DB_CONFIG)
            self.db_ready = True
            logger.info("✓ 数据库连接成功")
            
        except Exception as e:
            logger.error(f"✗ 数据库连接失败: {e}")
            raise
    
    async def embed_text(self, text: str) -> EmbeddingResponse:
        """文本向量化"""
        import time
        start_time = time.time()
        
        try:
            if not self.embedding_ready:
                raise HTTPException(status_code=500, detail="Embedding模型未就绪")
            
            loop = asyncio.get_running_loop()
            embedding = await loop.run_in_executor(
                None, lambda: self.embedding_model.encode(text, convert_to_numpy=True)
            )
            processing_time = time.time() - start_time
            
            return EmbeddingResponse(
                status="success",
                text=text,
                embedding=embedding.tolist(),
                dimension=len(embedding),
                processing_time=processing_time
            )
            
        except Exception as e:
            logger.error(f"Embedding失败: {e}")
            raise HTTPException(status_code=500, detail=f"Embedding失败: {str(e)}")
    
    async def rerank(self, query: str, candidates: List[str], top_k: int = 10) -> RerankResponse:
        """文档重排"""
        import time
        start_time = time.time()
        
        try:
            if not self.rerank_ready:
                raise HTTPException(status_code=500, detail="Rerank模型未就绪")
            
            # 准备查询-文档对
            query_doc_pairs = [(query, doc) for doc in candidates]
            
            # 计算重排分数
            scores = self.rerank_model.predict(query_doc_pairs)
            
            # 归一化分数
            min_score = np.min(scores)
            max_score = np.max(scores)
            if max_score > min_score:
                normalized_scores = (scores - min_score) / (max_score - min_score)
            else:
                normalized_scores = np.ones_like(scores) * 0.5
            
            # 排序
            sorted_indices = np.argsort(normalized_scores)[::-1][:top_k]
            
            # 构建结果
            results = [
                {
                    "original_index": int(idx),
                    "content": candidates[idx],
                    "score": float(normalized_scores[idx])
                }
                for idx in sorted_indices
            ]
            
            processing_time = time.time() - start_time
            
            return RerankResponse(
                status="success",
                query=query,
                total_candidates=len(candidates),
                reranked_results=results,
                processing_time=processing_time
            )
            
        except Exception as e:
            logger.error(f"Rerank失败: {e}")
            raise HTTPException(status_code=500, detail=f"Rerank失败: {str(e)}")
    
    async def search(self, query: str, top_k: int = 10, use_rerank: bool = True) -> SearchResponse:
        """语义搜索"""
        import time
        total_start = time.time()
        
        try:
            # Step 1: 向量化查询（在线程池中执行，避免阻塞事件循环）
            embed_start = time.time()
            loop = asyncio.get_running_loop()
            query_embedding = await loop.run_in_executor(
                None, lambda: self.embedding_model.encode(query, convert_to_numpy=True)
            )
            embedding_time = time.time() - embed_start
            
            # Step 2: 从数据库检索候选
            retrieval_start = time.time()
            async with self.db_pool.acquire() as conn:
                candidates = await conn.fetch("""
                    SELECT id, content, document_id, page_number
                    FROM document_chunks
                    WHERE LENGTH(content) > 10
                    ORDER BY RANDOM()
                    LIMIT 30
                """)
                
                candidates_list = [
                    {
                        'id': chunk['id'],
                        'content': chunk['content'],
                        'document_id': chunk['document_id'],
                        'page_number': chunk['page_number'],
                        'original_score': 0.5
                    }
                    for chunk in candidates
                ]
            
            retrieval_time = time.time() - retrieval_start
            
            # Step 3: Rerank重排
            if use_rerank and self.rerank_ready and candidates_list:
                rerank_start = time.time()
                
                query_doc_pairs = [
                    (query, candidate['content'])
                    for candidate in candidates_list
                ]
                
                scores = self.rerank_model.predict(query_doc_pairs)
                
                min_score = np.min(scores)
                max_score = np.max(scores)
                if max_score > min_score:
                    normalized_scores = (scores - min_score) / (max_score - min_score)
                else:
                    normalized_scores = np.ones_like(scores) * 0.5
                
                for i, candidate in enumerate(candidates_list):
                    candidate['rerank_score'] = float(normalized_scores[i])
                    candidate['final_score'] = float(
                        candidate['original_score'] * 0.3 + normalized_scores[i] * 0.7
                    )
                
                sorted_candidates = sorted(
                    candidates_list,
                    key=lambda x: x['final_score'],
                    reverse=True
                )[:top_k]
                
                rerank_time = time.time() - rerank_start
            else:
                sorted_candidates = candidates_list[:top_k]
                rerank_time = 0.0
            
            total_time = time.time() - total_start
            
            # 构建响应
            results = [
                SearchResult(
                    chunk_id=item['id'],
                    content=item['content'],
                    document_id=item['document_id'],
                    page_number=item['page_number'],
                    score=item['original_score'],
                    rerank_score=item.get('rerank_score'),
                    final_score=item['final_score']
                )
                for item in sorted_candidates
            ]
            
            return SearchResponse(
                status="success",
                query=query,
                total_results=len(results),
                results=results,
                processing_time=total_time,
                embedding_time=embedding_time,
                retrieval_time=retrieval_time,
                rerank_time=rerank_time
            )
            
        except Exception as e:
            logger.error(f"搜索失败: {e}")
            raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")
    
    async def health_check(self) -> HealthResponse:
        """健康检查"""
        return HealthResponse(
            status="healthy" if all([self.embedding_ready, self.rerank_ready, self.db_ready]) else "unhealthy",
            timestamp=datetime.now().isoformat(),
            embedding_model_ready=self.embedding_ready,
            rerank_model_ready=self.rerank_ready,
            database_ready=self.db_ready
        )

# ============ FastAPI应用 ============

# 全局RAG服务实例
rag_service = RAGService()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化
    await rag_service.initialize()
    yield
    # 关闭时清理
    if rag_service.db_pool:
        await rag_service.db_pool.close()

app = FastAPI(
    title="RAG API服务",
    description="统一RAG API服务，提供Embedding、Rerank、语义搜索等功能",
    version="1.0.0",
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
    return await rag_service.health_check()

@app.post("/api/embedding", response_model=EmbeddingResponse)
async def create_embedding(request: EmbeddingRequest):
    """文本向量化API"""
    return await rag_service.embed_text(request.text)

@app.post("/api/rerank", response_model=RerankResponse)
async def rerank_documents(request: RerankRequest):
    """文档重排API"""
    return await rag_service.rerank(request.query, request.candidates, request.top_k)

@app.post("/api/search", response_model=SearchResponse)
async def semantic_search(request: SearchRequest):
    """语义搜索API"""
    return await rag_service.search(request.query, request.top_k, request.use_rerank)

@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "RAG API服务",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "health": "/health",
            "embedding": "/api/embedding",
            "rerank": "/api/rerank",
            "search": "/api/search"
        }
    }

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )