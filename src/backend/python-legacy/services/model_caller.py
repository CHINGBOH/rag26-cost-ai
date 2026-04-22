#!/usr/bin/env python3
"""
模型调用工具
统一的Embedding和Rerank模型调用接口
支持多种模型后端（本地、API、分布式）
"""

import os
import asyncio
import logging
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass
from datetime import datetime
import json

import numpy as np
from sentence_transformers import SentenceTransformer, CrossEncoder
import httpx
import torch

# 配置
EMBEDDING_MODELS = {
    "default": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "chinese": "shibing624/text2vec-base-chinese",
    "multilingual": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "code": "microsoft/codebert-base",
    "financial": "BAAI/bge-small-zh-v1.5"
}

RERANK_MODELS = {
    "default": "cross-encoder/ms-marco-MiniLM-L-12-v2",
    "chinese": "BAAI/bge-reranker-base",
    "multilingual": "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
    "financial": "BAAI/bge-reranker-v2-m3"
}

# API配置
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")

# 本地模型路径
LOCAL_MODEL_DIR = os.getenv("LOCAL_MODEL_DIR", "/models")

# 日志配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class EmbeddingResult:
    """Embedding结果"""
    embedding_id: str
    vector: List[float]
    dimension: int
    model_name: str
    processing_time: float
    created_at: datetime
    metadata: Dict[str, Any]

@dataclass
class RerankResult:
    """Rerank结果"""
    query: str
    candidates: List[str]
    scores: List[float]
    model_name: str
    processing_time: float
    metadata: Dict[str, Any]

