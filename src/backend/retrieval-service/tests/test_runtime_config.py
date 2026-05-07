from pathlib import Path

from app.runtime_config import postgres_connection_kwargs, read_runtime_config, redis_connection_kwargs, resolve_local_model_path
from infrastructure.adapters.unified.store_config import StoreConfig


def test_runtime_config_uses_env_overrides(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://env_user:env_pass@db.example:5544/env_db")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant.example:7333")
    monkeypatch.setenv("QDRANT_INGEST_COLLECTION", "env_chunks")
    monkeypatch.setenv("QDRANT_COLLECTION_NAME", "session_context_env")
    monkeypatch.setenv("QDRANT_TIMEOUT", "45")
    monkeypatch.setenv("QDRANT_POOL_SIZE", "12")
    monkeypatch.setenv("OCR_SERVICE_URL", "http://ocr.example:9001")
    monkeypatch.setenv("FEEDBACK_LOG_PATH", "/tmp/runtime-feedback.jsonl")
    monkeypatch.setenv("RAG_PIPELINE_JOBS_DIR", "/tmp/runtime-jobs")
    monkeypatch.setenv("RAG_PIPELINE_UPLOAD_DIR", "/tmp/runtime-uploads")
    monkeypatch.setenv("RAG_REPORTS_DIR", "/tmp/runtime-reports")
    monkeypatch.setenv("RAG_EVAL_SET_PATH", "/tmp/runtime-eval.json")
    monkeypatch.setenv("RAG_AGENT_TRACES_DIR", "/tmp/runtime-agent-traces")
    monkeypatch.setenv("LEARNING_LAST_RUN_FILE", "/tmp/runtime-learning.json")
    monkeypatch.setenv("OCR_OUTPUT_DIR", "/tmp/runtime-ocr")
    monkeypatch.setenv("RETRIEVAL_URL", "http://retrieval.example:9002")
    monkeypatch.setenv("GATEWAY_URL", "http://gateway.example:9003")
    monkeypatch.setenv("NODEJS_URL", "http://node.example:9004")
    monkeypatch.setenv("PYTHON_LEGACY_URL", "http://legacy.example:9005")
    monkeypatch.setenv("TEI_URL", "http://tei.example:9000")
    monkeypatch.setenv("MODELS_DIR", "/tmp/runtime-models")
    monkeypatch.setenv("EMBEDDING_BACKEND", "llama_cpp_http")
    monkeypatch.setenv("EMBEDDING_MODEL", "runtime-embed-model")
    monkeypatch.setenv("EMBEDDING_DIM", "2048")
    monkeypatch.setenv("LLAMA_CPP_EMBED_URL", "http://embed.example:8090")
    monkeypatch.setenv("LLAMA_CPP_EMBED_MODEL", "bge-m3-q8.gguf")
    monkeypatch.setenv("EMBEDDING_VECTOR_DIM", "1536")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "secret-key")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    monkeypatch.setenv("LLM_ROUTE", "runtime-route")
    monkeypatch.setenv("LLM_MAX_TOKENS", "4096")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.4")
    monkeypatch.setenv("ES_INDEX_NAME", "runtime-chunks")
    monkeypatch.setenv("ES_TIMEOUT", "9.5")
    monkeypatch.setenv("RETRIEVAL_OBSERVABILITY_ENABLED", "false")
    monkeypatch.setenv("PG_TSV_CONFIG", "simple")
    monkeypatch.setenv("RAG_ENABLE_CONTRACT_VERIFIER_LOOP", "1")
    monkeypatch.setenv("DEFAULT_TOP_K", "11")
    monkeypatch.setenv("SCORE_THRESHOLD", "0.72")
    monkeypatch.setenv("MAX_ITERATIONS", "5")
    monkeypatch.setenv("HYBRID_VECTOR_MIN_SCORE", "0.55")
    monkeypatch.setenv("HYBRID_VECTOR_FETCH_MULTIPLIER", "3")
    monkeypatch.setenv("HYBRID_TEXT_FETCH_MULTIPLIER", "2")
    monkeypatch.setenv("HYBRID_RRF_RANK_CONSTANT", "42")
    monkeypatch.setenv("HYBRID_STRUCTURED_TOP_K", "7")
    monkeypatch.setenv("HYBRID_LITERAL_TOP_K", "6")
    monkeypatch.setenv("CONCEPT_RECURSIVE_DEPTH", "4")
    monkeypatch.setenv("POSTGRES_MAX_CONNECTIONS", "25")
    monkeypatch.setenv("REDIS_MAX_CONNECTIONS", "61")
    monkeypatch.setenv("REDIS_SOCKET_TIMEOUT", "13")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel.example:4318")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "retrieval-runtime-test")

    runtime = read_runtime_config(refresh=True)

    assert runtime.database_url == "postgresql://env_user:env_pass@db.example:5544/env_db"
    assert runtime.qdrant_url == "http://qdrant.example:7333"
    assert runtime.qdrant_ingest_collection == "env_chunks"
    assert runtime.qdrant_session_collection == "session_context_env"
    assert runtime.qdrant_timeout_seconds == 45
    assert runtime.qdrant_pool_size == 12
    assert runtime.ocr_service_url == "http://ocr.example:9001"
    assert runtime.feedback_log_path == Path("/tmp/runtime-feedback.jsonl")
    assert runtime.pipeline_jobs_dir == Path("/tmp/runtime-jobs")
    assert runtime.pipeline_upload_dir == Path("/tmp/runtime-uploads")
    assert runtime.reports_dir == Path("/tmp/runtime-reports")
    assert runtime.eval_set_path == Path("/tmp/runtime-eval.json")
    assert runtime.agent_traces_dir == Path("/tmp/runtime-agent-traces")
    assert runtime.learning_last_run_file == Path("/tmp/runtime-learning.json")
    assert runtime.ocr_output_dir == Path("/tmp/runtime-ocr")
    assert runtime.retrieval_service_url == "http://retrieval.example:9002"
    assert runtime.go_gateway_url == "http://gateway.example:9003"
    assert runtime.nodejs_url == "http://node.example:9004"
    assert runtime.python_legacy_url == "http://legacy.example:9005"
    assert runtime.tei_url == "http://tei.example:9000"
    assert runtime.models_dir == Path("/tmp/runtime-models")
    assert runtime.embedding_backend == "llama_cpp_http"
    assert runtime.embedding_model_name == "runtime-embed-model"
    assert runtime.embedding_dim == 2048
    assert runtime.llama_cpp_embed_url == "http://embed.example:8090"
    assert runtime.llama_cpp_embed_model == "bge-m3-q8.gguf"
    assert runtime.embedding_vector_dim == 1536
    assert runtime.llm_provider == "openai"
    assert runtime.llm_base_url == "https://llm.example/v1"
    assert runtime.llm_api_key == "secret-key"
    assert runtime.llm_model == "env-model"
    assert runtime.llm_route == "runtime-route"
    assert runtime.llm_max_tokens == 4096
    assert runtime.llm_temperature == 0.4
    assert runtime.elasticsearch_index_name == "runtime-chunks"
    assert runtime.elasticsearch_timeout_seconds == 9.5
    assert runtime.retrieval_observability_enabled is False
    assert runtime.pg_tsv_config == "simple"
    assert runtime.contract_verifier_loop_enabled is True
    assert runtime.default_top_k == 11
    assert runtime.score_threshold == 0.72
    assert runtime.max_iterations == 5
    assert runtime.hybrid_vector_min_score == 0.55
    assert runtime.hybrid_vector_fetch_multiplier == 3
    assert runtime.hybrid_text_fetch_multiplier == 2
    assert runtime.hybrid_rrf_rank_constant == 42
    assert runtime.hybrid_structured_top_k == 7
    assert runtime.hybrid_literal_top_k == 6
    assert runtime.concept_recursive_depth == 4
    assert runtime.postgres_max_connections == 25
    assert runtime.redis_max_connections == 61
    assert runtime.redis_socket_timeout_seconds == 13
    assert runtime.otel_endpoint == "http://otel.example:4318"
    assert runtime.otel_service_name == "retrieval-runtime-test"


