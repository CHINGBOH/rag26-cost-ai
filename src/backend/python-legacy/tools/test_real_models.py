#!/usr/bin/env python3
"""
实际模型调用服务
使用transformers直接调用BAAI embedding和rerank模型
"""

import os
import sys
import asyncio
import logging
from typing import List, Dict, Any
from dataclasses import dataclass

# 添加项目路径
sys.path.insert(0, '/home/l/rag-dashboard/src/backend/python-legacy')

# 配置
EMBEDDING_MODEL_PATH = "/home/l/rag-dashboard/models/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181"
RERANK_MODEL_PATH = "/home/l/rag-dashboard/models/models--BAAI--bge-reranker-v2-m3/snapshots/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class ModelResult:
    """模型调用结果"""
    status: str
    data: Any
    processing_time: float
    model_name: str

class RealModelCaller:
    """实际模型调用器 - 使用transformers"""
    
    def __init__(self):
        self.embedding_model = None
        self.rerank_model = None
        self.tokenizer = None
        
    def load_embedding_model(self):
        """加载BAAI embedding模型"""
        try:
            from sentence_transformers import SentenceTransformer
            
            logger.info(f"加载BAAI embedding模型: {EMBEDDING_MODEL_PATH}")
            
            if os.path.exists(EMBEDDING_MODEL_PATH):
                logger.info("使用本地BAAI embedding模型")
                self.embedding_model = SentenceTransformer(EMBEDDING_MODEL_PATH)
            else:
                logger.info("本地模型不存在，使用远程模型")
                self.embedding_model = SentenceTransformer('BAAI/bge-m3')
            
            logger.info(f"✓ BAAI embedding模型加载成功，维度: {self.embedding_model.get_sentence_embedding_dimension()}")
            return True
            
        except Exception as e:
            logger.error(f"✗ BAAI embedding模型加载失败: {e}")
            return False
    
    def load_rerank_model(self):
        """加载BAAI rerank模型"""
        try:
            from sentence_transformers import CrossEncoder
            
            logger.info(f"加载BAAI rerank模型: {RERANK_MODEL_PATH}")
            
            if os.path.exists(RERANK_MODEL_PATH):
                logger.info("使用本地BAAI rerank模型")
                self.rerank_model = CrossEncoder(RERANK_MODEL_PATH)
            else:
                logger.info("本地模型不存在，使用远程模型")
                self.rerank_model = CrossEncoder('BAAI/bge-reranker-v2-m3')
            
            logger.info("✓ BAAI rerank模型加载成功")
            return True
            
        except Exception as e:
            logger.error(f"✗ BAAI rerank模型加载失败: {e}")
            return False
    
    async def embed_text(self, text: str) -> ModelResult:
        """实际调用embedding模型"""
        import time
        start_time = time.time()
        
        try:
            if not self.embedding_model:
                if not self.load_embedding_model():
                    return ModelResult(
                        status="failed",
                        data=None,
                        processing_time=0,
                        model_name="BAAI/bge-m3"
                    )
            
            # 调用模型
            embedding = self.embedding_model.encode(text, convert_to_numpy=True)
            
            processing_time = time.time() - start_time
            
            return ModelResult(
                status="success",
                data=embedding.tolist(),
                processing_time=processing_time,
                model_name="BAAI/bge-m3"
            )
            
        except Exception as e:
            logger.error(f"Embedding调用失败: {e}")
            return ModelResult(
                status="failed",
                data=None,
                processing_time=time.time() - start_time,
                model_name="BAAI/bge-m3"
            )
    
    async def rerank(
        self,
        query: str,
        candidates: List[str],
        top_k: int = 10
    ) -> ModelResult:
        """实际调用rerank模型"""
        import time
        import numpy as np
        start_time = time.time()
        
        try:
            if not self.rerank_model:
                if not self.load_rerank_model():
                    return ModelResult(
                        status="failed",
                        data=None,
                        processing_time=0,
                        model_name="BAAI/bge-reranker-v2-m3"
                    )
            
            # 准备查询-文档对
            query_doc_pairs = [(query, doc) for doc in candidates]
            
            # 调用模型
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
            
            processing_time = time.time() - start_time
            
            results = {
                'reranked_indices': sorted_indices.tolist(),
                'reranked_scores': normalized_scores[sorted_indices].tolist(),
                'reranked_candidates': [candidates[i] for i in sorted_indices]
            }
            
            return ModelResult(
                status="success",
                data=results,
                processing_time=processing_time,
                model_name="BAAI/bge-reranker-v2-m3"
            )
            
        except Exception as e:
            logger.error(f"Rerank调用失败: {e}")
            return ModelResult(
                status="failed",
                data=None,
                processing_time=time.time() - start_time,
                model_name="BAAI/bge-reranker-v2-m3"
            )

