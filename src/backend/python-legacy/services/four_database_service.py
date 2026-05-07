from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from domain_models.document_models import ChunkType, Document, DocumentMetadata, DocumentType
from domain_models.retrieval_models import RetrievalConfig
from domain_models.search_models import SearchQuery
from infrastructure.adapters.unified import UnifiedStore
from services.document_processor import DocumentProcessor


@dataclass
class FourDatabaseSearchResult:
    chunk_id: str
    content: str
    final_score: float
    source: str
    metadata: dict[str, Any]


@dataclass
class FourDatabaseDocumentResult:
    document_id: str
    total_chunks: int
    embedded_chunks: int
    tables_extracted: int
    entities_extracted: int
    knowledge_graph_nodes: int
    processing_time: float


class FourDatabaseService:
    def __init__(
        self,
        store: Optional[UnifiedStore] = None,
        document_processor: Optional[DocumentProcessor] = None,
    ):
        self.store = store or UnifiedStore()
        self.document_processor = document_processor or DocumentProcessor(self.store)

    async def search_four_databases(
        self,
        *,
        query_text: str,
        top_k: int = 10,
        filters: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._search_four_databases_sync,
            query_text,
            top_k,
            filters or {},
        )

    def _search_four_databases_sync(
        self,
        query_text: str,
        top_k: int,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        query = SearchQuery(
            query_id=str(uuid.uuid4()),
            text=query_text,
            mode="hybrid",
            top_k=top_k,
            filters=filters,
        )
        context = self.store.search(query, RetrievalConfig())
        final_results = [
            FourDatabaseSearchResult(
                chunk_id=result.chunk.chunk_id,
                content=result.chunk.content,
                final_score=result.final_score,
                source=f"{result.chunk.doc_id or 'unknown'}.pdf",
                metadata={
                    "doc_id": result.chunk.doc_id,
                    "page_number": result.chunk.page_number,
                    "section": getattr(result.chunk, "section", ""),
                    "vector_score": result.vector_score,
                    "keyword_score": result.keyword_score,
                    "rerank_score": result.rerank_score,
                },
            )
            for result in context.results
        ]
        return {
            "final_results": final_results,
            "total_candidates": context.total_chunks_searched,
            "search_stats": {
                "latency_ms": context.latency_ms,
                "recall_stats": context.recall_stats,
                "result_count": len(final_results),
            },
        }

    async def process_document(
        self,
        *,
        file_path: str,
        file_name: str,
        ocr_result: dict[str, Any],
    ) -> FourDatabaseDocumentResult:
        return await asyncio.to_thread(self._process_document_sync, file_path, file_name, ocr_result)

    def _process_document_sync(
        self,
        file_path: str,
        file_name: str,
        ocr_result: dict[str, Any],
    ) -> FourDatabaseDocumentResult:
        started_at = time.time()
        document_id = str(uuid.uuid4())
        chunks = self.document_processor._create_chunks(document_id, ocr_result)
        self.document_processor._generate_embeddings(chunks)
        document = Document(
            metadata=DocumentMetadata(
                doc_id=document_id,
                title=file_name or os.path.basename(file_path),
                source=file_path,
                doc_type=DocumentType.PDF,
                total_pages=ocr_result.get("total_pages", 1),
            ),
            chunks=chunks,
            raw_content=ocr_result.get("full_text", ""),
        )
        self.store.index_document(document)
        return FourDatabaseDocumentResult(
            document_id=document_id,
            total_chunks=len(chunks),
            embedded_chunks=sum(1 for chunk in chunks if chunk.embedding is not None),
            tables_extracted=sum(1 for chunk in chunks if chunk.chunk_type == ChunkType.TABLE),
            entities_extracted=0,
            knowledge_graph_nodes=0,
            processing_time=time.time() - started_at,
        )

    async def get_system_statistics(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._get_system_statistics_sync)

    def _get_system_statistics_sync(self) -> dict[str, Any]:
        stats: dict[str, Any] = {
            "health": self.store.health_check(),
            "documents": 0,
            "chunks": 0,
        }
        if not getattr(self.store, "pg_pool", None):
            return stats

        conn = self.store.pg_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM documents")
                stats["documents"] = int((cur.fetchone() or [0])[0] or 0)
                cur.execute("SELECT COUNT(*) FROM text_chunks")
                stats["chunks"] = int((cur.fetchone() or [0])[0] or 0)
        finally:
            self.store.pg_pool.putconn(conn)
        return stats

    async def close(self) -> None:
        self.store.close()


_service: FourDatabaseService | None = None


async def get_four_db_service() -> FourDatabaseService:
    global _service
    if _service is None:
        _service = FourDatabaseService()
    return _service
