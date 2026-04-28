import asyncio
import sys

import numpy as np
import pytest

sys.path.insert(0, "src/backend/retrieval-service")

from config.settings import VectorStoreConfig
from infrastructure import vector_store


class FakeMilvusClient:
    def __init__(self, uri: str, token: str | None = None, db_name: str | None = None):
        self.uri = uri
        self.token = token
        self.db_name = db_name
        self.collections: set[str] = set()
        self.last_upsert: tuple[str, list[dict]] | None = None
        self.last_delete: tuple[str, str | None, str | None] | None = None

    def has_collection(self, collection_name: str) -> bool:
        return collection_name in self.collections

    def create_collection(self, collection_name: str, dimension: int, metric_type: str) -> None:
        self.collections.add(collection_name)

    def describe_collection(self, collection_name: str) -> dict:
        if collection_name not in self.collections:
            raise ValueError("missing collection")
        return {"collection_name": collection_name}

    def search(
        self,
        collection_name: str,
        data: list[list[float]],
        limit: int,
        search_params: dict | None = None,
        output_fields: list[str] | None = None,
    ) -> list[list[dict]]:
        return [
            [
                {
                    "id": "chunk-1",
                    "distance": 0.91,
                    "entity": {
                        "content": "企业管理费包括管理人员工资。",
                        "doc_id": "doc-1",
                        "title": "费用组成",
                        "page": 3,
                        "section": "1.2",
                        "chunk_type": "paragraph",
                        "source_kind": "chunk",
                    },
                }
            ]
        ]

    def upsert(self, collection_name: str, data: list[dict]) -> None:
        self.last_upsert = (collection_name, data)

    def delete(self, collection_name: str, filter: str | None = None, expr: str | None = None) -> None:
        self.last_delete = (collection_name, filter, expr)


def test_create_vector_store_adapter_supports_milvus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vector_store, "MilvusClient", FakeMilvusClient)
    config = VectorStoreConfig(type="milvus", uri="http://localhost:19530", collection_name="chunks")

    adapter = vector_store.create_vector_store_adapter(config)

    assert isinstance(adapter, vector_store.MilvusVectorStoreAdapter)
    assert adapter.is_available() is True


def test_milvus_search_normalizes_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vector_store, "MilvusClient", FakeMilvusClient)
    adapter = vector_store.MilvusVectorStoreAdapter(
        VectorStoreConfig(type="milvus", uri="http://localhost:19530", collection_name="chunks")
    )

    results = asyncio.run(adapter.search(np.array([0.1, 0.2, 0.3]), top_k=3, score_threshold=0.5))

    assert len(results) == 1
    document, score = results[0]
    assert document.id == "chunk-1"
    assert document.doc_id == "doc-1"
    assert document.metadata["source_kind"] == "chunk"
    assert score == pytest.approx(0.91)


def test_create_vector_store_adapter_rejects_unsupported_backend() -> None:
    config = VectorStoreConfig(type="chroma")

    with pytest.raises(ValueError, match="Unsupported vector store type"):
        vector_store.create_vector_store_adapter(config)