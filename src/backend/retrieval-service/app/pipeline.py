"""
统一检索管道 - 召回精排全流程
文件归属: 检索层
"""

import uuid
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime
from dataclasses import dataclass

from domain_models.document import Document, DocumentChunk
from domain_models.search import SearchQuery, SearchResultItem, SearchContext
from domain_models.retrieval import (
    RetrievalRequest,
    RetrievalResponse,
    RetrievalConfig,
    RetrievedDocument,
)
from infrastructure.adapters.unified import UnifiedStore

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
    - 多路并行召回
    - 结果智能合并
    """

    def __init__(self, store: Optional[UnifiedStore] = None):
        self.store = store or UnifiedStore()
        self.request_count = 0
        self.total_latency_ms = 0.0
        logger.info("UnifiedRetrievalPipeline initialized")

    def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        """
        执行检索
        流程:
        1. 直接执行检索
        2. 结果格式化
        """
        request_id = str(uuid.uuid4())
        start_time = datetime.now()

        documents = self._retrieve_simple(request, request_id)

        # 统计
        latency_ms = (datetime.now() - start_time).total_seconds() * 1000
        self.request_count += 1
        self.total_latency_ms += latency_ms

        # 构建响应
        response = RetrievalResponse(
            request_id=request_id,
            documents=documents,
            latency_ms=latency_ms,
            stats={
                "total_documents": len(documents),
            },
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
        """简单检索"""
        search_query = SearchQuery(
            query_id=request_id,
            text=request.query,
            session_id=request.session_id,
            mode="hybrid",
            top_k=10,
            filters=request.filters,
        )

        context = self.store.search(search_query, request.config)

        documents = []
        for item in context.results:
            if item.chunk:
                documents.append(
                    RetrievedDocument(
                        doc_id=item.chunk.doc_id,
                        chunk_id=item.chunk.chunk_id,
                        content=item.chunk.content,
                        score=item.final_score,
                        metadata={
                            "vector_score": getattr(item, "vector_score", 0),
                            "keyword_score": getattr(item, "keyword_score", 0),
                            "rerank_score": getattr(item, "rerank_score", 0),
                            "page_number": item.chunk.page_number,
                            "section": getattr(item.chunk, "section", ""),
                        },
                    )
                )

        return documents

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
