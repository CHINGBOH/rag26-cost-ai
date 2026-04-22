#!/usr/bin/env python3
"""
Embedding服务 - 文本向量化服务
支持多种embedding模型，批量处理，异步任务
"""

import os
import asyncio
import logging
import json
import httpx
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from sentence_transformers import SentenceTransformer
import redis
import asyncpg
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter

# 配置
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", 5432))
POSTGRES_DB = os.getenv("POSTGRES_DB", "rag_db")
POSTGRES_USER = os.getenv("POSTGRES_USER", "rag_user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "rag_password")

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))

# TEI 配置
EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "tei")  # local or tei
TEI_URL = os.getenv("TEI_URL", "http://localhost:8003")

# 日志配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class EmbeddingResult:
    """向量化结果"""
    embedding_id: str
    vector: List[float]
    dimension: int
    model_name: str
    processing_time: float
    created_at: datetime

class EmbeddingService:
    """Embedding服务"""
    
    def __init__(self):
        self.embedding_models = {}
        self.current_model = None
        self.redis_client = None
        self.qdrant_client = None
        self.postgres_pool = None
        self.tei_client = None
        self.embedding_dimension = 384  # 默认维度
        
    async def initialize(self):
        """初始化服务"""
        logger.info("初始化Embedding服务...")
        logger.info(f"使用后端: {EMBEDDING_BACKEND}")
        
        # 初始化Redis客户端（异步）
        self.redis_client = redis.asyncio.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True
        )
        
        # 初始化Qdrant客户端
        self.qdrant_client = QdrantClient(
            url=f"http://{QDRANT_HOST}:{QDRANT_PORT}"
        )
        
        # 初始化PostgreSQL连接池
        self.postgres_pool = await asyncpg.create_pool(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            database=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            min_size=2,
            max_size=10
        )
        
        # 初始化TEI客户端
        if EMBEDDING_BACKEND == "tei":
            self.tei_client = httpx.AsyncClient(base_url=TEI_URL, timeout=30.0)
            logger.info(f"TEI客户端初始化完成: {TEI_URL}")
        else:
            # 加载本地模型
            await self._load_models()
        
        # 确保 Qdrant 集合存在（只创建一次，不删已有数据）
        try:
            collections = [c.name for c in self.qdrant_client.get_collections().collections]
            if "document_chunks" not in collections:
                self.qdrant_client.create_collection(
                    collection_name="document_chunks",
                    vectors_config=VectorParams(size=1024, distance=Distance.COSINE)
                )
                logger.info("Created Qdrant collection: document_chunks")
            else:
                logger.info("Qdrant collection exists: document_chunks")
        except Exception as e:
            logger.warning(f"Qdrant collection check failed: {e}")
        
        logger.info("Embedding服务初始化完成")
    
    async def _load_models(self):
        """加载embedding模型"""
        logger.info("加载embedding模型...")
        
        # 加载默认模型
        default_model = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        logger.info(f"加载默认模型: {default_model}")
        
        try:
            # 尝试使用GPU
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info(f"使用设备: {device}")
            
            self.embedding_models['default'] = SentenceTransformer(default_model, device=device)
            self.current_model = self.embedding_models['default']
            self.embedding_dimension = self.current_model.get_sentence_embedding_dimension()
            torch.set_num_threads(max(1, os.cpu_count() // 2))
            logger.info(f"默认模型加载成功，向量维度: {self.embedding_dimension}")
            logger.info(f"模型设备: {self.current_model.device}")
            logger.info(f"PyTorch threads: {torch.get_num_threads()}")
        except Exception as e:
            logger.error(f"加载默认模型失败: {e}")
            raise
        
        # 可以加载更多模型
        # self.embedding_models['chinese'] = SentenceTransformer("...")
        # self.embedding_models['multilingual'] = SentenceTransformer("...")
    
    async def embed_text(self, text: str, model_name: str = "default") -> EmbeddingResult:
        """向量化单个文本"""
        start_time = datetime.now()
        
        try:
            if EMBEDDING_BACKEND == "tei":
                # 使用TEI服务
                response = await self.tei_client.post(
                    "/embed",
                    json={"inputs": [text]}
                )
                response.raise_for_status()
                embedding = np.array(response.json()['embeddings'][0])
            else:
                # 使用本地模型
                model = self.embedding_models.get(model_name)
                if not model:
                    raise ValueError(f"模型不存在: {model_name}")
                embedding = model.encode(text, convert_to_numpy=True)
            
            # 生成embedding_id
            import hashlib
            embedding_id = hashlib.md5(text.encode()).hexdigest()
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            return EmbeddingResult(
                embedding_id=embedding_id,
                vector=embedding.tolist(),
                dimension=len(embedding),
                model_name=model_name,
                processing_time=processing_time,
                created_at=start_time
            )
            
        except Exception as e:
            logger.error(f"向量化失败: {e}")
            raise
    
    async def embed_batch(self, texts: List[str], model_name: str = "default") -> List[EmbeddingResult]:
        """批量向量化文本"""
        start_time = datetime.now()
        
        try:
            if EMBEDDING_BACKEND == "tei":
                # 使用TEI服务批量处理
                response = await self.tei_client.post(
                    "/embed",
                    json={"inputs": texts}
                )
                response.raise_for_status()
                embeddings = np.array(response.json()['embeddings'])
            else:
                # 使用本地模型
                model = self.embedding_models.get(model_name)
                if not model:
                    raise ValueError(f"模型不存在: {model_name}")
                embeddings = model.encode(texts, convert_to_numpy=True)
            
            results = []
            for i, text in enumerate(texts):
                import hashlib
                embedding_id = hashlib.md5(text.encode()).hexdigest()
                
                results.append(EmbeddingResult(
                    embedding_id=embedding_id,
                    vector=embeddings[i].tolist(),
                    dimension=len(embeddings[i]),
                    model_name=model_name,
                    processing_time=0,  # 批量处理的时间在最后计算
                    created_at=start_time
                ))
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            # 更新处理时间
            for result in results:
                result.processing_time = processing_time / len(texts)
            
            return results
            
        except Exception as e:
            logger.error(f"批量向量化失败: {e}")
            raise
    
    async def embed_document_chunk(
        self, 
        document_id: int, 
        chunk_id: int, 
        content: str,
        page_number: Optional[int] = None
    ) -> Dict[str, Any]:
        """向量化文档块并存储到四库"""
        start_time = datetime.now()
        
        try:
            # 1. 向量化内容
            embedding_result = await self.embed_text(content)
            
            # 2. 存储到Qdrant
            await self._store_to_qdrant(
                document_id=document_id,
                chunk_id=chunk_id,
                content=content,
                embedding_result=embedding_result
            )
            
            # 3. 存储到PostgreSQL
            await self._store_to_postgres(
                document_id=document_id,
                chunk_id=chunk_id,
                content=content,
                embedding_result=embedding_result,
                page_number=page_number
            )
            
            # 4. 缓存到Redis
            await self._cache_embedding(
                chunk_id=chunk_id,
                embedding_result=embedding_result
            )
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            return {
                "chunk_id": chunk_id,
                "embedding_id": embedding_result.embedding_id,
                "dimension": embedding_result.dimension,
                "processing_time": processing_time,
                "status": "completed"
            }
            
        except Exception as e:
            logger.error(f"向量化文档块失败: {e}")
            raise
    
    async def _store_to_qdrant(
        self,
        document_id: int,
        chunk_id: int,
        content: str,
        embedding_result: EmbeddingResult
    ):
        """存储向量到Qdrant"""
        try:
            # 插入向量
            point = PointStruct(
                id=chunk_id,
                vector=embedding_result.vector,
                payload={
                    "document_id": document_id,
                    "chunk_id": chunk_id,
                    "content": content,
                    "embedding_id": embedding_result.embedding_id,
                    "model_name": embedding_result.model_name,
                    "created_at": embedding_result.created_at.isoformat()
                }
            )
            
            self.qdrant_client.upsert(
                collection_name=collection_name,
                points=[point]
            )
            
            logger.info(f"向量已存储到Qdrant: chunk_id={chunk_id}")
            
        except Exception as e:
            logger.error(f"存储到Qdrant失败: {e}")
            raise
    
    async def _store_to_postgres(
        self,
        document_id: int,
        chunk_id: int,
        content: str,
        embedding_result: EmbeddingResult,
        page_number: Optional[int] = None
    ):
        """存储到PostgreSQL"""
        try:
            async with self.postgres_pool.acquire() as conn:
                # 更新文档块的向量化信息
                await conn.execute("""
                    UPDATE document_chunks
                    SET embedding_id = $1,
                        embedding_model = $2,
                        embedding_dimension = $3,
                        embedding_created_at = $4,
                        updated_at = $5
                    WHERE id = $6
                """, 
                    embedding_result.embedding_id,
                    embedding_result.model_name,
                    embedding_result.dimension,
                    embedding_result.created_at,
                    datetime.now(),
                    chunk_id
                )
                
                # 记录向量化任务
                await conn.execute("""
                    INSERT INTO embedding_tasks
                    (task_type, entity_type, entity_id, model_name, 
                     embedding_dimension, status, embedding_id, 
                     vector_data, completed_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                    "chunk",
                    "chunk",
                    chunk_id,
                    embedding_result.model_name,
                    embedding_result.dimension,
                    "completed",
                    embedding_result.embedding_id,
                    json.dumps({"vector": embedding_result.vector}),
                    datetime.now()
                )
                
            logger.info(f"向量化信息已存储到PostgreSQL: chunk_id={chunk_id}")
            
        except Exception as e:
            logger.error(f"存储到PostgreSQL失败: {e}")
            raise
    
    async def _cache_embedding(
        self,
        chunk_id: int,
        embedding_result: EmbeddingResult
    ):
        """缓存embedding结果"""
        try:
            cache_key = f"embedding:chunk:{chunk_id}"
            cache_data = {
                "embedding_id": embedding_result.embedding_id,
                "vector": embedding_result.vector,
                "dimension": embedding_result.dimension,
                "model_name": embedding_result.model_name,
                "created_at": embedding_result.created_at.isoformat()
            }
            
            await self.redis_client.setex(
                cache_key,
                3600,  # 1小时过期
                json.dumps(cache_data)
            )
            
            logger.info(f"Embedding已缓存: chunk_id={chunk_id}")
            
        except Exception as e:
            logger.error(f"缓存失败: {e}")
            # 缓存失败不影响主流程
    
    async def search_similar_chunks(
        self,
        query_text: str,
        document_id: Optional[int] = None,
        top_k: int = 10,
        score_threshold: float = 0.7
    ) -> List[Dict[str, Any]]:
        """搜索相似文档块"""
        try:
            # 向量化查询
            query_embedding = await self.embed_text(query_text)
            
            # 创建搜索过滤器
            query_filter = None
            if document_id is not None:
                query_filter = Filter(
                    must=[
                    {
                        "key": "document_id",
                        "match": {"value": document_id}
                    }
                ]
            )
            
            # 在Qdrant中搜索
            search_results = self.qdrant_client.search(
                collection_name="document_chunks",
                query_vector=query_embedding.vector,
                limit=top_k,
                score_threshold=score_threshold,
                query_filter=query_filter
            )
            
            # 格式化结果
            results = []
            for result in search_results:
                results.append({
                    "chunk_id": result.id,
                    "score": result.score,
                    "payload": result.payload,
                    "content": result.payload.get("content", "")
                })
            
            return results
            
        except Exception as e:
            logger.error(f"搜索相似块失败: {e}")
            raise
    
    async def get_embedding_stats(self) -> Dict[str, Any]:
        """获取向量化统计信息"""
        try:
            # 从PostgreSQL获取统计
            async with self.postgres_pool.acquire() as conn:
                # 总文档块数
                total_chunks = await conn.fetchval("SELECT COUNT(*) FROM document_chunks")
                
                # 已向量化块数
                embedded_chunks = await conn.fetchval("SELECT COUNT(*) FROM document_chunks WHERE embedding_id IS NOT NULL")
                
                # 向量化任务统计
                task_stats = await conn.fetch("""
                    SELECT 
                        status,
                        COUNT(*) as count
                    FROM embedding_tasks
                    GROUP BY status
                """)
                
            stats = {
                "total_chunks": total_chunks,
                "embedded_chunks": embedded_chunks,
                "embedding_progress": round(embedded_chunks / total_chunks * 100, 2) if total_chunks > 0 else 0,
                "embedding_tasks": {row['status']: row['count'] for row in task_stats},
                "available_models": list(self.embedding_models.keys()),
                "current_model": self.current_model.__class__.__name__
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            raise
    
    async def close(self):
        """关闭服务"""
        logger.info("关闭Embedding服务...")
        
        if self.postgres_pool:
            await self.postgres_pool.close()
        
        if self.redis_client:
            self.redis_client.close()
        
        if self.qdrant_client:
            self.qdrant_client.close()
        
        logger.info("Embedding服务已关闭")

# 全局实例
embedding_service = EmbeddingService()

async def get_embedding_service() -> EmbeddingService:
    """获取Embedding服务实例"""
    if embedding_service.current_model is None:
        await embedding_service.initialize()
    return embedding_service