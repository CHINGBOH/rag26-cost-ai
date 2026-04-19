#!/usr/bin/env python3
"""
Rerank服务 - 精确重排服务
对召回结果进行精确重排，提高相关性
支持多种rerank模型和特征融合
"""

import os
import asyncio
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

from sentence_transformers import CrossEncoder
import numpy as np

# 配置
RERANK_MODEL_NAME = os.getenv("RERANK_MODEL_NAME", "cross-encoder/ms-marco-MiniLM-L-12-v2")
BATCH_SIZE = int(os.getenv("RERANK_BATCH_SIZE", "16"))

# 日志配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class RerankResult:
    """重排结果"""
    chunk_id: str
    original_score: float
    rerank_score: float
    final_score: float
    content: str
    source: str
    metadata: Dict[str, Any]

@dataclass
class RerankStats:
    """重排统计"""
    total_candidates: int
    reranked_count: int
    processing_time: float
    score_improvement: float
    top_k_changed: int

class RerankService:
    """Rerank服务"""
    
    def __init__(self):
        self.rerank_model = None
        self.feature_weights = {
            'vector_score': 0.3,
            'rerank_score': 0.5,
            'keyword_score': 0.1,
            'graph_score': 0.1
        }
        
    async def initialize(self):
        """初始化Rerank服务"""
        logger.info("初始化Rerank服务...")
        
        # 加载Rerank模型
        logger.info(f"加载Rerank模型: {RERANK_MODEL_NAME}")
        try:
            self.rerank_model = CrossEncoder(RERANK_MODEL_NAME)
            logger.info("✓ Rerank模型加载成功")
        except Exception as e:
            logger.error(f"加载Rerank模型失败: {e}")
            # 使用简单的重排逻辑
            self.rerank_model = None
            logger.warning("使用简单重排逻辑")
        
        logger.info("Rerank服务初始化完成")
    
    async def rerank(
        self,
        query_text: str,
        candidates: List[Dict[str, Any]],
        top_k: int = 10
    ) -> List[RerankResult]:
        """重排候选结果"""
        start_time = datetime.now()
        
        try:
            if not candidates:
                return []
            
            # 1. 准备候选结果
            prepared_candidates = self._prepare_candidates(candidates)
            
            # 2. 计算Rerank分数
            if self.rerank_model:
                rerank_scores = await self._compute_rerank_scores(
                    query_text, prepared_candidates
                )
            else:
                rerank_scores = self._compute_simple_scores(query_text, prepared_candidates)
            
            # 3. 特征融合
            final_results = self._feature_fusion(
                prepared_candidates, rerank_scores
            )
            
            # 4. 排序并返回top_k
            sorted_results = sorted(
                final_results, 
                key=lambda x: x.final_score, 
                reverse=True
            )[:top_k]
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            logger.info(f"重排完成: {len(candidates)}个候选 -> {len(sorted_results)}个结果, 耗时{processing_time:.2f}秒")
            
            return sorted_results
            
        except Exception as e:
            logger.error(f"重排失败: {e}")
            raise
    
    def _prepare_candidates(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """准备候选结果"""
        prepared = []
        
        for candidate in candidates:
            prepared.append({
                'chunk_id': candidate.get('chunk_id', ''),
                'original_score': float(candidate.get('score', 0)),
                'content': candidate.get('content', ''),
                'source': candidate.get('source', 'unknown'),
                'metadata': candidate.get('metadata', {})
            })
        
        return prepared
    
    async def _compute_rerank_scores(
        self,
        query_text: str,
        candidates: List[Dict[str, Any]]
    ) -> List[float]:
        """使用Rerank模型计算分数"""
        try:
            # 准备查询-文档对
            query_doc_pairs = [
                (query_text, candidate['content'])
                for candidate in candidates
            ]
            
            # 批量计算分数
            scores = self.rerank_model.predict(query_doc_pairs)
            
            # 归一化分数到0-1
            scores = self._normalize_scores(scores)
            
            return scores.tolist()
            
        except Exception as e:
            logger.error(f"计算Rerank分数失败: {e}")
            return [0.0] * len(candidates)
    
    def _compute_simple_scores(
        self,
        query_text: str,
        candidates: List[Dict[str, Any]]
    ) -> List[float]:
        """简单重排逻辑（无模型时使用）"""
        scores = []
        query_tokens = set(query_text.split())
        
        for candidate in candidates:
            content = candidate['content']
            content_tokens = set(content.split())
            
            # 计算重叠度
            overlap = len(query_tokens & content_tokens)
            total = len(query_tokens | content_tokens)
            
            # Jaccard相似度
            score = overlap / total if total > 0 else 0
            
            # 考虑原始分数
            original_score = candidate['original_score']
            final_score = score * 0.7 + original_score * 0.3
            
            scores.append(final_score)
        
        return self._normalize_scores(scores).tolist()
    
    def _normalize_scores(self, scores: np.ndarray) -> np.ndarray:
        """归一化分数"""
        if len(scores) == 0:
            return scores
        
        # Min-Max归一化
        min_score = np.min(scores)
        max_score = np.max(scores)
        
        if max_score == min_score:
            return np.ones_like(scores) * 0.5
        
        normalized = (scores - min_score) / (max_score - min_score)
        
        return normalized
    
    def _feature_fusion(
        self,
        candidates: List[Dict[str, Any]],
        rerank_scores: List[float]
    ) -> List[RerankResult]:
        """特征融合"""
        results = []
        
        for i, candidate in enumerate(candidates):
            # 获取各特征分数
            vector_score = candidate['original_score']
            rerank_score = rerank_scores[i]
            
            # 根据来源类型分配分数
            source = candidate['source']
            if source == 'vector':
                keyword_score = 0.0
                graph_score = 0.0
            elif source == 'graph':
                keyword_score = 0.0
                graph_score = candidate['original_score']
            elif source == 'keyword':
                keyword_score = candidate['original_score']
                graph_score = 0.0
            elif source == 'structured':
                keyword_score = candidate['original_score']
                graph_score = 0.0
            else:
                keyword_score = 0.0
                graph_score = 0.0
            
            # 加权融合
            final_score = (
                vector_score * self.feature_weights['vector_score'] +
                rerank_score * self.feature_weights['rerank_score'] +
                keyword_score * self.feature_weights['keyword_score'] +
                graph_score * self.feature_weights['graph_score']
            )
            
            results.append(RerankResult(
                chunk_id=candidate['chunk_id'],
                original_score=vector_score,
                rerank_score=rerank_score,
                final_score=final_score,
                content=candidate['content'],
                source=source,
                metadata=candidate['metadata']
            ))
        
        return results
    
    async def rerank_with_filters(
        self,
        query_text: str,
        candidates: List[Dict[str, Any]],
        filters: Dict[str, Any],
        top_k: int = 10
    ) -> List[RerankResult]:
        """带过滤条件的重排"""
        try:
            # 1. 应用过滤条件
            filtered_candidates = self._apply_filters(candidates, filters)
            
            # 2. 重排
            reranked = await self.rerank(query_text, filtered_candidates, top_k)
            
            return reranked
            
        except Exception as e:
            logger.error(f"带过滤重排失败: {e}")
            raise
    
    def _apply_filters(
        self,
        candidates: List[Dict[str, Any]],
        filters: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """应用过滤条件"""
        filtered = []
        
        for candidate in candidates:
            # 检查元数据
            metadata = candidate.get('metadata', {})
            
            # 检查文档类型过滤
            if 'document_type' in filters:
                if metadata.get('document_type') != filters['document_type']:
                    continue
            
            # 检查页码范围过滤
            if 'page_range' in filters:
                page_num = metadata.get('page_number', 0)
                min_page, max_page = filters['page_range']
                if not (min_page <= page_num <= max_page):
                    continue
            
            # 检查置信度过滤
            if 'min_confidence' in filters:
                confidence = metadata.get('confidence', 0)
                if confidence < filters['min_confidence']:
                    continue
            
            # 检查日期范围过滤
            if 'date_range' in filters:
                date_str = metadata.get('created_at', '')
                if date_str:
                    try:
                        import datetime
                        date_obj = datetime.datetime.fromisoformat(date_str)
                        min_date, max_date = filters['date_range']
                        if not (min_date <= date_obj <= max_date):
                            continue
                    except Exception:
                        pass
            
            filtered.append(candidate)
        
        return filtered
    
    async def batch_rerank(
        self,
        queries: List[str],
        candidates_list: List[List[Dict[str, Any]]],
        top_k: int = 10
    ) -> List[List[RerankResult]]:
        """批量重排"""
        try:
            results = []
            
            for query, candidates in zip(queries, candidates_list):
                reranked = await self.rerank(query, candidates, top_k)
                results.append(reranked)
            
            return results
            
        except Exception as e:
            logger.error(f"批量重排失败: {e}")
            raise
    
    async def evaluate_rerank(
        self,
        query_text: str,
        candidates: List[Dict[str, Any]],
        relevant_ids: List[str],
        top_k: int = 10
    ) -> Dict[str, Any]:
        """评估重排效果"""
        try:
            # 重排
            reranked = await self.rerank(query_text, candidates, top_k)
            
            # 提取top_k的chunk_id
            top_k_ids = [result.chunk_id for result in reranked[:top_k]]
            
            # 计算评估指标
            metrics = self._compute_metrics(top_k_ids, relevant_ids)
            
            return metrics
            
        except Exception as e:
            logger.error(f"评估重排效果失败: {e}")
            raise
    
    def _compute_metrics(
        self,
        predicted_ids: List[str],
        relevant_ids: List[str]
    ) -> Dict[str, Any]:
        """计算评估指标"""
        metrics = {}
        
        # Precision@K
        relevant_count = sum(1 for pid in predicted_ids if pid in relevant_ids)
        metrics[f'precision@{len(predicted_ids)}'] = relevant_count / len(predicted_ids) if predicted_ids else 0
        
        # Recall@K
        relevant_retrieved = sum(1 for rid in relevant_ids if rid in predicted_ids)
        metrics[f'recall@{len(predicted_ids)}'] = relevant_retrieved / len(relevant_ids) if relevant_ids else 0
        
        # MRR (Mean Reciprocal Rank)
        mrr = 0.0
        for i, pid in enumerate(predicted_ids):
            if pid in relevant_ids:
                mrr = 1.0 / (i + 1)
                break
        metrics['mrr'] = mrr
        
        # NDCG@K
        dcg = 0.0
        for i, pid in enumerate(predicted_ids):
            if pid in relevant_ids:
                dcg += 1.0 / np.log2(i + 2)
        
        # 计算理想DCG
        ideal_dcg = sum(1.0 / np.log2(i + 2) for i in range(min(len(relevant_ids), len(predicted_ids))))
        
        metrics[f'ndcg@{len(predicted_ids)}'] = dcg / ideal_dcg if ideal_dcg > 0 else 0
        
        return metrics
    
    def update_feature_weights(self, weights: Dict[str, float]):
        """更新特征权重"""
        total_weight = sum(weights.values())
        
        # 归一化权重
        for key in weights:
            weights[key] = weights[key] / total_weight
        
        self.feature_weights = weights
        logger.info(f"特征权重已更新: {self.feature_weights}")
    
    def get_feature_weights(self) -> Dict[str, float]:
        """获取当前特征权重"""
        return self.feature_weights.copy()

class AdvancedRerankService(RerankService):
    """高级Rerank服务，支持更多特性"""
    
    async def initialize(self):
        """初始化高级Rerank服务"""
        await super().initialize()
        logger.info("高级Rerank服务初始化完成")
    
    async def rerank_with_diversity(
        self,
        query_text: str,
        candidates: List[Dict[str, Any]],
        top_k: int = 10,
        diversity_weight: float = 0.3
    ) -> List[RerankResult]:
        """带多样性的重排"""
        try:
            # 1. 基础重排
            base_results = await self.rerank(query_text, candidates, top_k * 2)
            
            # 2. 计算多样性
            diverse_results = self._apply_diversity(
                base_results, top_k, diversity_weight
            )
            
            return diverse_results
            
        except Exception as e:
            logger.error(f"带多样性重排失败: {e}")
            raise
    
    def _apply_diversity(
        self,
        results: List[RerankResult],
        top_k: int,
        diversity_weight: float
    ) -> List[RerankResult]:
        """应用多样性"""
        selected = []
        remaining = results.copy()
        
        while len(selected) < top_k and remaining:
            # 选择最佳候选
            best_idx = 0
            best_score = -float('inf')
            
            for i, candidate in enumerate(remaining):
                # 基础分数
                base_score = candidate.final_score
                
                # 多样性惩罚
                diversity_penalty = 0.0
                for selected_item in selected:
                    similarity = self._compute_similarity(
                        candidate.content, selected_item.content
                    )
                    diversity_penalty += similarity
                
                # 最终分数
                final_score = base_score * (1 - diversity_weight) - diversity_penalty * diversity_weight
                
                if final_score > best_score:
                    best_score = final_score
                    best_idx = i
            
            # 选择最佳候选
            selected.append(remaining.pop(best_idx))
        
        return selected
    
    def _compute_similarity(self, text1: str, text2: str) -> float:
        """计算文本相似度"""
        try:
            # 简单的Jaccard相似度
            set1 = set(text1.split())
            set2 = set(text2.split())
            
            intersection = len(set1 & set2)
            union = len(set1 | set2)
            
            return intersection / union if union > 0 else 0
            
        except Exception as e:
            logger.error(f"计算相似度失败: {e}")
            return 0.0

# 全局实例
rerank_service = RerankService()
advanced_rerank_service = AdvancedRerankService()

async def get_rerank_service() -> RerankService:
    """获取Rerank服务实例"""
    if rerank_service.rerank_model is None:
        await rerank_service.initialize()
    return rerank_service

async def get_advanced_rerank_service() -> AdvancedRerankService:
    """获取高级Rerank服务实例"""
    if advanced_rerank_service.rerank_model is None:
        await advanced_rerank_service.initialize()
    return advanced_rerank_service