import json

from infrastructure.embedding_service import EmbeddingService


class _FakeHTTPResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def test_llama_cpp_http_embeddings_are_sorted_by_index(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BACKEND", "llama_cpp_http")
    monkeypatch.setenv("LLAMA_CPP_EMBED_URL", "http://127.0.0.1:8099")
    monkeypatch.setenv("LLAMA_CPP_EMBED_MODEL", "bge-m3-q8_0.gguf")

    def fake_urlopen(request, timeout):
        payload = {
            "data": [
                {"index": 1, "embedding": [0.3, 0.4]},
                {"index": 0, "embedding": [0.1, 0.2]},
            ]
        }
        return _FakeHTTPResponse(payload)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    service = EmbeddingService(use_mock=False)

    assert service.dimension == 2
    assert service.encode(["alpha", "beta"]) == [[0.1, 0.2], [0.3, 0.4]]


def test_embedding_service_reads_runtime_config(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BACKEND", "llama_cpp_http")
    monkeypatch.setenv("LLAMA_CPP_EMBED_URL", "http://127.0.0.1:8099")
    monkeypatch.setenv("LLAMA_CPP_EMBED_MODEL", "custom-bge.gguf")
    monkeypatch.setenv("EMBEDDING_VECTOR_DIM", "2048")
    monkeypatch.setattr(EmbeddingService, "_load_model", lambda self: None)
    monkeypatch.setattr(EmbeddingService, "_validate_dimension", lambda self: None)

    service = EmbeddingService(use_mock=False)

    assert service.backend == "llama_cpp_http"
    assert service.llama_url == "http://127.0.0.1:8099"
    assert service.llama_model == "custom-bge.gguf"
    assert service.expected_dimension == 2048
