import asyncio
import importlib
import os
import sys
import types

import pytest

# Add src/backend to sys.path for legacy imports.
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from config.runtime import read_runtime_config, tool_pg_config, tool_pg_database


def test_runtime_config_uses_shared_yaml_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "API_HOST",
        "API_PORT",
        "LOG_LEVEL",
        "CORS_ORIGINS",
        "VLLM_API_URL",
        "VLLM_MODEL_NAME",
        "LLM_BASE_URL",
        "LLM_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    runtime = read_runtime_config(refresh=True)

    assert runtime.api_host == "0.0.0.0"
    assert runtime.api_port == 8000
    assert runtime.api_reload is True
    assert runtime.enhanced_api_port == 8001
    assert runtime.simple_llm_port == 8003
    assert runtime.log_level == "INFO"
    assert "http://localhost:3000" in runtime.cors_origins
    assert runtime.embedding_model_name == "BAAI/bge-m3"
    assert runtime.qdrant_host == "localhost"
    assert runtime.qdrant_port == 6333
    assert runtime.redis_host == "localhost"
    assert runtime.redis_port == 6379
    assert runtime.embedding_backend == "tei"
    assert runtime.tei_url == "http://localhost:8003"
    assert runtime.elasticsearch_url == "http://localhost:9200"
    assert runtime.elasticsearch_index_name == "documents"
    assert runtime.neo4j_uri == "bolt://localhost:7687"
    assert runtime.neo4j_user == "neo4j"
    assert runtime.neo4j_password == "password"
    assert runtime.rerank_model_name == "BAAI/bge-reranker-large"
    assert runtime.rerank_batch_size == 8
    assert runtime.query_analysis_enabled is False


def test_runtime_config_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_PORT", "8100")
    monkeypatch.setenv("API_RELOAD", "false")
    monkeypatch.setenv("ENHANCED_API_PORT", "8101")
    monkeypatch.setenv("SIMPLE_LLM_PORT", "9103")
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test,http://b.test")
    monkeypatch.setenv("QDRANT_HOST", "qdrant.test")
    monkeypatch.setenv("POSTGRES_DB", "legacy_db")
    monkeypatch.setenv("REDIS_PORT", "6381")
    monkeypatch.setenv("EMBEDDING_BACKEND", "local")
    monkeypatch.setenv("EMBEDDING_MODEL_NAME", "embed-runtime")
    monkeypatch.setenv("OCR_OUTPUT_DIR", "/tmp/ocr-runtime")
    monkeypatch.setenv("KB_DIR", "/tmp/kb-runtime/documents")
    monkeypatch.setenv("RAG_API", "http://gateway.runtime:8080")
    monkeypatch.setenv("OCR_API", "http://ocr.runtime:8001")
    monkeypatch.setenv("CACHE_TTL_SECONDS", "7200")
    monkeypatch.setenv("EMBEDDING_MODEL", "/tmp/models/bge-m3")
    monkeypatch.setenv("RERANK_MODEL_PATH", "/tmp/models/reranker")
    monkeypatch.setenv("RERANK_MODEL_NAME", "rerank-runtime")
    monkeypatch.setenv("RERANK_BATCH_SIZE", "24")
    monkeypatch.setenv("ENABLE_QUERY_ANALYSIS", "true")
    monkeypatch.setenv("VLLM_API_URL", "http://llm.internal:9000")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example.com")
    monkeypatch.setenv("ES_URL", "http://es.runtime:9201")
    monkeypatch.setenv("ES_INDEX_NAME", "runtime-index")
    monkeypatch.setenv("NEO4J_URI", "bolt://neo.runtime:7688")
    monkeypatch.setenv("NEO4J_USER", "neo-user")
    monkeypatch.setenv("NEO4J_PASSWORD", "neo-pass")

    runtime = read_runtime_config(refresh=True)

    assert runtime.api_port == 8100
    assert runtime.api_reload is False
    assert runtime.enhanced_api_port == 8101
    assert runtime.simple_llm_port == 9103
    assert runtime.cors_origins == ("http://a.test", "http://b.test")
    assert runtime.qdrant_host == "qdrant.test"
    assert runtime.postgres_db == "legacy_db"
    assert runtime.redis_port == 6381
    assert runtime.embedding_backend == "local"
    assert runtime.embedding_model_name == "embed-runtime"
    assert runtime.ocr_output_dir == "/tmp/ocr-runtime"
    assert runtime.knowledge_base_documents_dir == "/tmp/kb-runtime/documents"
    assert runtime.rag_api_url == "http://gateway.runtime:8080"
    assert runtime.ocr_api_url == "http://ocr.runtime:8001"
    assert runtime.cache_ttl_seconds == 7200
    assert runtime.embedding_model_path == "/tmp/models/bge-m3"
    assert runtime.rerank_model_path == "/tmp/models/reranker"
    assert runtime.rerank_model_name == "rerank-runtime"
    assert runtime.rerank_batch_size == 24
    assert runtime.query_analysis_enabled is True
    assert runtime.vllm_api_url == "http://llm.internal:9000"
    assert runtime.llm_base_url == "https://llm.example.com"
    assert runtime.elasticsearch_url == "http://es.runtime:9201"
    assert runtime.elasticsearch_index_name == "runtime-index"
    assert runtime.neo4j_uri == "bolt://neo.runtime:7688"
    assert runtime.neo4j_user == "neo-user"
    assert runtime.neo4j_password == "neo-pass"


