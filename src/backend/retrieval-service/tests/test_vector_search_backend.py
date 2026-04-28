import json
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, "src/backend/retrieval-service")

from app.agent import tools
from domain.models import Document


class FakeMilvusAdapter:
    def __init__(self, available: bool = True):
        self.available = available

    def is_available(self) -> bool:
        return self.available

    async def search(self, query_vector, top_k: int = 30, score_threshold: float = 0.6):
        return [
            (
                Document(
                    id="milvus-1",
                    content="Milvus 命中的向量片段",
                    doc_id="doc-milvus",
                    title="Milvus 标题",
                    page=9,
                    section="3.2",
                    chunk_type="paragraph",
                    metadata={"source_kind": "chunk"},
                ),
                0.88,
            )
        ]


def test_vector_search_prefers_milvus_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tools,
        "AppConfig",
        lambda: SimpleNamespace(vector_store=SimpleNamespace(type="milvus")),
    )
    monkeypatch.setattr(tools, "create_vector_store_adapter", lambda config: FakeMilvusAdapter())
    monkeypatch.setattr(tools, "_get_embedding", lambda query: [0.1, 0.2, 0.3])
    monkeypatch.setattr(tools, "_get_pg_conn", lambda: (_ for _ in ()).throw(AssertionError("pg fallback should not run")))

    result = json.loads(tools.vector_search.func("企业管理费", top_k=2))

    assert len(result) == 1
    assert result[0]["source_db"] == "milvus"
    assert result[0]["retrieval_path"] == "vector"


def test_vector_search_falls_back_to_pgvector(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params) -> None:
            self.query = query
            self.params = params

        def fetchall(self):
            return [(7, "doc-7", 4, "PG 命中的向量片段", 0.81)]

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        tools,
        "AppConfig",
        lambda: SimpleNamespace(vector_store=SimpleNamespace(type="qdrant")),
    )
    monkeypatch.setattr(tools, "_get_embedding", lambda query: [0.1, 0.2, 0.3])
    monkeypatch.setattr(tools, "_get_pg_conn", lambda: FakeConn())
    monkeypatch.setattr(tools, "_put_pg_conn", lambda conn: None)

    result = json.loads(tools.vector_search.func("企业管理费", top_k=2))

    assert len(result) == 1
    assert result[0]["source_db"] == "pgvector"
    assert result[0]["retrieval_path"] == "vector"