def test_runtime_config_builds_database_url_from_pg_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PG_HOST", "pg.example")
    monkeypatch.setenv("PG_PORT", "6543")
    monkeypatch.setenv("PG_DB", "runtime_db")
    monkeypatch.setenv("PG_USER", "runtime_user")
    monkeypatch.setenv("PG_PASSWORD", "runtime_pass")

    runtime = read_runtime_config(refresh=True)
    kwargs = postgres_connection_kwargs(refresh=True)

    assert runtime.database_url == (
        "postgresql://runtime_user:runtime_pass@pg.example:6543/runtime_db"
    )
    assert kwargs == {
        "host": "pg.example",
        "port": 6543,
        "dbname": "runtime_db",
        "user": "runtime_user",
        "password": "runtime_pass",
        "connect_timeout": 5,
    }


def test_runtime_config_builds_database_url_from_postgres_alias_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PG_HOST", raising=False)
    monkeypatch.delenv("PG_PORT", raising=False)
    monkeypatch.delenv("PG_DB", raising=False)
    monkeypatch.delenv("PG_USER", raising=False)
    monkeypatch.delenv("PG_PASSWORD", raising=False)
    monkeypatch.setenv("POSTGRES_HOST", "pg.alias")
    monkeypatch.setenv("POSTGRES_PORT", "5544")
    monkeypatch.setenv("POSTGRES_DB", "alias_db")
    monkeypatch.setenv("POSTGRES_USER", "alias_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "alias_pass")

    runtime = read_runtime_config(refresh=True)
    kwargs = postgres_connection_kwargs(refresh=True)

    assert runtime.database_url == "postgresql://alias_user:alias_pass@pg.alias:5544/alias_db"
    assert kwargs["host"] == "pg.alias"
    assert kwargs["dbname"] == "alias_db"
    assert kwargs["user"] == "alias_user"
    assert kwargs["password"] == "alias_pass"


def test_store_config_reads_runtime_config(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://qdrant.runtime:7444")
    monkeypatch.setenv("QDRANT_COLLECTION_NAME", "session_context_runtime")
    monkeypatch.setenv("QDRANT_TIMEOUT", "44")
    monkeypatch.setenv("QDRANT_POOL_SIZE", "9")
    monkeypatch.setenv("DATABASE_URL", "postgresql://cfg_user:cfg_pass@db.runtime:5545/cfg_db")
    monkeypatch.setenv("POSTGRES_MAX_CONNECTIONS", "33")
    monkeypatch.setenv("REDIS_URL", "redis://:secret@redis.runtime:6380/4")
    monkeypatch.setenv("REDIS_MAX_CONNECTIONS", "62")
    monkeypatch.setenv("REDIS_SOCKET_TIMEOUT", "17")

    config = StoreConfig.from_env()

    assert config.qdrant.host == "qdrant.runtime"
    assert config.qdrant.port == 7444
    assert config.qdrant.collection_name == "session_context_runtime"
    assert config.qdrant.timeout == 44
    assert config.qdrant.pool_size == 9
    assert config.postgres.host == "db.runtime"
    assert config.postgres.port == 5545
    assert config.postgres.database == "cfg_db"
    assert config.postgres.user == "cfg_user"
    assert config.postgres.password == "cfg_pass"
    assert config.postgres.max_connections == 33
    assert config.cache.host == "redis.runtime"
    assert config.cache.port == 6380
    assert config.cache.db == 4
    assert config.cache.password == "secret"
    assert config.cache.max_connections == 62
    assert config.cache.socket_timeout == 17


def test_runtime_helpers_parse_redis_and_model_paths(monkeypatch, tmp_path):
    model_dir = tmp_path / "models" / "models--BAAI--bge-m3" / "snapshots" / "snapshot-a"
    model_dir.mkdir(parents=True)
    monkeypatch.setenv("MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("REDIS_URL", "redis://:pw@redis.example:6390/7")

    redis = redis_connection_kwargs(refresh=True)
    model_path = resolve_local_model_path("BAAI/bge-m3", refresh=True)

    assert redis == {"host": "redis.example", "port": 6390, "db": 7, "password": "pw"}
    assert model_path == str(model_dir)