async def test_real_model_calls():
    """测试实际模型调用"""
    import asyncpg
    
    logger.info("=" * 60)
    logger.info("测试实际模型调用")
    logger.info("=" * 60)
    
    # 初始化模型调用器
    model_caller = RealModelCaller()
    
    # 测试1: Embedding调用
    logger.info("\n1. 测试BAAI Embedding模型调用")
    test_text = "深圳市建设工程计价费率标准"
    
    embed_result = await model_caller.embed_text(test_text)
    
    if embed_result.status == "success":
        logger.info(f"✓ Embedding调用成功")
        logger.info(f"  - 向量维度: {len(embed_result.data)}")
        logger.info(f"  - 处理时间: {embed_result.processing_time:.4f}秒")
        logger.info(f"  - 前10个维度: {embed_result.data[:10]}")
    else:
        logger.error(f"✗ Embedding调用失败")
    
    # 测试2: Rerank调用
    logger.info("\n2. 测试BAAI Rerank模型调用")
    
    # 从数据库获取候选
    conn = await asyncpg.connect(
        host="localhost",
        port=5432,
        database="rag_db",
        user="rag_user",
        password=os.environ.get("POSTGRES_PASSWORD", "rag_password")
    )
    
    try:
        chunks = await conn.fetch("""
            SELECT id, content
            FROM document_chunks
            WHERE LENGTH(content) > 20
            LIMIT 10
        """)
        
        if chunks:
            candidates = [chunk['content'] for chunk in chunks]
            logger.info(f"从数据库获取 {len(candidates)} 个候选文档块")
            
            test_query = "工程量清单"
            logger.info(f"查询: {test_query}")
            
            rerank_result = await model_caller.rerank(test_query, candidates, top_k=5)
            
            if rerank_result.status == "success":
                logger.info(f"✓ Rerank调用成功")
                logger.info(f"  - 处理时间: {rerank_result.processing_time:.4f}秒")
                logger.info(f"  - 重排候选数: {len(rerank_result.data['reranked_candidates'])}")
                
                for i, (idx, score, candidate) in enumerate(zip(
                    rerank_result.data['reranked_indices'],
                    rerank_result.data['reranked_scores'],
                    rerank_result.data['reranked_candidates']
                ), 1):
                    content_preview = candidate[:50] + "..." if len(candidate) > 50 else candidate
                    logger.info(f"  {i}. [原始索引:{idx}] 分数:{score:.4f} - {content_preview}")
            else:
                logger.error(f"✗ Rerank调用失败")
        else:
            logger.info("没有找到文档块用于测试")
            
    finally:
        await conn.close()
    
    # 测试3: 完整的RAG流程
    logger.info("\n3. 测试完整RAG流程 (Embedding + Rerank)")
    
    test_query = "建设工程造价咨询"
    logger.info(f"查询: {test_query}")
    
    # Step 1: 向量化查询
    logger.info("Step 1: 向量化查询")
    embed_result = await model_caller.embed_text(test_query)
    
    if embed_result.status == "success":
        logger.info(f"✓ 查询向量化成功")
    else:
        logger.error(f"✗ 查询向量化失败")
        return
    
    # Step 2: 获取候选
    logger.info("Step 2: 从数据库获取候选")
    conn = await asyncpg.connect(
        host="localhost",
        port=5432,
        database="rag_db",
        user="rag_user",
        password=os.environ.get("POSTGRES_PASSWORD", "rag_password")
    )
    
    try:
        candidates_chunks = await conn.fetch("""
            SELECT id, content
            FROM document_chunks
            WHERE LENGTH(content) > 10
            LIMIT 15
        """)
        
        candidates = [chunk['content'] for chunk in candidates_chunks]
        logger.info(f"获取到 {len(candidates)} 个候选")
        
        # Step 3: Rerank重排
        logger.info("Step 3: Rerank重排")
        rerank_result = await model_caller.rerank(test_query, candidates, top_k=5)
        
        if rerank_result.status == "success":
            logger.info(f"✓ Rerank重排成功")
            logger.info(f"\n最终Top 5结果:")
            
            for i, (idx, score, candidate) in enumerate(zip(
                rerank_result.data['reranked_indices'],
                rerank_result.data['reranked_scores'],
                rerank_result.data['reranked_candidates']
            ), 1):
                content_preview = candidate[:80] + "..." if len(candidate) > 80 else candidate
                logger.info(f"{i}. [{score:.4f}] {content_preview}")
        else:
            logger.error(f"✗ Rerank重排失败")
            
    finally:
        await conn.close()
    
    logger.info("\n" + "=" * 60)
    logger.info("实际模型调用测试完成")
    logger.info("=" * 60)

async def main():
    """主函数"""
    await test_real_model_calls()

if __name__ == "__main__":
    asyncio.run(main())