def test_tool_pg_config_prefers_pg_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_HOST", "pg.alias")
    monkeypatch.setenv("PG_PORT", "5546")
    monkeypatch.setenv("PG_DB", "alias_db")
    monkeypatch.setenv("PG_USER", "alias_user")
    monkeypatch.setenv("PG_PASSWORD", "alias_pass")
    read_runtime_config(refresh=True)

    config = tool_pg_config()

    assert config == {
        "host": "pg.alias",
        "port": 5546,
        "database": "alias_db",
        "user": "alias_user",
        "password": "alias_pass",
    }


def test_tool_pg_database_supports_postgres_alias_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PG_DB", raising=False)
    monkeypatch.setenv("POSTGRES_DB", "postgres_alias_db")
    read_runtime_config(refresh=True)

    assert tool_pg_database("rag_dashboard") == "postgres_alias_db"


def test_llm_services_read_runtime_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLAMA_CPP_PATH", "/tmp/bin/llama-cli")
    monkeypatch.setenv("LLAMA_MODEL_PATH", "/tmp/models/model.gguf")
    monkeypatch.setenv("VLLM_API_URL", "http://vllm.internal:8001")
    monkeypatch.setenv("VLLM_MODEL_NAME", "test-vllm")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.internal")
    monkeypatch.setenv("LLM_API_KEY", "secret")
    monkeypatch.setenv("LLM_MODEL", "test-chat")
    read_runtime_config(refresh=True)

    from services.llm_service import LlamaCppService, VLLMService
    from unified_llm_service import LlamaCppEngine, OpenAIEngine, VLLMEngine

    assert LlamaCppService().llama_cli_path == "/tmp/bin/llama-cli"
    assert LlamaCppService().model_path == "/tmp/models/model.gguf"
    assert VLLMService().api_url == "http://vllm.internal:8001"
    assert VLLMService().model_name == "test-vllm"
    assert VLLMEngine().base_url == "http://vllm.internal:8001"
    assert LlamaCppEngine().executable_path == "/tmp/bin/llama-cli"
    assert OpenAIEngine().base_url == "https://llm.internal"
    assert OpenAIEngine().api_key == "secret"
    assert OpenAIEngine().model_name == "test-chat"


def test_rerank_service_uses_runtime_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RERANK_MODEL_NAME", "runtime-reranker")
    monkeypatch.setenv("RERANK_BATCH_SIZE", "21")
    read_runtime_config(refresh=True)

    import services.rerank_service as rerank_service

    reloaded = importlib.reload(rerank_service)

    assert reloaded.RERANK_MODEL_NAME == "runtime-reranker"
    assert reloaded.BATCH_SIZE == 21


def test_model_caller_uses_runtime_config_for_api_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_BASE", "https://openai.internal/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("LOCAL_MODEL_DIR", "/tmp/local-models")
    read_runtime_config(refresh=True)

    import services.model_caller as model_caller

    captured_kwargs: list[dict] = []

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            captured_kwargs.append(kwargs)

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(model_caller.httpx, "AsyncClient", FakeAsyncClient)

    embedding_caller = model_caller.EmbeddingModelCaller()
    rerank_caller = model_caller.RerankModelCaller()

    asyncio.run(embedding_caller.initialize(use_api=True))
    asyncio.run(rerank_caller.initialize(use_api=True))
    asyncio.run(embedding_caller.close())
    asyncio.run(rerank_caller.close())

    assert captured_kwargs[0]["base_url"] == "https://openai.internal/v1"
    assert captured_kwargs[0]["headers"]["Authorization"] == "Bearer openai-secret"
    assert captured_kwargs[1]["base_url"] == "https://openai.internal/v1"
    assert embedding_caller.runtime_config.local_model_dir == "/tmp/local-models"