class EmbeddingModelCaller:
    """Embedding模型调用器"""
    
    def __init__(self):
        self.models = {}
        self.current_model = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.use_api = False
        self.api_client = None
        
    async def initialize(
        self,
        model_name: str = "default",
        use_api: bool = False,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None
    ):
        """初始化Embedding模型"""
        logger.info(f"初始化Embedding模型: {model_name}")
        
        self.use_api = use_api
        
        if use_api:
            # 使用API调用
            self.api_client = httpx.AsyncClient(
                base_url=api_base or OPENAI_API_BASE,
                headers={"Authorization": f"Bearer {api_key or OPENAI_API_KEY}"},
                timeout=60.0
            )
            logger.info("✓ 使用API调用Embedding模型")
        else:
            # 加载本地模型
            model_path = EMBEDDING_MODELS.get(model_name, model_name)
            
            # 检查是否是本地路径
            if os.path.exists(os.path.join(LOCAL_MODEL_DIR, model_path)):
                model_path = os.path.join(LOCAL_MODEL_DIR, model_path)
            
            logger.info(f"加载模型: {model_path}")
            logger.info(f"使用设备: {self.device}")
            
            try:
                self.models[model_name] = SentenceTransformer(
                    model_path,
                    device=self.device
                )
                self.current_model = self.models[model_name]
                
                logger.info(f"✓ Embedding模型加载成功")
                logger.info(f"向量维度: {self.current_model.get_sentence_embedding_dimension()}")
                
            except Exception as e:
                logger.error(f"加载Embedding模型失败: {e}")
                raise
    
    async def embed(
        self,
        texts: Union[str, List[str]],
        model_name: str = None,
        batch_size: int = 32,
        normalize: bool = True
    ) -> Union[EmbeddingResult, List[EmbeddingResult]]:
        """生成文本向量"""
        if self.use_api:
            return await self._embed_via_api(texts, normalize)
        else:
            return await self._embed_local(texts, model_name, batch_size, normalize)
    
    async def _embed_via_api(
        self,
        texts: Union[str, List[str]],
        normalize: bool
    ) -> Union[EmbeddingResult, List[EmbeddingResult]]:
        """通过API生成向量"""
        start_time = datetime.now()
        
        try:
            # 标准化输入
            single_text = isinstance(texts, str)
            if single_text:
                texts = [texts]
            
            # 调用API
            response = await self.api_client.post(
                "/embeddings",
                json={
                    "input": texts,
                    "model": "text-embedding-ada-002"
                }
            )
            
            if response.status_code != 200:
                raise Exception(f"API请求失败: {response.text}")
            
            data = response.json()
            
            # 解析结果
            results = []
            for i, item in enumerate(data["data"]):
                vector = item["embedding"]
                
                if normalize:
                    vector = self._normalize_vector(vector)
                
                results.append(EmbeddingResult(
                    embedding_id=f"api_{i}_{datetime.now().timestamp()}",
                    vector=vector,
                    dimension=len(vector),
                    model_name="openai-ada-002",
                    processing_time=0,
                    created_at=start_time,
                    metadata={"api": True}
                ))
            
            processing_time = (datetime.now() - start_time).total_seconds()
            for result in results:
                result.processing_time = processing_time / len(results)
            
            return results[0] if single_text else results
            
        except Exception as e:
            logger.error(f"API Embedding失败: {e}")
            raise
    
    async def _embed_local(
        self,
        texts: Union[str, List[str]],
        model_name: str,
        batch_size: int,
        normalize: bool
    ) -> Union[EmbeddingResult, List[EmbeddingResult]]:
        """本地生成向量"""
        start_time = datetime.now()
        
        try:
            # 选择模型
            model = self.current_model
            if model_name and model_name in self.models:
                model = self.models[model_name]
            
            # 标准化输入
            single_text = isinstance(texts, str)
            if single_text:
                texts = [texts]
            
            # 批量编码（在线程池中执行，避免阻塞事件循环）
            loop = asyncio.get_running_loop()
            embeddings = await loop.run_in_executor(
                None,
                lambda: model.encode(
                    texts,
                    batch_size=batch_size,
                    show_progress_bar=False,
                    convert_to_numpy=True
                )
            )
            
            # 归一化
            if normalize:
                embeddings = np.array([self._normalize_vector(emb) for emb in embeddings])
            
            # 生成结果
            import hashlib
            results = []
            for i, embedding in enumerate(embeddings):
                embedding_id = hashlib.md5(texts[i].encode()).hexdigest()
                
                results.append(EmbeddingResult(
                    embedding_id=embedding_id,
                    vector=embedding.tolist(),
                    dimension=len(embedding),
                    model_name=model_name or "default",
                    processing_time=0,
                    created_at=start_time,
                    metadata={"device": self.device}
                ))
            
            processing_time = (datetime.now() - start_time).total_seconds()
            for result in results:
                result.processing_time = processing_time / len(results)
            
            return results[0] if single_text else results
            
        except Exception as e:
            logger.error(f"本地Embedding失败: {e}")
            raise
    
    def _normalize_vector(self, vector: List[float]) -> List[float]:
        """归一化向量"""
        vector = np.array(vector)
        norm = np.linalg.norm(vector)
        
        if norm == 0:
            return vector.tolist()
        
        return (vector / norm).tolist()
    
    async def embed_documents(
        self,
        documents: List[Dict[str, Any]],
        text_field: str = "content",
        batch_size: int = 32
    ) -> List[EmbeddingResult]:
        """批量向量化文档"""
        try:
            # 提取文本
            texts = [doc.get(text_field, "") for doc in documents]
            
            # 批量向量化
            embeddings = await self.embed(texts, batch_size=batch_size)
            
            # 添加文档元数据
            for i, embedding in enumerate(embeddings):
                embedding.metadata.update({
                    "document_id": documents[i].get("id"),
                    "document_type": documents[i].get("type"),
                    "page_number": documents[i].get("page_number")
                })
            
            return embeddings
            
        except Exception as e:
            logger.error(f"批量向量化文档失败: {e}")
            raise
    
    async def get_model_info(self) -> Dict[str, Any]:
        """获取模型信息"""
        if self.use_api:
            return {
                "type": "api",
                "model": "openai-ada-002",
                "dimension": 1536
            }
        else:
            return {
                "type": "local",
                "model": self.current_model.__class__.__name__,
                "dimension": self.current_model.get_sentence_embedding_dimension(),
                "device": self.device,
                "available_models": list(self.models.keys())
            }
    
    async def close(self):
        """关闭服务"""
        if self.api_client:
            await self.api_client.aclose()
        logger.info("Embedding模型调用器已关闭")

