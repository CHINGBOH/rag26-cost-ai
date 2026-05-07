"""
Elasticsearch keyword-search adapter.

Provides BM25-based full-text retrieval over text_chunks using IK Chinese analyzer.
Designed as a drop-in alternative to PG zhparser when KEYWORD_BACKEND=es.

Index schema (chunks_v1):
    chunk_id    keyword       (matches text_chunks.id, e.g. "tc_10433")
    doc_id      keyword
    content     text + ik_max_word (index) / ik_smart (search)
    section     text + ik_smart
    page_number integer
    path        keyword[]     (chapter materialised path)
    depth       integer
    created_at  date
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.runtime_config import read_runtime_config

logger = logging.getLogger(__name__)


_INDEX_MAPPING: Dict[str, Any] = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "analysis": {
            "analyzer": {
                "ik_max": {"type": "ik_max_word"},
                "ik_smart_search": {"type": "ik_smart"},
            }
        },
    },
    "mappings": {
        "properties": {
            "chunk_id": {"type": "keyword"},
            "doc_id": {"type": "keyword"},
            "content": {
                "type": "text",
                "analyzer": "ik_max",
                "search_analyzer": "ik_smart_search",
            },
            "section": {
                "type": "text",
                "analyzer": "ik_smart_search",
            },
            "page_number": {"type": "integer"},
            "path": {"type": "keyword"},
            "depth": {"type": "integer"},
            "created_at": {"type": "date"},
        }
    },
}


def _client():
    """Create a lazy Elasticsearch client. Returns None if package missing."""
    try:
        from elasticsearch import Elasticsearch
    except ImportError:
        logger.warning("[es_store] elasticsearch package not installed")
        return None
    runtime = read_runtime_config()
    return Elasticsearch(
        runtime.elasticsearch_url,
        request_timeout=runtime.elasticsearch_timeout_seconds,
    )


def is_enabled() -> bool:
    """Whether ES backend is selected via env."""
    return read_runtime_config().keyword_backend.lower() == "es"


def health() -> Dict[str, Any]:
    """Probe ES cluster + index. Used by /api/v1/architecture/live and /health."""
    client = _client()
    runtime = read_runtime_config()
    if client is None:
        return {"available": False, "reason": "elasticsearch package not installed"}
    try:
        cluster = client.cluster.health(timeout="3s")
        index_exists = client.indices.exists(index=runtime.elasticsearch_index_name)
        doc_count = 0
        if index_exists:
            doc_count = client.count(index=runtime.elasticsearch_index_name).get("count", 0)
        return {
            "available": True,
            "cluster_status": cluster.get("status"),  # green / yellow / red
            "nodes": cluster.get("number_of_nodes"),
            "index": runtime.elasticsearch_index_name,
            "index_exists": bool(index_exists),
            "doc_count": int(doc_count),
        }
    except Exception as exc:  # pragma: no cover - network
        return {"available": False, "reason": str(exc)}


def ensure_index() -> bool:
    """Create the chunks index with IK analyzers if it does not exist."""
    client = _client()
    runtime = read_runtime_config()
    if client is None:
        return False
    try:
        if client.indices.exists(index=runtime.elasticsearch_index_name):
            return True
        client.indices.create(index=runtime.elasticsearch_index_name, body=_INDEX_MAPPING)
        logger.info("[es_store] created index %s", runtime.elasticsearch_index_name)
        return True
    except Exception as exc:
        logger.error("[es_store] ensure_index failed: %s", exc)
        return False


def bulk_index(docs: List[Dict[str, Any]]) -> int:
    """Bulk-index a batch of chunk docs. Returns successfully indexed count."""
    client = _client()
    runtime = read_runtime_config()
    if client is None or not docs:
        return 0
    try:
        from elasticsearch.helpers import bulk

        actions = [
            {
                "_op_type": "index",
                "_index": runtime.elasticsearch_index_name,
                "_id": d["chunk_id"],
                "_source": d,
            }
            for d in docs
        ]
        success, _ = bulk(client, actions, request_timeout=60, raise_on_error=False)
        return int(success)
    except Exception as exc:
        logger.error("[es_store] bulk_index error: %s", exc)
        return 0


def search(query: str, top_k: int = 10) -> List[Dict[str, Any]]:
    """BM25 search via IK analyzer.

    Returns list of dicts shaped like keyword_search() in tools.py:
        {chunk_id, doc_id, page_number, content, score, source_db, metadata}
    """
    if not query or not query.strip():
        return []
    client = _client()
    runtime = read_runtime_config()
    if client is None:
        return []
    try:
        body = {
            "size": top_k,
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": ["content^2", "section^1.5"],
                    "type": "best_fields",
                    "tie_breaker": 0.3,
                }
            },
            "_source": ["chunk_id", "doc_id", "content", "page_number", "section", "path"],
        }
        resp = client.search(index=runtime.elasticsearch_index_name, body=body)
        hits = resp.get("hits", {}).get("hits", [])
        out: List[Dict[str, Any]] = []
        for h in hits:
            src = h.get("_source", {})
            out.append(
                {
                    "chunk_id": src.get("chunk_id") or h.get("_id"),
                    "doc_id": str(src.get("doc_id") or ""),
                    "page_number": int(src.get("page_number") or 1),
                    "source_db": "elasticsearch",
                    "content": src.get("content") or "",
                    "score": round(float(h.get("_score") or 0.0), 4),
                    "metadata": {
                        "section": src.get("section") or "",
                        "path": src.get("path") or [],
                        "es_score": float(h.get("_score") or 0.0),
                    },
                }
            )
        return out
    except Exception as exc:
        logger.error("[es_store] search error: %s", exc)
        return []


def delete_index() -> bool:
    """Drop the index (for re-creation in scripts/tests)."""
    client = _client()
    runtime = read_runtime_config()
    if client is None:
        return False
    try:
        client.indices.delete(index=runtime.elasticsearch_index_name, ignore_unavailable=True)
        return True
    except Exception as exc:
        logger.error("[es_store] delete_index failed: %s", exc)
        return False
