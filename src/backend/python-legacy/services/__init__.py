#!/usr/bin/env python3
"""
Services module
Provides all backend services for the RAG system
"""

from services.embedding_service import EmbeddingService, get_embedding_service
try:
    from services.four_database_service import FourDatabaseService, get_four_db_service
except ImportError:
    pass  # four_database_service not yet available
from services.rerank_service import RerankService, get_rerank_service
from services.llm_service import UnifiedLLMService, get_llm_service, Message
from services.model_caller import UnifiedModelCaller, get_model_caller

__all__ = [
    "EmbeddingService",
    "get_embedding_service",
    "FourDatabaseService",
    "get_four_db_service",
    "RerankService",
    "get_rerank_service",
    "UnifiedLLMService",
    "get_llm_service",
    "Message",
    "UnifiedModelCaller",
    "get_model_caller",
]