class RerankModelCaller:
    """Rerank模型调用器"""
    
    def __init__(self):
        self.models = {}
        self.current_model = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.use_api = False
        self.api_client = None
        
    async def initialize(
        self,
        model_name: str = "default",
        use_api: bool = False,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None
    ):
        """初始化Rerank模型"""
        logger.info(f"初始化Rerank模型: {model_name}")
        
        self.use_api = use_api
        
        if use_api:
            # 使用API调用
            self.api_client = httpx.AsyncClient(
                base_url=api_base or OPENAI_API_BASE,
                headers={"Authorization": f"Bearer {api_key or OPENAI_API_KEY}"},
                timeout=60.0
            )
            logger.info("✓ 使用API调用Rerank模型")
        else:
            # 加载本地模型
            model_path = RERANK_MODELS.get(model_name, model_name)
            
            # 检查是否是本地路径
            if os.path.exists(os.path.join(LOCAL_MODEL_DIR, model_path)):
                model_path = os.path.join(LOCAL_MODEL_DIR, model_path)
            
            logger.info(f"加载模型: {model_path}")
            logger.info(f"使用设备: {self.device}")
            
            try:
                self.models[model_name] = CrossEncoder(
                    model_path,
                    device=self.device
                )
                self.current_model = self.models[model_name]
                
                logger.info(f"✓ Rerank模型加载成功")
                
            except Exception as e:
                logger.error(f"加载Rerank模型失败: {e}")
                raise
    
    async def rerank(
        self,
        query: str,
        candidates: List[str],
        model_name: str = None,
        top_k: Optional[int] = None,
        return_scores: bool = True
    ) -> RerankResult:
        """重排候选结果"""
        if self.use_api:
            return await self._rerank_via_api(query, candidates, top_k, return_scores)
        else:
            return await self._rerank_local(query, candidates, model_name, top_k, return_scores)
    
    async def _rerank_via_api(
        self,
        query: str,
        candidates: List[str],
        top_k: Optional[int],
        return_scores: bool
    ) -> RerankResult:
        """通过API重排"""
        start_time = datetime.now()
        
        try:
            # 调用API（简化版本，实际可能需要多次调用）
            # 这里使用简单的相似度计算
            
            # 向量化查询和候选
            embedding_caller = EmbeddingModelCaller()
            await embedding_caller.initialize(use_api=True)
            
            query_embedding = await embedding_caller.embed(query)
            candidate_embeddings = await embedding_caller.embed(candidates)
            
            # 计算相似度
            scores = []
            for candidate_emb in candidate_embeddings:
                score = self._cosine_similarity(
                    query_embedding.vector,
                    candidate_emb.vector
                )
                scores.append(score)
            
            # 排序
            sorted_indices = sorted(
                range(len(scores)),
                key=lambda i: scores[i],
                reverse=True
            )
            
            # 选择top_k
            if top_k:
                sorted_indices = sorted_indices[:top_k]
            
            # 重新排序
            reranked_candidates = [candidates[i] for i in sorted_indices]
            reranked_scores = [scores[i] for i in sorted_indices]
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            return RerankResult(
                query=query,
                candidates=reranked_candidates,
                scores=reranked_scores,
                model_name="api-rerank",
                processing_time=processing_time,
                metadata={"method": "cosine_similarity"}
            )
            
        except Exception as e:
            logger.error(f"API Rerank失败: {e}")
            raise
    
    async def _rerank_local(
        self,
        query: str,
        candidates: List[str],
        model_name: str,
        top_k: Optional[int],
        return_scores: bool
    ) -> RerankResult:
        """本地重排"""
        start_time = datetime.now()
        
        try:
            # 选择模型
            model = self.current_model
            if model_name and model_name in self.models:
                model = self.models[model_name]
            
            # 构建查询-文档对
            query_doc_pairs = [(query, candidate) for candidate in candidates]
            
            # 批量计算分数
            scores = model.predict(query_doc_pairs)
            
            # 归一化分数
            scores = self._normalize_scores(scores)
            
            # 排序
            sorted_indices = sorted(
                range(len(scores)),
                key=lambda i: scores[i],
                reverse=True
            )
            
            # 选择top_k
            if top_k:
                sorted_indices = sorted_indices[:top_k]
            
            # 重新排序
            reranked_candidates = [candidates[i] for i in sorted_indices]
            reranked_scores = [scores[i] for i in sorted_indices]
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            return RerankResult(
                query=query,
                candidates=reranked_candidates,
                scores=reranked_scores,
                model_name=model_name or "default",
                processing_time=processing_time,
                metadata={"device": self.device}
            )
            
        except Exception as e:
            logger.error(f"本地Rerank失败: {e}")
            raise
    
    def _normalize_scores(self, scores: np.ndarray) -> np.ndarray:
        """归一化分数"""
        if len(scores) == 0:
            return scores
        
        min_score = np.min(scores)
        max_score = np.max(scores)
        
        if max_score == min_score:
            return np.ones_like(scores) * 0.5
        
        normalized = (scores - min_score) / (max_score - min_score)
        return normalized
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        vec1 = np.array(vec1)
        vec2 = np.array(vec2)
        
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    async def batch_rerank(
        self,
        queries: List[str],
        candidates_list: List[List[str]],
        top_k: int = 10
    ) -> List[RerankResult]:
        """批量重排"""
        try:
            results = []
            
            for query, candidates in zip(queries, candidates_list):
                result = await self.rerank(query, candidates, top_k=top_k)
                results.append(result)
            
            return results
            
        except Exception as e:
            logger.error(f"批量重排失败: {e}")
            raise
    
    async def get_model_info(self) -> Dict[str, Any]:
        """获取模型信息"""
        if self.use_api:
            return {
                "type": "api",
                "model": "api-rerank",
                "method": "cosine_similarity"
            }
        else:
            return {
                "type": "local",
                "model": self.current_model.__class__.__name__,
                "device": self.device,
                "available_models": list(self.models.keys())
            }
    
    async def close(self):
        """关闭服务"""
        if self.api_client:
            await self.api_client.aclose()
        logger.info("Rerank模型调用器已关闭")

