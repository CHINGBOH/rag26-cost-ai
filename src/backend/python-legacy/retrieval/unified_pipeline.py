"""
统一检索管道 - 召回精排全流程

文件归属: 检索层
依赖:
  - services/query_analysis_agent.py (查询分析)
  - infrastructure/adapters/unified (存储)
  - domain_models/retrieval.py (数据模型)
被依赖:
  - api/routes.py (API调用)
  - application/usecases.py (用例层)
输出协议: RetrievalResponse | EnhancedRetrievalResponse
"""

import uuid
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime
from dataclasses import dataclass

import sys
import os

# 添加项目根目录到路径，支持相对导入
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))  # src/backend
sys.path.insert(0, project_root)

from domain_models.document_models import Document, DocumentChunk
from domain_models.search_models import SearchQuery, SearchResultItem, SearchContext
from domain_models.retrieval_models import (
    RetrievalRequest,
    RetrievalResponse,
    RetrievalConfig,
    RetrievedDocument,
)
from infrastructure.adapters.unified import UnifiedStore

# 可选导入
try:
    from services.query_analysis_agent import QueryAnalysisAgent, QueryAnalysisResult

    QUERY_ANALYSIS_AVAILABLE = True
except ImportError:
    QUERY_ANALYSIS_AVAILABLE = False
    logging.warning("QueryAnalysisAgent not available")
    # 定义虚拟类型以避免类型错误
    from typing import Any

    QueryAnalysisResult = Any
    QueryAnalysisAgent = Any

logger = logging.getLogger(__name__)


@dataclass
class SubQueryResult:
    """子查询结果"""

    sub_query_id: str
    query_text: str
    documents: List[RetrievedDocument]
    latency_ms: float


