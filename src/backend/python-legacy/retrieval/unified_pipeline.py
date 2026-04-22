"""
统一检索管道 - 单库改造后
召回: pgvector similarity + tsvector fulltext
融合: vector + text + rerank
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
    统一检索管道 - 单库改造版
    双路召回: pgvector similarity + tsvector fulltext
    """

    def __init__(self, store: Optional[UnifiedStore] = None):
        self.store = store or UnifiedStore()
        self.request_count = 0
        self.total_latency_ms = 0.0
        self.enable_query_analysis = os.getenv("ENABLE_QUERY_ANALYSIS", "false").lower() == "true"

        self.query_analyzer = QueryAnalysisAgent() if QUERY_ANALYSIS_AVAILABLE else None

        logger.info(f"UnifiedRetrievalPipeline initialized (query_analysis={self.enable_query_analysis})")

    def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        """执行检索"""
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

        latency_ms = (datetime.now() - start_time).total_seconds() * 1000
        self.request_count += 1
        self.total_latency_ms += latency_ms

        stats = {
            "query_analyzed": query_analysis is not None,
            "total_documents": len(documents),
        }

        if query_analysis:
            stats["query_analysis"] = query_analysis.to_dict()

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
        """简单检索 (双路: vector + text)"""
        search_query = SearchQuery(
            query_id=request_id,
            text=request.query,
            session_id=request.session_id,
            mode="hybrid",
            top_k=10,
            filters=request.filters,
        )

        import copy
        config = copy.deepcopy(request.config)
        # 启用双路召回
        config.vector_top_k = 30
        config.keyword_top_k = 20
        config.graph_top_k = 0  # 不再使用图谱

        context = self.store.search(search_query, config)

        documents = []
        for item in context.results:
            if item.chunk:
                score = getattr(item, "final_score", None)
                if score is None:
                    score = getattr(item, "rerank_score", None)
                    if score is None:
                        score = getattr(item, "vector_score", getattr(item, "keyword_score", 0))

                documents.append(
                    RetrievedDocument(
                        doc_id=item.chunk.doc_id,
                        chunk_id=item.chunk.chunk_id,
                        content=item.chunk.content,
                        score=score,
                        metadata={
                            "vector_score": getattr(item, "vector_score", 0),
                            "text_score": getattr(item, "keyword_score", 0),
                            "rerank_score": getattr(item, "rerank_score", 0),
                            "page_number": item.chunk.page_number,
                            "section": getattr(item.chunk, "section", ""),
                        },
                    )
                )

        return documents

    def _retrieve_with_sub_queries(
        self, request: RetrievalRequest, query_analysis: QueryAnalysisResult, request_id: str
    ) -> List[RetrievedDocument]:
        """使用子查询分解进行检索"""
        all_results: List[RetrievedDocument] = []
        seen_chunks = set()

        for sub_q in query_analysis.sub_queries:
            logger.info(f"Executing sub-query [{sub_q.query_id}]: {sub_q.query_text}")

            sub_request = RetrievalRequest(
                query=sub_q.query_text,
                session_id=request.session_id,
                config=request.config,
                filters=request.filters,
            )

            sub_results = self._retrieve_simple(sub_request, f"{request_id}_{sub_q.query_id}")

            for doc in sub_results:
                key = (doc.doc_id, doc.chunk_id)
                if key not in seen_chunks:
                    seen_chunks.add(key)
                    doc.metadata["sub_query_id"] = sub_q.query_id
                    doc.metadata["sub_query_intent"] = sub_q.intent.value
                    all_results.append(doc)

        all_results.sort(key=lambda x: x.score, reverse=True)
        return all_results[:20]

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
