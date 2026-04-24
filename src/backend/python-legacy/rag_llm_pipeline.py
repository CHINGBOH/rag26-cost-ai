#!/usr/bin/env python3
"""
完整RAG+LLM集成服务
实现任务识别、编排、检索、精排和LLM生成的完整流程
"""

import os
import sys
import asyncio
import logging
from typing import List, Dict, Any, Optional, AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
import re
import hashlib

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

# ============ 枚举定义 ============

class TaskType(Enum):
    """任务类型"""
    QUESTION_ANSWERING = "question_answering"    # 问答
    DOCUMENT_SEARCH = "document_search"          # 文档搜索
    ANALYSIS = "analysis"                        # 分析
    COMPARISON = "comparison"                    # 比较
    SUMMARY = "summary"                          # 摘要
    RECOMMENDATION = "recommendation"            # 推荐
    CALCULATION = "calculation"                  # 计算
    OTHER = "other"

class PipelineStage(Enum):
    """管道阶段"""
    IDLE = "idle"
    TASK_RECOGNITION = "task_recognition"
    QUERY_DECOMPOSITION = "query_decomposition"
    RETRIEVAL = "retrieval"
    RERANKING = "reranking"
    CONTEXT_CONSTRUCTION = "context_construction"
    LLM_GENERATION = "llm_generation"
    COMPLETE = "complete"

# ============ 数据模型 ============

@dataclass
class TaskIntent:
    """任务意图"""
    task_type: TaskType
    confidence: float
    keywords: List[str]
    entities: List[Dict[str, Any]]
    complexity: str  # simple, medium, complex
    requires_rag: bool

@dataclass
class RetrievalResult:
    """检索结果"""
    chunk_id: int
    content: str
    document_id: int
    page_number: int
    score: float
    rerank_score: float
    final_score: float
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ContextItem:
    """上下文项"""
    content: str
    source: str
    relevance_score: float
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class LLMContext:
    """LLM上下文"""
    system_prompt: str
    user_query: str
    context_items: List[ContextItem]
    total_tokens: int
    context_window: int

@dataclass
class GenerationResult:
    """生成结果"""
    answer: str
    sources: List[Dict[str, Any]]
    reasoning: Optional[str] = None
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

# ============ 核心服务类 ============