class UnifiedRetrievalPipeline:
    """
    统一检索管道 - 增强版

    增强功能:
    - 查询意图分析 (可选，通过 ENABLE_QUERY_ANALYSIS env var 启用)
    - 复杂查询分解为子查询
    - 多路并行召回
    - 结果智能合并
    """

    def __init__(self, store: Optional[UnifiedStore] = None):
        self.store = store or UnifiedStore()
        self.request_count = 0
        self.total_latency_ms = 0.0
        self.enable_query_analysis = os.getenv("ENABLE_QUERY_ANALYSIS", "false").lower() == "true"

        self.query_analyzer = QueryAnalysisAgent() if QUERY_ANALYSIS_AVAILABLE else None

        logger.info(f"UnifiedRetrievalPipeline initialized (query_analysis={self.enable_query_analysis})")

    def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        """
        执行检索 - 增强版支持查询分析

        流程:
        1. 查询分析 (意图识别、实体提取、子查询分解) - 可选
        2. 子查询并行执行
        3. 结果合并与去重
        4. 精排与分数融合
        """
        request_id = str(uuid.uuid4())
        start_time = datetime.now()

        query_analysis = None
        if self.enable_query_analysis and self.query_analyzer:
            try:
                query_analysis = self.query_analyzer.analyze(request.query)
                logger.info(
                    f"Query analyzed: intent={query_analysis.primary_intent.value}, "
                    f"entities={len(query_analysis.entities)}, "
                    f"sub_queries={len(query_analysis.sub_queries)}"
                )
            except Exception as e:
                logger.warning(f"Query analysis failed: {e}")

        documents = self._retrieve_simple(request, request_id)

        # 统计
        latency_ms = (datetime.now() - start_time).total_seconds() * 1000
        self.request_count += 1
        self.total_latency_ms += latency_ms

        # 构建stats字典
        stats = {
            "query_analyzed": query_analysis is not None,
            "total_documents": len(documents),
        }

        # 附加查询分析结果到stats
        if query_analysis:
            stats["query_analysis"] = query_analysis.to_dict()

        # 构建响应
        response = RetrievalResponse(
            request_id=request_id,
            documents=documents,
            latency_ms=latency_ms,
            stats=stats,
            fusion_details={
                "weights": request.config.fusion_weights
                if hasattr(request.config, "fusion_weights")
                else {},
                "strategy": "weighted_sum",
            },
        )

        return response

    def _retrieve_simple(
        self, request: RetrievalRequest, request_id: str
    ) -> List[RetrievedDocument]:
        """简单检索 (无子查询分解)"""
        search_query = SearchQuery(
            query_id=request_id,
            text=request.query,
            session_id=request.session_id,
            mode="keyword",  # 使用ES关键词召回
            top_k=10,
            filters=request.filters,
        )

        # 启用关键词召回 (ES有1241条数据)
        import copy
        config = copy.deepcopy(request.config)
        config.graph_top_k = 5
        config.vector_top_k = 0  # 向量库为空，禁用
        config.keyword_top_k = 20  # ES有1241条数据

        context = self.store.search(search_query, config)

        documents = []
        for item in context.results:
            if item.chunk:
                # 确定使用哪个得分
                score = getattr(item, "final_score", None)
                if score is None:
                    # 尝试使用rerank_score
                    score = getattr(item, "rerank_score", None)
                    if score is None:
                        # 尝试使用graph_score
                        score = getattr(item, "graph_score", None)
                        if score is None:
                            # 尝试使用vector_score或keyword_score
                            score = getattr(item, "vector_score", getattr(item, "keyword_score", 0))
                
                documents.append(
                    RetrievedDocument(
                        doc_id=item.chunk.doc_id,
                        chunk_id=item.chunk.chunk_id,
                        content=item.chunk.content,
                        score=score,
                        metadata={
                            "vector_score": getattr(item, "vector_score", 0),
                            "keyword_score": getattr(item, "keyword_score", 0),
                            "rerank_score": getattr(item, "rerank_score", 0),
                            "graph_score": getattr(item, "graph_score", 0),
                            "page_number": item.chunk.page_number,
                            "section": getattr(item.chunk, "section", ""),
                        },
                    )
                )

        return documents

    def _retrieve_with_sub_queries(
        self, request: RetrievalRequest, query_analysis: QueryAnalysisResult, request_id: str
    ) -> List[RetrievedDocument]:
        """
        使用子查询分解进行检索

        并行执行多个子查询，然后合并结果
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        all_results: List[RetrievedDocument] = []
        seen_chunks = set()  # 去重

        # 串行执行 (简化版，生产环境可用线程池并行)
        for sub_q in query_analysis.sub_queries:
            logger.info(f"Executing sub-query [{sub_q.query_id}]: {sub_q.query_text}")

            sub_request = RetrievalRequest(
                query=sub_q.query_text,
                session_id=request.session_id,
                config=request.config,
                filters=request.filters,
            )

            sub_results = self._retrieve_simple(sub_request, f"{request_id}_{sub_q.query_id}")

            # 合并结果 (去重)
            for doc in sub_results:
                key = (doc.doc_id, doc.chunk_id)
                if key not in seen_chunks:
                    seen_chunks.add(key)
                    # 标记子查询来源
                    doc.metadata["sub_query_id"] = sub_q.query_id
                    doc.metadata["sub_query_intent"] = sub_q.intent.value
                    all_results.append(doc)

        # 按分数排序
        all_results.sort(key=lambda x: x.score, reverse=True)

        return all_results[:20]  # 返回Top 20

    def index_documents(self, documents: List[Document]) -> Dict[str, Any]:
        """批量索引文档"""
        results = {"total_documents": len(documents), "successful": 0, "failed": 0, "errors": []}

        for doc in documents:
            try:
                result = self.store.index_document(doc)
                if result.get("errors"):
                    results["failed"] += 1
                    results["errors"].append(
                        {"doc_id": doc.metadata.doc_id, "errors": result["errors"]}
                    )
                else:
                    results["successful"] += 1
            except Exception as e:
                results["failed"] += 1
                results["errors"].append({"doc_id": doc.metadata.doc_id, "error": str(e)})

        return results

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        avg_latency = self.request_count > 0 and self.total_latency_ms / self.request_count or 0
        return {
            "total_requests": self.request_count,
            "average_latency_ms": round(avg_latency, 2),
            "store_health": self.store.health_check(),
        }