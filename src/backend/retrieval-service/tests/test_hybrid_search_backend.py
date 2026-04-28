import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.agent import tools


class EmptyCursor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None) -> None:
        self.query = query
        self.params = params

    def fetchall(self):
        return []


class EmptyConn:
    def cursor(self):
        return EmptyCursor()

    def rollback(self):
        return None


def test_hybrid_search_prefers_milvus_dense_leg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tools,
        "AppConfig",
        lambda: SimpleNamespace(vector_store=SimpleNamespace(type="milvus")),
    )
    monkeypatch.setattr(
        tools,
        "_milvus_vector_results",
        lambda query, top_k: [
            {
                "chunk_id": "milvus-h1",
                "doc_id": "doc-m1",
                "page_number": 5,
                "source_db": "milvus",
                "content": "Milvus dense hit",
                "score": 0.82,
                "metadata": {},
                "retrieval_path": "vector",
            }
        ],
    )
    monkeypatch.setattr(tools, "_get_embedding", lambda text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(tools, "_get_pg_conn", lambda: EmptyConn())
    monkeypatch.setattr(tools, "_put_pg_conn", lambda conn: None)
    monkeypatch.setattr(tools, "_table_available", lambda conn, name: False)
    monkeypatch.setattr(tools, "_resolve_text_search_config", lambda conn: "chinese")
    monkeypatch.setattr(tools, "_table_has_column", lambda conn, table, column: False)
    monkeypatch.setattr(tools, "_rrf_fuse_chunks", lambda ranked_lists, rank_constant=60: ranked_lists[0])
    monkeypatch.setattr(tools, "_query_fee_formula_text_chunks", lambda conn, query, top_k=10: [])
    monkeypatch.setattr(tools, "_query_fee_comparison_text_chunks", lambda conn, query, top_k=10: [])
    monkeypatch.setattr(tools, "_query_appendix_standard_text_chunks", lambda conn, query, top_k=10: [])
    monkeypatch.setattr(tools, "_query_fill_requirement_text_chunks", lambda conn, query, top_k=10: [])
    monkeypatch.setattr(tools, "_query_text_chunks_literal", lambda conn, query, top_k=10: [])
    monkeypatch.setattr(tools, "_should_include_structured_tables", lambda query: False)

    result = json.loads(tools.hybrid_search.func("企业管理费计算规则", top_k=3))

    assert result[0]["source_db"] == "hybrid_vector"
    assert result[0]["metadata"]["vector_backend"] == "milvus"
    assert result[0]["retrieval_path"] == "vector"


def test_hybrid_search_keeps_pgvector_when_path_constraint_present(monkeypatch: pytest.MonkeyPatch) -> None:
    class PgCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params=None) -> None:
            self.query = query
            self.params = params

        def fetchall(self):
            if "embedding <=>" in self.query:
                return [(11, "doc-pg", 8, "PG scoped vector hit", 0.79)]
            return []

    class PgConn:
        def cursor(self):
            return PgCursor()

        def rollback(self):
            return None

    monkeypatch.setattr(
        tools,
        "AppConfig",
        lambda: SimpleNamespace(vector_store=SimpleNamespace(type="milvus")),
    )
    monkeypatch.setattr(
        tools,
        "_milvus_vector_results",
        lambda query, top_k: (_ for _ in ()).throw(AssertionError("milvus helper should be skipped when path is constrained")),
    )
    monkeypatch.setattr(tools, "_get_embedding", lambda text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(tools, "_get_pg_conn", lambda: PgConn())
    monkeypatch.setattr(tools, "_put_pg_conn", lambda conn: None)
    monkeypatch.setattr(tools, "_table_available", lambda conn, name: False)
    monkeypatch.setattr(tools, "_resolve_text_search_config", lambda conn: "chinese")
    monkeypatch.setattr(tools, "_table_has_column", lambda conn, table, column: False)
    monkeypatch.setattr(tools, "_rrf_fuse_chunks", lambda ranked_lists, rank_constant=60: ranked_lists[0])
    monkeypatch.setattr(tools, "_query_fee_formula_text_chunks", lambda conn, query, top_k=10: [])
    monkeypatch.setattr(tools, "_query_fee_comparison_text_chunks", lambda conn, query, top_k=10: [])
    monkeypatch.setattr(tools, "_query_appendix_standard_text_chunks", lambda conn, query, top_k=10: [])
    monkeypatch.setattr(tools, "_query_fill_requirement_text_chunks", lambda conn, query, top_k=10: [])
    monkeypatch.setattr(tools, "_query_text_chunks_literal", lambda conn, query, top_k=10: [])
    monkeypatch.setattr(tools, "_should_include_structured_tables", lambda query: False)

    result = json.loads(
        tools.hybrid_search.func("企业管理费计算规则", top_k=3, path_constraint="第二册电气设备安装工程/%")
    )

    assert result[0]["source_db"] == "hybrid_vector"
    assert result[0]["metadata"]["vector_backend"] == "pgvector"
    assert result[0]["retrieval_path"] == "vector"