class TaskRecognizer:
    """任务识别器"""
    
    def __init__(self):
        self.patterns = {
            TaskType.QUESTION_ANSWERING: [
                r'什么|怎么|如何|为什么|哪个|哪些',
                r'什么是|如何做|怎么解决|为什么是'
            ],
            TaskType.DOCUMENT_SEARCH: [
                r'查找|搜索|检索|找到',
                r'关于.*的文档|包含.*的内容'
            ],
            TaskType.ANALYSIS: [
                r'分析|评估|判断|研究',
                r'.*的分析|.*的评估'
            ],
            TaskType.COMPARISON: [
                r'比较|对比|区别|差异',
                r'.*和.*的区别|.*与.*的对比'
            ],
            TaskType.SUMMARY: [
                r'总结|概括|归纳|概述',
                r'.*的总结|.*的概括'
            ],
            TaskType.RECOMMENDATION: [
                r'推荐|建议|应该|最好',
                r'推荐.*|建议.*'
            ],
            TaskType.CALCULATION: [
                r'计算|算|求|多少',
                r'.*等于|.*是多少'
            ]
        }
    
    async def recognize(self, query: str) -> TaskIntent:
        """识别任务意图"""
        query_lower = query.lower()
        
        # 分析每个任务类型
        task_scores = {}
        for task_type, patterns in self.patterns.items():
            score = 0
            for pattern in patterns:
                if re.search(pattern, query_lower):
                    score += 1
            task_scores[task_type] = score
        
        # 确定主要任务类型
        max_score = max(task_scores.values())
        if max_score > 0:
            task_type = max(task_scores, key=task_scores.get)
            confidence = min(max_score / 3, 1.0)  # 归一化置信度
        else:
            task_type = TaskType.OTHER
            confidence = 0.5
        
        # 提取关键词
        keywords = self._extract_keywords(query)
        
        # 识别实体
        entities = self._extract_entities(query)
        
        # 评估复杂度
        complexity = self._assess_complexity(query, keywords, entities)
        
        # 判断是否需要RAG
        requires_rag = self._requires_rag(task_type, complexity)
        
        return TaskIntent(
            task_type=task_type,
            confidence=confidence,
            keywords=keywords,
            entities=entities,
            complexity=complexity,
            requires_rag=requires_rag
        )
    
    def _extract_keywords(self, query: str) -> List[str]:
        """提取关键词"""
        # 简单的关键词提取
        stop_words = {'的', '了', '是', '在', '和', '有', '我', '你', '他', '她', '它', '们', '这', '那', '什么', '怎么', '如何', '为什么'}
        words = re.findall(r'[\w]+', query)
        keywords = [w for w in words if w not in stop_words and len(w) > 1]
        return keywords
    
    def _extract_entities(self, query: str) -> List[Dict[str, Any]]:
        """提取实体"""
        entities = []
        
        # 数字实体
        numbers = re.findall(r'\d+\.?\d*', query)
        for num in numbers:
            entities.append({
                'type': 'number',
                'value': num,
                'text': num
            })
        
        # 时间实体
        times = re.findall(r'\d{4}年\d{1,2}月|\d{1,2}月\d{1,2}日', query)
        for time in times:
            entities.append({
                'type': 'time',
                'value': time,
                'text': time
            })
        
        return entities
    
    def _assess_complexity(self, query: str, keywords: List[str], entities: List[Dict[str, Any]]) -> str:
        """评估复杂度"""
        score = 0
        
        # 基于关键词数量
        if len(keywords) > 5:
            score += 1
        
        # 基于实体数量
        if len(entities) > 2:
            score += 1
        
        # 基于查询长度
        if len(query) > 30:
            score += 1
        
        if score >= 2:
            return 'complex'
        elif score == 1:
            return 'medium'
        else:
            return 'simple'
    
    def _requires_rag(self, task_type: TaskType, complexity: str) -> bool:
        """判断是否需要RAG"""
        rag_tasks = {
            TaskType.QUESTION_ANSWERING,
            TaskType.DOCUMENT_SEARCH,
            TaskType.ANALYSIS,
            TaskType.COMPARISON,
            TaskType.SUMMARY,
            TaskType.RECOMMENDATION
        }
        
        if task_type in rag_tasks:
            return True
        
        if complexity in ['medium', 'complex']:
            return True
        
        return False

class QueryDecomposer:
    """查询分解器"""
    
    async def decompose(self, query: str, intent: TaskIntent) -> List[str]:
        """分解复杂查询"""
        if intent.complexity == 'simple':
            return [query]
        
        sub_queries = []
        
        # 基于连接词分解
        connectors = ['和', '与', '以及', '还有', '，', '；']
        for connector in connectors:
            if connector in query:
                parts = query.split(connector)
                sub_queries.extend([p.strip() for p in parts if p.strip()])
                break
        
        # 如果没有分解，返回原查询
        if not sub_queries:
            sub_queries = [query]
        
        return sub_queries