class UnifiedModelCaller:
    """统一模型调用器"""
    
    def __init__(self):
        self.embedding_caller = EmbeddingModelCaller()
        self.rerank_caller = RerankModelCaller()
        
    async def initialize(
        self,
        embedding_model: str = "default",
        rerank_model: str = "default",
        use_api: bool = False,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None
    ):
        """初始化统一模型调用器"""
        logger.info("初始化统一模型调用器...")
        
        # 初始化Embedding模型
        await self.embedding_caller.initialize(
            model_name=embedding_model,
            use_api=use_api,
            api_key=api_key,
            api_base=api_base
        )
        
        # 初始化Rerank模型
        await self.rerank_caller.initialize(
            model_name=rerank_model,
            use_api=use_api,
            api_key=api_key,
            api_base=api_base
        )
        
        logger.info("✓ 统一模型调用器初始化完成")
    
    async def embed(self, texts: Union[str, List[str]], **kwargs) -> Union[EmbeddingResult, List[EmbeddingResult]]:
        """生成文本向量"""
        return await self.embedding_caller.embed(texts, **kwargs)
    
    async def rerank(self, query: str, candidates: List[str], **kwargs) -> RerankResult:
        """重排候选结果"""
        return await self.rerank_caller.rerank(query, candidates, **kwargs)
    
    async def get_model_info(self) -> Dict[str, Any]:
        """获取模型信息"""
        return {
            "embedding": await self.embedding_caller.get_model_info(),
            "rerank": await self.rerank_caller.get_model_info()
        }
    
    async def close(self):
        """关闭服务"""
        await self.embedding_caller.close()
        await self.rerank_caller.close()
        logger.info("统一模型调用器已关闭")

# 全局实例
unified_model_caller = UnifiedModelCaller()

async def get_model_caller() -> UnifiedModelCaller:
    """获取模型调用器实例"""
    return unified_model_caller