def test_store_config_uses_runtime_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QDRANT_HOST", "qdrant.internal")
    monkeypatch.setenv("QDRANT_PORT", "7333")
    monkeypatch.setenv("POSTGRES_HOST", "pg.internal")
    monkeypatch.setenv("POSTGRES_PORT", "5544")
    monkeypatch.setenv("POSTGRES_DB", "rag_legacy")
    monkeypatch.setenv("POSTGRES_USER", "legacy_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "legacy_pass")
    monkeypatch.setenv("POSTGRES_MAX_CONNECTIONS", "42")
    monkeypatch.setenv("REDIS_HOST", "redis.internal")
    monkeypatch.setenv("REDIS_PORT", "6380")
    monkeypatch.setenv("REDIS_DB", "4")
    monkeypatch.setenv("REDIS_PASSWORD", "redis-pass")
    monkeypatch.setenv("REDIS_MAX_CONNECTIONS", "60")
    monkeypatch.setenv("REDIS_SOCKET_TIMEOUT", "15")
    read_runtime_config(refresh=True)

    import infrastructure.adapters.unified.store_config as store_config_module

    reloaded = importlib.reload(store_config_module)
    config = reloaded.StoreConfig.from_env()

    assert config.qdrant.host == "qdrant.internal"
    assert config.qdrant.port == 7333
    assert config.qdrant.collection_name == "session_context"
    assert config.postgres.host == "pg.internal"
    assert config.postgres.port == 5544
    assert config.postgres.database == "rag_legacy"
    assert config.postgres.user == "legacy_user"
    assert config.postgres.password == "legacy_pass"
    assert config.postgres.max_connections == 42
    assert config.cache.host == "redis.internal"
    assert config.cache.port == 6380
    assert config.cache.db == 4
    assert config.cache.password == "redis-pass"
    assert config.cache.max_connections == 60
    assert config.cache.socket_timeout == 15


def test_embedding_service_uses_runtime_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_HOST", "redis.runtime")
    monkeypatch.setenv("REDIS_PORT", "6390")
    monkeypatch.setenv("REDIS_DB", "5")
    monkeypatch.setenv("QDRANT_HOST", "qdrant.runtime")
    monkeypatch.setenv("QDRANT_PORT", "7340")
    monkeypatch.setenv("QDRANT_TIMEOUT", "12")
    monkeypatch.setenv("POSTGRES_HOST", "pg.runtime")
    monkeypatch.setenv("POSTGRES_PORT", "5545")
    monkeypatch.setenv("POSTGRES_DB", "runtime_db")
    monkeypatch.setenv("POSTGRES_USER", "runtime_user")
    monkeypatch.setenv("POSTGRES_MAX_CONNECTIONS", "7")
    monkeypatch.setenv("EMBEDDING_BACKEND", "tei")
    monkeypatch.setenv("TEI_URL", "http://tei.runtime:9001")
    read_runtime_config(refresh=True)

    import services.embedding_service as embedding_service_module

    reloaded = importlib.reload(embedding_service_module)
    captured: dict[str, dict] = {}

    class FakeRedisClient:
        def __init__(self, **kwargs):
            captured["redis"] = kwargs

        def close(self) -> None:
            return None

    class FakeQdrantClient:
        def __init__(self, *args, **kwargs):
            captured["qdrant"] = kwargs

        def get_collections(self):
            return types.SimpleNamespace(collections=[types.SimpleNamespace(name="document_chunks")])

        def close(self) -> None:
            return None

    class FakePool:
        async def close(self) -> None:
            return None

    async def fake_create_pool(**kwargs):
        captured["postgres"] = kwargs
        return FakePool()

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            captured["tei"] = kwargs

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(reloaded.redis.asyncio, "Redis", FakeRedisClient)
    monkeypatch.setattr(reloaded, "QdrantClient", FakeQdrantClient)
    monkeypatch.setattr(reloaded.asyncpg, "create_pool", fake_create_pool)
    monkeypatch.setattr(reloaded.httpx, "AsyncClient", FakeAsyncClient)

    service = reloaded.EmbeddingService()
    asyncio.run(service.initialize())

    assert captured["redis"]["host"] == "redis.runtime"
    assert captured["redis"]["port"] == 6390
    assert captured["redis"]["db"] == 5
    assert captured["qdrant"]["url"] == "http://qdrant.runtime:7340"
    assert captured["qdrant"]["timeout"] == 12
    assert captured["postgres"]["host"] == "pg.runtime"
    assert captured["postgres"]["port"] == 5545
    assert captured["postgres"]["database"] == "runtime_db"
    assert captured["postgres"]["user"] == "runtime_user"
    assert captured["postgres"]["max_size"] == 7
    assert captured["tei"]["base_url"] == "http://tei.runtime:9001"


def test_unified_pipeline_uses_runtime_query_analysis_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_QUERY_ANALYSIS", "true")
    read_runtime_config(refresh=True)

    import retrieval.unified_pipeline as unified_pipeline_module

    reloaded = importlib.reload(unified_pipeline_module)
    pipeline = reloaded.UnifiedRetrievalPipeline(store=object())

    assert pipeline.enable_query_analysis is True


def test_unified_api_uses_runtime_cors_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://frontend.test,http://gateway.test")
    read_runtime_config(refresh=True)

    import api.unified_api as unified_api

    reloaded = importlib.reload(unified_api)
    cors_middleware = next(item for item in reloaded.app.user_middleware if item.cls.__name__ == "CORSMiddleware")

    assert cors_middleware.kwargs["allow_origins"] == ["http://frontend.test", "http://gateway.test"]


def test_rag_unified_api_uses_runtime_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_PORT", "8124")
    monkeypatch.setenv("CORS_ORIGINS", "http://legacy-ui.test")
    monkeypatch.setenv("EMBEDDING_MODEL_NAME", "embed-runtime")
    monkeypatch.setenv("RERANK_MODEL_NAME", "rerank-runtime")
    monkeypatch.setenv("POSTGRES_HOST", "pg.runtime")
    monkeypatch.setenv("POSTGRES_PORT", "5547")
    monkeypatch.setenv("POSTGRES_DB", "legacy_runtime")
    monkeypatch.setenv("POSTGRES_USER", "legacy_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "legacy_pass")
    read_runtime_config(refresh=True)

    import rag_unified_api

    reloaded = importlib.reload(rag_unified_api)
    cors_middleware = next(item for item in reloaded.app.user_middleware if item.cls.__name__ == "CORSMiddleware")

    assert reloaded.DB_CONFIG == {
        "host": "pg.runtime",
        "port": 5547,
        "database": "legacy_runtime",
        "user": "legacy_user",
        "password": "legacy_pass",
    }
    assert reloaded.EMBEDDING_MODEL_NAME == "embed-runtime"
    assert reloaded.RERANK_MODEL_NAME == "rerank-runtime"
    assert cors_middleware.kwargs["allow_origins"] == ["http://legacy-ui.test"]


def test_main_minimal_uses_runtime_store_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://frontend.test")
    monkeypatch.setenv("ES_URL", "http://es.runtime:9201")
    monkeypatch.setenv("ES_INDEX_NAME", "runtime-index")
    monkeypatch.setenv("NEO4J_URI", "bolt://neo.runtime:7688")
    monkeypatch.setenv("NEO4J_USER", "neo-user")
    monkeypatch.setenv("NEO4J_PASSWORD", "neo-pass")
    monkeypatch.setenv("QDRANT_HOST", "qdrant.runtime")
    monkeypatch.setenv("QDRANT_PORT", "7444")
    read_runtime_config(refresh=True)

    es_calls: dict[str, object] = {}
    neo_calls: dict[str, object] = {}
    qdrant_calls: dict[str, object] = {}

    class FakeElasticsearch:
        def __init__(self, hosts):
            es_calls["hosts"] = hosts

        def ping(self):
            return True

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

        def run(self, _query):
            return None

    class FakeDriver:
        def session(self):
            return FakeSession()

    class FakeGraphDatabase:
        @staticmethod
        def driver(uri, auth):
            neo_calls["uri"] = uri
            neo_calls["auth"] = auth
            return FakeDriver()

    class FakeQdrantClient:
        def __init__(self, host, port):
            qdrant_calls["host"] = host
            qdrant_calls["port"] = port

    monkeypatch.setitem(sys.modules, "elasticsearch", types.SimpleNamespace(Elasticsearch=FakeElasticsearch))
    monkeypatch.setitem(sys.modules, "neo4j", types.SimpleNamespace(GraphDatabase=FakeGraphDatabase))
    monkeypatch.setitem(sys.modules, "qdrant_client", types.SimpleNamespace(QdrantClient=FakeQdrantClient))

    import main_minimal

    reloaded = importlib.reload(main_minimal)
    reloaded._init_db_clients()
    cors_middleware = next(item for item in reloaded.app.user_middleware if item.cls.__name__ == "CORSMiddleware")

    assert es_calls["hosts"] == ["http://es.runtime:9201"]
    assert neo_calls["uri"] == "bolt://neo.runtime:7688"
    assert neo_calls["auth"] == ("neo-user", "neo-pass")
    assert qdrant_calls == {"host": "qdrant.runtime", "port": 7444}
    assert cors_middleware.kwargs["allow_origins"] == ["http://frontend.test"]


def test_four_database_service_maps_search_and_process_results() -> None:
    from domain_models.document_models import ChunkType, DocumentChunk
    from services.four_database_service import FourDatabaseService

    chunk = DocumentChunk(chunk_id="chunk-1", doc_id="doc-1", content="result content", page_number=3)

    class FakeStore:
        def __init__(self):
            self.indexed = None

        def search(self, _query, _config):
            return types.SimpleNamespace(
                results=[
                    types.SimpleNamespace(
                        chunk=chunk,
                        final_score=0.91,
                        vector_score=0.8,
                        keyword_score=0.2,
                        rerank_score=0.7,
                    )
                ],
                total_chunks_searched=4,
                latency_ms=12.5,
                recall_stats={"vector_count": 1, "text_count": 1},
            )

        def index_document(self, document):
            self.indexed = document
            return {"chunks_indexed": len(document.chunks)}

        def health_check(self):
            return {"postgres": "healthy"}

        def close(self):
            return None

    class FakeProcessor:
        def _create_chunks(self, doc_id, _ocr_result):
            return [
                DocumentChunk(chunk_id=f"{doc_id}-1", doc_id=doc_id, content="text", chunk_type=ChunkType.TEXT),
                DocumentChunk(chunk_id=f"{doc_id}-2", doc_id=doc_id, content="table", chunk_type=ChunkType.TABLE),
            ]

        def _generate_embeddings(self, chunks):
            chunks[0].embedding = [0.1, 0.2]
            return True

    service = FourDatabaseService(store=FakeStore(), document_processor=FakeProcessor())

    search_result = asyncio.run(
        service.search_four_databases(query_text="hello", top_k=3, filters={"doc_type": "pdf"})
    )
    process_result = asyncio.run(
        service.process_document(
            file_path="/tmp/sample.pdf",
            file_name="sample.pdf",
            ocr_result={"total_pages": 2, "full_text": "sample"},
        )
    )

    assert search_result["total_candidates"] == 4
    assert search_result["final_results"][0].chunk_id == "chunk-1"
    assert search_result["final_results"][0].source == "doc-1.pdf"
    assert process_result.total_chunks == 2
    assert process_result.embedded_chunks == 1
    assert process_result.tables_extracted == 1


def test_rag_api_service_uses_runtime_startup_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_HOST", "127.0.0.1")
    monkeypatch.setenv("API_PORT", "8123")
    monkeypatch.setenv("API_RELOAD", "false")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("CORS_ORIGINS", "http://legacy-ui.test")
    read_runtime_config(refresh=True)

    def _stub_service_module(module_name: str, class_names: list[str], getter_name: str) -> None:
        module = types.ModuleType(module_name)
        for class_name in class_names:
            setattr(module, class_name, type(class_name, (), {}))

        async def _getter():
            return None

        setattr(module, getter_name, _getter)
        monkeypatch.setitem(sys.modules, module_name, module)

    _stub_service_module("services.embedding_service", ["EmbeddingService"], "get_embedding_service")
    _stub_service_module("services.four_database_service", ["FourDatabaseService"], "get_four_db_service")
    _stub_service_module("services.rerank_service", ["RerankService"], "get_rerank_service")
    _stub_service_module("services.llm_service", ["UnifiedLLMService", "Message"], "get_llm_service")
    _stub_service_module(
        "services.model_caller",
        ["UnifiedModelCaller", "EmbeddingResult", "RerankResult"],
        "get_model_caller",
    )

    import rag_api_service

    reloaded = importlib.reload(rag_api_service)
    cors_middleware = next(item for item in reloaded.app.user_middleware if item.cls.__name__ == "CORSMiddleware")

    assert reloaded.API_HOST == "127.0.0.1"
    assert reloaded.API_PORT == 8123
    assert reloaded.LOG_LEVEL == "DEBUG"
    assert cors_middleware.kwargs["allow_origins"] == ["http://legacy-ui.test"]