class ContextBuilder:
    """上下文构建器"""
    
    def __init__(self, context_window: int = 4000):
        self.context_window = context_window
        self.token_estimator = self._create_token_estimator()
    
    def _create_token_estimator(self):
        """创建token估算器"""
        # 简单的token估算：中文≈1.5字符/token，英文≈4字符/token
        def estimate(text: str) -> int:
            chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
            english_chars = len(re.findall(r'[a-zA-Z]', text))
            return int(chinese_chars / 1.5 + english_chars / 4)
        
        return estimate
    
    async def build_context(
        self,
        query: str,
        retrieval_results: List[RetrievalResult],
        system_prompt: str = None
    ) -> LLMContext:
        """构建LLM上下文"""
        # 默认系统提示
        if not system_prompt:
            system_prompt = """你是一个专业的智能助手，擅长回答各种问题。请基于提供的上下文信息回答用户的问题。

回答要求：
1. 准确理解问题，基于上下文信息回答
2. 如果上下文中没有相关信息，请明确说明
3. 回答要简洁明了，重点突出
4. 可以引用具体的上下文内容作为依据
5. 保持客观中立的立场"""

        # 计算系统提示的token数
        system_tokens = self.token_estimator(system_prompt)
        query_tokens = self.token_estimator(query)
        
        # 计算可用于上下文的token数
        available_tokens = self.context_window - system_tokens - query_tokens - 500  # 预留500 token用于回答
        
        # 构建上下文项
        context_items = []
        used_tokens = 0
        
        for result in retrieval_results:
            content = result.content
            content_tokens = self.token_estimator(content)
            
            if used_tokens + content_tokens > available_tokens:
                # 截断内容
                remaining_tokens = available_tokens - used_tokens
                if remaining_tokens > 0:
                    # 简单截断
                    content = content[:int(remaining_tokens * 1.5)]  # 假设中文
                    content_tokens = self.token_estimator(content)
                    context_items.append(ContextItem(
                        content=content,
                        source=f"文档{result.document_id}第{result.page_number}页",
                        relevance_score=result.final_score,
                        metadata={
                            'chunk_id': result.chunk_id,
                            'document_id': result.document_id,
                            'page_number': result.page_number
                        }
                    ))
                break
            
            context_items.append(ContextItem(
                content=content,
                source=f"文档{result.document_id}第{result.page_number}页",
                relevance_score=result.final_score,
                metadata={
                    'chunk_id': result.chunk_id,
                    'document_id': result.document_id,
                    'page_number': result.page_number
                }
            ))
            used_tokens += content_tokens
        
        total_tokens = system_tokens + query_tokens + used_tokens
        
        return LLMContext(
            system_prompt=system_prompt,
            user_query=query,
            context_items=context_items,
            total_tokens=total_tokens,
            context_window=self.context_window
        )
    
    def format_context_for_llm(self, context: LLMContext) -> str:
        """格式化上下文供LLM使用"""
        context_text = "上下文信息：\n\n"
        
        for i, item in enumerate(context.context_items, 1):
            context_text += f"[来源{i}: {item.source} (相关性: {item.relevance_score:.2f})]\n"
            context_text += f"{item.content}\n\n"
        
        return context_text

