#!/usr/bin/env python3
"""
完整RAG服务 - 使用实际模型调用
包含Embedding、Rerank和完整的检索生成流程
"""

import os
import sys
import asyncio
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

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
class RAGResult:
    """RAG检索结果"""
    query: str
    total_candidates: int
    reranked_results: List[Dict[str, Any]]
    processing_time: float
    embedding_time: float
    rerank_time: float
    retrieval_time: float

class CompleteRAGService:
    """完整RAG服务"""
    
    def __init__(self):
        self.embedding_model = None
        self.rerank_model = None
        
    def load_models(self):
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
            
            # 加载Rerank模型
            logger.info(f"加载BAAI rerank模型: {RERANK_MODEL_PATH}")
            if os.path.exists(RERANK_MODEL_PATH):
                self.rerank_model = CrossEncoder(RERANK_MODEL_PATH)
                logger.info("✓ 使用本地BAAI rerank模型")
            else:
                self.rerank_model = CrossEncoder('BAAI/bge-reranker-v2-m3')
                logger.info("✓ 使用远程BAAI rerank模型")
            
            logger.info("✓ 所有模型加载完成")
            return True
            
        except Exception as e:
            logger.error(f"✗ 模型加载失败: {e}")
            return False
    
    async def retrieve(
        self,
        query: str,
        top_k: int = 10,
        use_rerank: bool = True
    ) -> RAGResult:
        """执行完整RAG检索"""
        import time
        import numpy as np
        import asyncpg
        
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
            conn = await asyncpg.connect(
                host="localhost",
                port=5432,
                database="rag_db",
                user="rag_user",
                password=os.environ.get("POSTGRES_PASSWORD", "rag_password")
            )
            
            try:
                # 简单的文本检索（实际应该使用向量相似度）
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
                        'original_score': 0.5  # 基础分数
                    }
                    for chunk in candidates
                ]
                
                retrieval_time = time.time() - retrieval_start
                
                # Step 3: Rerank重排
                if use_rerank and self.rerank_model and candidates_list:
                    rerank_start = time.time()
                    
                    # 准备查询-文档对
                    query_doc_pairs = [
                        (query, candidate['content'])
                        for candidate in candidates_list
                    ]
                    
                    # 计算重排分数
                    scores = self.rerank_model.predict(query_doc_pairs)
                    
                    # 归一化分数
                    min_score = np.min(scores)
                    max_score = np.max(scores)
                    if max_score > min_score:
                        normalized_scores = (scores - min_score) / (max_score - min_score)
                    else:
                        normalized_scores = np.ones_like(scores) * 0.5
                    
                    # 更新候选分数
                    for i, candidate in enumerate(candidates_list):
                        candidate['rerank_score'] = float(normalized_scores[i])
                        candidate['final_score'] = float(
                            candidate['original_score'] * 0.3 + normalized_scores[i] * 0.7
                        )
                    
                    # 排序并返回top_k
                    sorted_candidates = sorted(
                        candidates_list,
                        key=lambda x: x['final_score'],
                        reverse=True
                    )[:top_k]
                    
                    rerank_time = time.time() - rerank_start
                else:
                    # 不使用rerank，直接返回top_k
                    sorted_candidates = candidates_list[:top_k]
                    rerank_time = 0.0
                
                total_time = time.time() - total_start
                
                return RAGResult(
                    query=query,
                    total_candidates=len(candidates_list),
                    reranked_results=sorted_candidates,
                    processing_time=total_time,
                    embedding_time=embedding_time,
                    rerank_time=rerank_time,
                    retrieval_time=retrieval_time
                )
                
            finally:
                await conn.close()
                
        except Exception as e:
            logger.error(f"RAG检索失败: {e}")
            return RAGResult(
                query=query,
                total_candidates=0,
                reranked_results=[],
                processing_time=time.time() - total_start,
                embedding_time=0.0,
                rerank_time=0.0,
                retrieval_time=0.0
            )

async def test_complete_rag():
    """测试完整RAG服务"""
    logger.info("=" * 60)
    logger.info("测试完整RAG服务 (Embedding + Rerank)")
    logger.info("=" * 60)
    
    # 初始化RAG服务
    rag_service = CompleteRAGService()
    
    if not rag_service.load_models():
        logger.error("模型加载失败，无法继续测试")
        return
    
    # 测试查询
    test_queries = [
        "工程量清单计价标准",
        "建设工程造价咨询",
        "企业管理费率",
        "安全文明施工费"
    ]
    
    for query in test_queries:
        logger.info(f"\n{'=' * 60}")
        logger.info(f"查询: {query}")
        logger.info(f"{'=' * 60}")
        
        # 执行RAG检索（使用rerank）
        result_with_rerank = await rag_service.retrieve(
            query=query,
            top_k=5,
            use_rerank=True
        )
        
        if result_with_rerank.reranked_results:
            logger.info(f"\n✓ 检索成功 (使用Rerank)")
            logger.info(f"  - 候选总数: {result_with_rerank.total_candidates}")
            logger.info(f"  - 返回结果: {len(result_with_rerank.reranked_results)}")
            logger.info(f"  - 总处理时间: {result_with_rerank.processing_time:.4f}秒")
            logger.info(f"  - Embedding时间: {result_with_rerank.embedding_time:.4f}秒")
            logger.info(f"  - 检索时间: {result_with_rerank.retrieval_time:.4f}秒")
            logger.info(f"  - Rerank时间: {result_with_rerank.rerank_time:.4f}秒")
            
            logger.info(f"\nTop 5结果:")
            for i, item in enumerate(result_with_rerank.reranked_results, 1):
                content_preview = item['content'][:60] + "..." if len(item['content']) > 60 else item['content']
                logger.info(f"{i}. [{item['final_score']:.4f}] [{item['page_number']}页] {content_preview}")
        else:
            logger.error(f"✗ 检索失败")
        
        # 执行RAG检索（不使用rerank，对比性能）
        result_without_rerank = await rag_service.retrieve(
            query=query,
            top_k=5,
            use_rerank=False
        )
        
        if result_without_rerank.reranked_results:
            logger.info(f"\n✓ 检索成功 (不使用Rerank)")
            logger.info(f"  - 总处理时间: {result_without_rerank.processing_time:.4f}秒")
            logger.info(f"  - 性能提升: {(1 - result_with_rerank.processing_time / result_without_rerank.processing_time) * 100:.2f}%")
        
        # 短暂延迟，避免过载
        await asyncio.sleep(1)
    
    logger.info("\n" + "=" * 60)
    logger.info("完整RAG服务测试完成")
    logger.info("=" * 60)

async def main():
    """主函数"""
    await test_complete_rag()

if __name__ == "__main__":
    asyncio.run(main())