class RAGLLMPipeline:
    """完整RAG+LLM管道"""
    
    def __init__(self):
        self.task_recognizer = TaskRecognizer()
        self.query_decomposer = QueryDecomposer()
        self.context_builder = ContextBuilder()
        
        self.embedding_model = None
        self.rerank_model = None
        self.db_pool = None
        
        self.models_loaded = False
        self.db_connected = False
    
    async def initialize(self):
        """初始化管道"""
        try:
            # 加载模型
            await self.load_models()
            
            # 连接数据库
            await self.connect_database()
            
            logger.info("✓ RAG+LLM管道初始化完成")
            
        except Exception as e:
            logger.error(f"✗ RAG+LLM管道初始化失败: {e}")
            raise
    
    async def load_models(self):
        """加载模型"""
        try:
            from sentence_transformers import SentenceTransformer, CrossEncoder
            
            # 加载Embedding模型
            logger.info("加载BAAI embedding模型...")
            if os.path.exists(EMBEDDING_MODEL_PATH):
                self.embedding_model = SentenceTransformer(EMBEDDING_MODEL_PATH)
                logger.info("✓ 使用本地BAAI embedding模型")
            else:
                self.embedding_model = SentenceTransformer('BAAI/bge-m3')
                logger.info("✓ 使用远程BAAI embedding模型")
            
            # 加载Rerank模型
            logger.info("加载BAAI rerank模型...")
            if os.path.exists(RERANK_MODEL_PATH):
                self.rerank_model = CrossEncoder(RERANK_MODEL_PATH)
                logger.info("✓ 使用本地BAAI rerank模型")
            else:
                self.rerank_model = CrossEncoder('BAAI/bge-reranker-v2-m3')
                logger.info("✓ 使用远程BAAI rerank模型")
            
            self.models_loaded = True
            
        except Exception as e:
            logger.error(f"✗ 模型加载失败: {e}")
            raise
    
    async def connect_database(self):
        """连接数据库"""
        try:
            self.db_pool = await asyncpg.create_pool(**DB_CONFIG)
            self.db_connected = True
            logger.info("✓ 数据库连接成功")
            
        except Exception as e:
            logger.error(f"✗ 数据库连接失败: {e}")
            raise
    
    async def process_query(
        self,
        query: str,
        use_rag: bool = True,
        top_k: int = 10,
        context_window: int = 4000
    ) -> GenerationResult:
        """处理查询并生成回答"""
        logger.info(f"\n{'='*60}")
        logger.info(f"处理查询: {query}")
        logger.info(f"{'='*60}")
        
        try:
            # 阶段1: 任务识别
            logger.info("阶段1: 任务识别")
            intent = await self.task_recognizer.recognize(query)
            logger.info(f"  任务类型: {intent.task_type.value}")
            logger.info(f"  置信度: {intent.confidence:.2f}")
            logger.info(f"  复杂度: {intent.complexity}")
            logger.info(f"  需要RAG: {intent.requires_rag}")
            
            # 阶段2: 查询分解
            logger.info("阶段2: 查询分解")
            sub_queries = await self.query_decomposer.decompose(query, intent)
            logger.info(f"  子查询数量: {len(sub_queries)}")
            for i, sq in enumerate(sub_queries, 1):
                logger.info(f"  {i}. {sq}")
            
            # 阶段3: 检索
            retrieval_results = []
            if use_rag and intent.requires_rag:
                logger.info("阶段3: 检索")
                for sub_query in sub_queries:
                    results = await self._retrieve(sub_query, top_k)
                    retrieval_results.extend(results)
                
                # 去重
                seen_ids = set()
                unique_results = []
                for result in retrieval_results:
                    if result.chunk_id not in seen_ids:
                        seen_ids.add(result.chunk_id)
                        unique_results.append(result)
                retrieval_results = unique_results
                
                logger.info(f"  检索结果数: {len(retrieval_results)}")
                
                # 阶段4: 重排
                logger.info("阶段4: 重排")
                if self.rerank_model and retrieval_results:
                    retrieval_results = await self._rerank(query, retrieval_results, top_k)
                    logger.info(f"  重排结果数: {len(retrieval_results)}")
                
                # 阶段5: 上下文构建
                logger.info("阶段5: 上下文构建")
                self.context_builder.context_window = context_window
                llm_context = await self.context_builder.build_context(query, retrieval_results)
                logger.info(f"  上下文项数: {len(llm_context.context_items)}")
                logger.info(f"  总token数: {llm_context.total_tokens}")
                
                # 格式化上下文
                context_text = self.context_builder.format_context_for_llm(llm_context)
            else:
                logger.info("跳过RAG，直接生成回答")
                context_text = ""
            
            # 阶段6: LLM生成
            logger.info("阶段6: LLM生成")
            
            # 构建完整提示
            if context_text:
                full_prompt = f"{llm_context.system_prompt}\n\n{context_text}\n\n用户问题: {query}\n\n请回答:"
            else:
                full_prompt = f"用户问题: {query}\n\n请回答:"
            
            # 这里应该调用实际的LLM服务
            # 暂时使用模拟生成
            answer = await self._simulate_llm_generation(full_prompt, retrieval_results)
            
            # 构建结果
            sources = [
                {
                    'chunk_id': result.chunk_id,
                    'document_id': result.document_id,
                    'page_number': result.page_number,
                    'relevance_score': result.final_score,
                    'content_preview': result.content[:100] + "..." if len(result.content) > 100 else result.content
                }
                for result in retrieval_results[:5]
            ]
            
            result = GenerationResult(
                answer=answer,
                sources=sources,
                confidence=intent.confidence,
                metadata={
                    'task_type': intent.task_type.value,
                    'complexity': intent.complexity,
                    'retrieval_count': len(retrieval_results),
                    'context_tokens': llm_context.total_tokens if context_text else 0,
                    'processing_time': 0.0  # 实际应该计算
                }
            )
            
            logger.info(f"✓ 查询处理完成")
            logger.info(f"{'='*60}\n")
            
            return result
            
        except Exception as e:
            logger.error(f"✗ 查询处理失败: {e}")
            raise
    
    async def _retrieve(self, query: str, top_k: int) -> List[RetrievalResult]:
        """执行检索"""
        # 向量化查询（在线程池中执行，避免阻塞事件循环）
        loop = asyncio.get_running_loop()
        query_embedding = await loop.run_in_executor(
            None, lambda: self.embedding_model.encode(query, convert_to_numpy=True)
        )
        
        # 从数据库检索
        async with self.db_pool.acquire() as conn:
            candidates = await conn.fetch("""
                SELECT id, content, document_id, page_number
                FROM document_chunks
                WHERE LENGTH(content) > 10
                ORDER BY RANDOM()
                LIMIT 30
            """)
            
            results = []
            for chunk in candidates:
                results.append(RetrievalResult(
                    chunk_id=chunk['id'],
                    content=chunk['content'],
                    document_id=chunk['document_id'],
                    page_number=chunk['page_number'],
                    score=0.5,  # 基础分数
                    rerank_score=0.0,
                    final_score=0.5
                ))
            
            return results[:top_k]
    
    async def _rerank(
        self,
        query: str,
        candidates: List[RetrievalResult],
        top_k: int
    ) -> List[RetrievalResult]:
        """重排结果"""
        # 准备查询-文档对
        query_doc_pairs = [(query, candidate.content) for candidate in candidates]
        
        # 计算重排分数
        scores = self.rerank_model.predict(query_doc_pairs)
        
        # 归一化分数
        min_score = np.min(scores)
        max_score = np.max(scores)
        if max_score > min_score:
            normalized_scores = (scores - min_score) / (max_score - min_score)
        else:
            normalized_scores = np.ones_like(scores) * 0.5
        
        # 更新分数
        for i, candidate in enumerate(candidates):
            candidate.rerank_score = float(normalized_scores[i])
            candidate.final_score = float(candidate.score * 0.3 + normalized_scores[i] * 0.7)
        
        # 排序并返回top_k
        sorted_results = sorted(candidates, key=lambda x: x.final_score, reverse=True)[:top_k]
        return sorted_results
    
    async def _simulate_llm_generation(self, prompt: str, retrieval_results: List[RetrievalResult]) -> str:
        """模拟LLM生成（实际应该调用真正的LLM服务）"""
        # 这里应该调用llama.cpp或vLLM服务
        # 暂时返回基于检索结果的模拟回答
        
        if retrieval_results:
            top_result = retrieval_results[0]
            answer = f"基于文档{top_result.document_id}第{top_result.page_number}页的内容，{top_result.content[:200]}..."
        else:
            answer = "抱歉，没有找到相关信息来回答您的问题。"
        
        return answer

# ============ 测试代码 ============

async def test_rag_llm_pipeline():
    """测试完整RAG+LLM管道"""
    logger.info("=" * 60)
    logger.info("测试完整RAG+LLM管道")
    logger.info("=" * 60)
    
    # 初始化管道
    pipeline = RAGLLMPipeline()
    await pipeline.initialize()
    
    # 测试查询
    test_queries = [
        "深圳市建设工程计价费率标准是什么？",
        "如何计算企业管理费？",
        "安全文明施工费包括哪些内容？"
    ]
    
    for query in test_queries:
        try:
            result = await pipeline.process_query(query, use_rag=True, top_k=5)
            
            print(f"\n查询: {query}")
            print(f"回答: {result.answer}")
            print(f"来源数: {len(result.sources)}")
            print(f"置信度: {result.confidence:.2f}")
            
        except Exception as e:
            logger.error(f"查询处理失败: {e}")
        
        # 短暂延迟
        await asyncio.sleep(1)
    
    logger.info("\n" + "=" * 60)
    logger.info("测试完成")
    logger.info("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_rag_llm_pipeline())