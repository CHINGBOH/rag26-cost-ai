from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
import yaml

RETRIEVAL_SERVICE_ROOT = Path(__file__).resolve().parents[1]
try:
    REPO_ROOT = Path(__file__).resolve().parents[4]
except IndexError:
    # Docker: service files live at /app/, only 2 parents deep
    REPO_ROOT = Path(__file__).resolve().parents[1]

_LOCAL_HOSTS = "localhost,127.0.0.1,0.0.0.0,::1,host.docker.internal"


@dataclass(frozen=True)
class RetrievalRuntimeConfig:
    database_url: str
    feedback_log_path: Path
    pipeline_jobs_dir: Path
    pipeline_upload_dir: Path
    reports_dir: Path
    eval_set_path: Path
    agent_traces_dir: Path
    learning_last_run_file: Path
    ocr_output_dir: Path
    retrieval_service_url: str
    go_gateway_url: str
    nodejs_url: str
    python_legacy_url: str
    ocr_service_url: str
    qdrant_url: str
    qdrant_ingest_collection: str
    qdrant_session_collection: str
    qdrant_timeout_seconds: int
    qdrant_pool_size: int
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    neo4j_http_url: str
    elasticsearch_url: str
    elasticsearch_index_name: str
    elasticsearch_timeout_seconds: float
    redis_url: str
    milvus_url: str
    milvus_health_url: str
    vector_store_type: str
    keyword_backend: str
    tei_url: str
    postgres_max_connections: int
    models_dir: Path
    embedding_backend: str
    embedding_model_name: str
    embedding_dim: int
    llama_cpp_embed_url: str
    llama_cpp_embed_model: str
    embedding_vector_dim: int
    llm_provider: str
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    llm_route: str
    llm_max_tokens: int
    llm_temperature: float
    deepseek_base_url: str
    local_llm_model: str
    local_llm_base_url: str
    local_llm_engine: str
    redis_max_connections: int
    redis_socket_timeout_seconds: int
    retrieval_observability_enabled: bool
    pg_tsv_config: str
    contract_verifier_loop_enabled: bool
    default_top_k: int
    score_threshold: float
    max_iterations: int
    hybrid_vector_min_score: float
    hybrid_vector_fetch_multiplier: int
    hybrid_text_fetch_multiplier: int
    hybrid_rrf_rank_constant: int
    hybrid_structured_top_k: int
    hybrid_literal_top_k: int
    concept_recursive_depth: int
    otel_endpoint: str
    otel_service_name: str


def bootstrap_runtime_environment() -> None:
    load_dotenv(REPO_ROOT / ".env", override=False)

    existing_no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    merged_no_proxy = ",".join(filter(None, [existing_no_proxy, _LOCAL_HOSTS]))
    os.environ["NO_PROXY"] = merged_no_proxy
    os.environ["no_proxy"] = merged_no_proxy

    for key in (
        "ALL_PROXY",
        "all_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "FTP_PROXY",
        "ftp_proxy",
    ):
        os.environ.pop(key, None)


def bootstrap_llm_proxy_environment(base_url: str) -> None:
    bootstrap_runtime_environment()
    if any(host in (base_url or "") for host in ("localhost", "127.0.0.1", "::1")):
        for key in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
            os.environ.pop(key, None)


def read_runtime_config(*, refresh: bool = False) -> RetrievalRuntimeConfig:
    bootstrap_runtime_environment()
    file_config = _load_file_config(refresh=refresh)
    keyword_backend_override = _load_override("keyword_backend", refresh=refresh)
    vector_backend_override = _load_override("vector_backend", refresh=refresh)

    database_url = (
        os.environ.get("DATABASE_URL")
        or _build_postgres_url_from_env()
        or _build_postgres_url_from_file(file_config)
        or "postgresql://rag_user:rag_password@localhost:5432/rag_db"
    )

    qdrant_host = os.environ.get("QDRANT_HOST") or _nested(
        file_config, "vector_store", "host", default="localhost"
    )
    qdrant_port = int(
        os.environ.get("QDRANT_PORT")
        or _nested(file_config, "vector_store", "port", default=6333)
        or 6333
    )
    qdrant_url = os.environ.get("QDRANT_URL") or f"http://{qdrant_host}:{qdrant_port}"
    qdrant_collection = (
        os.environ.get("QDRANT_INGEST_COLLECTION")
        or _nested(file_config, "vector_store", "collection_name", default="document_chunks")
        or "document_chunks"
    )
    qdrant_session_collection = os.environ.get("QDRANT_COLLECTION_NAME") or "session_context"
    qdrant_timeout_seconds = _env_int("QDRANT_TIMEOUT", 30, minimum=1)
    qdrant_pool_size = _env_int("QDRANT_POOL_SIZE", 10, minimum=1)

    neo4j_uri = os.environ.get("NEO4J_URI") or _nested(
        file_config, "graph_store", "uri", default="bolt://localhost:7687"
    )
    neo4j_user = os.environ.get("NEO4J_USER") or _nested(
        file_config, "graph_store", "username", default="neo4j"
    )
    neo4j_password = os.environ.get("NEO4J_PASSWORD") or _nested(
        file_config, "graph_store", "password", default="password"
    )
    neo4j_http_url = os.environ.get("NEO4J_HTTP_URL") or _derive_neo4j_http_url(neo4j_uri)

    elasticsearch_url = (
        os.environ.get("ES_URL")
        or _first_nested(file_config, "keyword_store", "hosts", default="http://localhost:9200")
    )
    elasticsearch_index_name = os.environ.get("ES_INDEX_NAME") or "rag_chunks_v1"
    elasticsearch_timeout_seconds = _env_float(
        "ES_TIMEOUT",
        _nested(file_config, "keyword_store", "timeout_seconds", default=5.0),
        default=5.0,
        min_value=0.1,
    )
    redis_url = os.environ.get("REDIS_URL") or _build_redis_url_from_env_or_file(file_config)

    vector_store_type = vector_backend_override or os.environ.get("VECTOR_STORE__TYPE") or _nested(
        file_config, "vector_store", "type", default="milvus"
    )
    keyword_backend = keyword_backend_override or os.environ.get("KEYWORD_BACKEND") or _derive_keyword_backend(
        _nested(file_config, "keyword_store", "type", default="elasticsearch")
    )

    tei_url = os.environ.get("TEI_URL") or _nested(file_config, "models", "tei", "url", default="http://localhost:8003")
    postgres_max_connections = _env_int("POSTGRES_MAX_CONNECTIONS", 20, minimum=1)
    models_dir = Path(os.environ.get("MODELS_DIR") or str(REPO_ROOT / "models"))
    embedding_backend = os.environ.get("EMBEDDING_BACKEND") or "sentence_transformers"
    embedding_model_name = (
        os.environ.get("EMBEDDING_MODEL")
        or _nested(file_config, "models", "embedding", "name", default="BAAI/bge-large-zh-v1.5")
        or "BAAI/bge-large-zh-v1.5"
    )
    embedding_dim = _env_int(
        "EMBEDDING_DIM",
        _nested(file_config, "models", "embedding", "dimension", default=1024),
        minimum=0,
    )
    llama_cpp_embed_url = (os.environ.get("LLAMA_CPP_EMBED_URL") or "").rstrip("/")
    llama_cpp_embed_model = os.environ.get("LLAMA_CPP_EMBED_MODEL") or "llama.cpp-embedding"
    embedding_vector_dim = _env_int("EMBEDDING_VECTOR_DIM", 0, minimum=0)
    llm_provider = os.environ.get("LLM_PROVIDER") or "deepseek"
    llm_api_key = (
        os.environ.get("LLM_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or _nested(file_config, "models", "llm", "api_key", default="")
        or ""
    )
    llm_base_url = (
        os.environ.get("LLM_BASE_URL")
        or _nested(file_config, "models", "llm", "base_url", default="")
        or "https://api.deepseek.com"
    )
    llm_model = (
        os.environ.get("LLM_MODEL")
        or _nested(file_config, "models", "llm", "model", default="")
        or "deepseek-chat"
    )
    llm_route = os.environ.get("LLM_ROUTE") or llm_provider
    llm_max_tokens = _env_int("LLM_MAX_TOKENS", 2048, minimum=1)
    llm_temperature = _env_float("LLM_TEMPERATURE", 0.0, min_value=0.0, max_value=2.0)
    deepseek_base_url = os.environ.get("DEEPSEEK_BASE_URL") or llm_base_url

    local_llm_model = (
        os.environ.get("LOCAL_LLM_MODEL")
        or os.environ.get("LLM_LOCAL_MODEL")
        or "Qwen2.5-14B-Instruct"
    )
    local_llm_base_url = os.environ.get("LOCAL_LLM_BASE_URL") or "http://127.0.0.1:8080/v1"
    local_llm_engine = os.environ.get("LOCAL_LLM_ENGINE") or "llama.cpp"
    redis_max_connections = _env_int("REDIS_MAX_CONNECTIONS", 50, minimum=1)
    redis_socket_timeout_seconds = _env_int("REDIS_SOCKET_TIMEOUT", 10, minimum=1)

    pipeline_jobs_dir = Path(
        os.environ.get("RAG_PIPELINE_JOBS_DIR") or str(REPO_ROOT / "data" / "pipeline_jobs")
    )
    pipeline_upload_dir = Path(
        os.environ.get("RAG_PIPELINE_UPLOAD_DIR") or str(REPO_ROOT / "data" / "uploads")
    )
    reports_dir = Path(os.environ.get("RAG_REPORTS_DIR") or str(REPO_ROOT / "reports"))
    eval_set_path = Path(
        os.environ.get("RAG_EVAL_SET_PATH") or str(REPO_ROOT / "data" / "eval" / "golden_test_set.json")
    )
    agent_traces_dir = Path(
        os.environ.get("RAG_AGENT_TRACES_DIR") or str(REPO_ROOT / "data" / "agent_traces")
    )
    feedback_log_path = Path(
        os.environ.get("FEEDBACK_LOG_PATH") or str(REPO_ROOT / "data" / "feedback" / "rag_feedback.jsonl")
    )
    learning_last_run_file = Path(
        os.environ.get("LEARNING_LAST_RUN_FILE")
        or str(REPO_ROOT / "logs" / "agent_test_16_results.json")
    )
    ocr_output_dir = Path(
        os.environ.get("OCR_OUTPUT_DIR") or str(REPO_ROOT / "data" / "ocr_outputs")
    )
    retrieval_service_url = (
        os.environ.get("RETRIEVAL_API_URL")
        or os.environ.get("RETRIEVAL_URL")
        or "http://localhost:8002"
    ).rstrip("/")
    go_gateway_url = (os.environ.get("GATEWAY_URL") or "http://localhost:8080").rstrip("/")
    nodejs_url = (
        os.environ.get("NODEJS_URL")
        or f"http://localhost:{_nested(file_config, 'services', 'recursion', 'port', default=3001)}"
    ).rstrip("/")
    python_legacy_url = (
        os.environ.get("PYTHON_LEGACY_URL")
        or f"http://localhost:{_nested(file_config, 'services', 'api', 'port', default=8000)}"
    ).rstrip("/")
    ocr_service_url = os.environ.get("OCR_SERVICE_URL") or (
        f"http://localhost:{_nested(file_config, 'services', 'ocr', 'port', default=8001)}"
    )

    milvus_url = os.environ.get("MILVUS_URL") or _nested(
        file_config, "vector_store", "uri", default="http://localhost:19530"
    )
    milvus_health_url = os.environ.get("MILVUS_HEALTH_URL") or _derive_milvus_health_url(milvus_url)

    retrieval_observability_enabled = _env_bool("RETRIEVAL_OBSERVABILITY_ENABLED", default=True)
    pg_tsv_config = os.environ.get("PG_TSV_CONFIG") or "chinese"
    contract_verifier_loop_enabled = _env_bool("RAG_ENABLE_CONTRACT_VERIFIER_LOOP", default=False)
    default_top_k = _env_int(
        "DEFAULT_TOP_K",
        _nested(file_config, "retrieval", "vector_top_k", default=8),
        minimum=1,
    )
    score_threshold = _env_float(
        "SCORE_THRESHOLD",
        _nested(file_config, "retrieval", "score_threshold", default=0.6),
        min_value=0.0,
        max_value=1.0,
    )
    max_iterations = _env_int("MAX_ITERATIONS", 3, minimum=1)
    hybrid_vector_min_score = _env_float("HYBRID_VECTOR_MIN_SCORE", 0.40, min_value=0.0, max_value=1.0)
    hybrid_vector_fetch_multiplier = _env_int("HYBRID_VECTOR_FETCH_MULTIPLIER", 1, minimum=1)
    hybrid_text_fetch_multiplier = _env_int("HYBRID_TEXT_FETCH_MULTIPLIER", 1, minimum=1)
    hybrid_rrf_rank_constant = _env_int("HYBRID_RRF_RANK_CONSTANT", 60, minimum=1)
    hybrid_structured_top_k = _env_int("HYBRID_STRUCTURED_TOP_K", 0, minimum=0)
    hybrid_literal_top_k = _env_int("HYBRID_LITERAL_TOP_K", 0, minimum=0)
    concept_recursive_depth = _env_int("CONCEPT_RECURSIVE_DEPTH", 2, minimum=1)

    otel_endpoint = (
        os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        or os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        or ""
    )
    otel_service_name = os.environ.get("OTEL_SERVICE_NAME") or "retrieval-service"

    return RetrievalRuntimeConfig(
        database_url=database_url,
        feedback_log_path=feedback_log_path,
        pipeline_jobs_dir=pipeline_jobs_dir,
        pipeline_upload_dir=pipeline_upload_dir,
        reports_dir=reports_dir,
        eval_set_path=eval_set_path,
        agent_traces_dir=agent_traces_dir,
        learning_last_run_file=learning_last_run_file,
        ocr_output_dir=ocr_output_dir,
        retrieval_service_url=retrieval_service_url,
        go_gateway_url=go_gateway_url,
        nodejs_url=nodejs_url,
        python_legacy_url=python_legacy_url,
        ocr_service_url=ocr_service_url,
        qdrant_url=qdrant_url,
        qdrant_ingest_collection=qdrant_collection,
        qdrant_session_collection=qdrant_session_collection,
        qdrant_timeout_seconds=qdrant_timeout_seconds,
        qdrant_pool_size=qdrant_pool_size,
        neo4j_uri=neo4j_uri,
        neo4j_user=neo4j_user,
        neo4j_password=neo4j_password,
        neo4j_http_url=neo4j_http_url,
        elasticsearch_url=elasticsearch_url,
        elasticsearch_index_name=elasticsearch_index_name,
        elasticsearch_timeout_seconds=elasticsearch_timeout_seconds,
        redis_url=redis_url,
        milvus_url=milvus_url,
        milvus_health_url=milvus_health_url,
        vector_store_type=vector_store_type,
        keyword_backend=keyword_backend,
        tei_url=tei_url,
        postgres_max_connections=postgres_max_connections,
        models_dir=models_dir,
        embedding_backend=embedding_backend,
        embedding_model_name=embedding_model_name,
        embedding_dim=embedding_dim,
        llama_cpp_embed_url=llama_cpp_embed_url,
        llama_cpp_embed_model=llama_cpp_embed_model,
        embedding_vector_dim=embedding_vector_dim,
        llm_provider=llm_provider,
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        llm_route=llm_route,
        llm_max_tokens=llm_max_tokens,
        llm_temperature=llm_temperature,
        deepseek_base_url=deepseek_base_url,
        local_llm_model=local_llm_model,
        local_llm_base_url=local_llm_base_url,
        local_llm_engine=local_llm_engine,
        redis_max_connections=redis_max_connections,
        redis_socket_timeout_seconds=redis_socket_timeout_seconds,
        retrieval_observability_enabled=retrieval_observability_enabled,
        pg_tsv_config=pg_tsv_config,
        contract_verifier_loop_enabled=contract_verifier_loop_enabled,
        default_top_k=default_top_k,
        score_threshold=score_threshold,
        max_iterations=max_iterations,
        hybrid_vector_min_score=hybrid_vector_min_score,
        hybrid_vector_fetch_multiplier=hybrid_vector_fetch_multiplier,
        hybrid_text_fetch_multiplier=hybrid_text_fetch_multiplier,
        hybrid_rrf_rank_constant=hybrid_rrf_rank_constant,
        hybrid_structured_top_k=hybrid_structured_top_k,
        hybrid_literal_top_k=hybrid_literal_top_k,
        concept_recursive_depth=concept_recursive_depth,
        otel_endpoint=otel_endpoint,
        otel_service_name=otel_service_name,
    )


def postgres_connection_kwargs(*, refresh: bool = False) -> dict[str, str | int]:
    runtime = read_runtime_config(refresh=refresh)
    parsed = urlparse(runtime.database_url)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "dbname": (parsed.path or "/rag_db").lstrip("/"),
        "user": parsed.username or "rag_user",
        "password": parsed.password or "",
        "connect_timeout": 5,
    }


def redis_connection_kwargs(*, refresh: bool = False) -> dict[str, str | int | None]:
    runtime = read_runtime_config(refresh=refresh)
    parsed = urlparse(runtime.redis_url)
    db_name = (parsed.path or "/0").lstrip("/")
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 6379,
        "db": int(db_name or 0),
        "password": parsed.password or None,
    }


def resolve_local_model_path(model_name: str, *, refresh: bool = False) -> str:
    runtime = read_runtime_config(refresh=refresh)
    snapshot_root = runtime.models_dir / f"models--{model_name.replace('/', '--')}" / "snapshots"
    if snapshot_root.exists():
        snapshots = sorted(path for path in snapshot_root.iterdir() if path.is_dir())
        if snapshots:
            return str(snapshots[-1])
    return model_name


@lru_cache(maxsize=1)
def _cached_file_config() -> dict:
    return _load_yaml_file()


def _load_file_config(*, refresh: bool) -> dict:
    if refresh:
        return _load_yaml_file()
    return _cached_file_config()


def _build_postgres_url_from_env() -> str | None:
    host = os.environ.get("PG_HOST") or os.environ.get("POSTGRES_HOST")
    port = os.environ.get("PG_PORT") or os.environ.get("POSTGRES_PORT")
    dbname = os.environ.get("PG_DB") or os.environ.get("POSTGRES_DB")
    user = os.environ.get("PG_USER") or os.environ.get("POSTGRES_USER")
    password = os.environ.get("PG_PASSWORD") or os.environ.get("POSTGRES_PASSWORD")
    if not any((host, port, dbname, user, password)):
        return None
    return "postgresql://{user}:{password}@{host}:{port}/{dbname}".format(
        user=user or "rag_user",
        password=password or "rag_password",
        host=host or "localhost",
        port=port or "5432",
        dbname=dbname or "rag_db",
    )


def _build_redis_url_from_env_or_file(file_config: dict) -> str:
    host = os.environ.get("REDIS_HOST") or _nested(file_config, "cache", "host", default="localhost")
    port = os.environ.get("REDIS_PORT") or _nested(file_config, "cache", "port", default=6379)
    db = os.environ.get("REDIS_DB") or _nested(file_config, "cache", "db", default=0)
    password = os.environ.get("REDIS_PASSWORD")
    auth = f":{password}@" if password else ""
    return f"redis://{auth}{host}:{port}/{db}"


def _build_postgres_url_from_file(file_config: dict) -> str | None:
    password = _nested(file_config, "structured_store", "password", default="rag_password") or "rag_password"
    return (
        f"postgresql://{_nested(file_config, 'structured_store', 'username', default='rag_user')}:{password}"
        f"@{_nested(file_config, 'structured_store', 'host', default='localhost')}:"
        f"{_nested(file_config, 'structured_store', 'port', default=5432)}/"
        f"{_nested(file_config, 'structured_store', 'database', default='rag_db')}"
    )


def _derive_neo4j_http_url(neo4j_uri: str) -> str:
    parsed = urlparse(neo4j_uri)
    host = parsed.hostname or "localhost"
    port = 7474
    return f"http://{host}:{port}"


def _derive_milvus_health_url(milvus_url: str) -> str:
    parsed = urlparse(milvus_url)
    host = parsed.hostname or "localhost"
    return f"http://{host}:9091/healthz"


def _derive_keyword_backend(keyword_store_type: str) -> str:
    if keyword_store_type == "elasticsearch":
        return "es"
    if keyword_store_type == "meilisearch":
        return "meili"
    return keyword_store_type


def _load_yaml_file() -> dict:
    config_path = REPO_ROOT / "config" / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        return {}
    return data


def _nested(data: dict, *keys: str, default=None):
    current = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _first_nested(data: dict, *keys: str, default=None):
    value = _nested(data, *keys, default=None)
    if isinstance(value, list) and value:
        return value[0]
    return default if value in (None, []) else value


def _load_override(key: str, *, refresh: bool):
    try:
        from app.runtime_overrides import get_runtime_override

        return get_runtime_override(key, None, refresh=refresh)
    except Exception:
        return None


def _secret_value(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value()
    return str(value)


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, fallback, *, default: int | None = None, minimum: int) -> int:
    if default is None:
        default = int(fallback or 0)
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        raw = fallback
    if raw in (None, ""):
        return default
    try:
        return max(minimum, int(raw))
    except (TypeError, ValueError):
        return default


def _env_float(
    name: str,
    fallback,
    *,
    default: float | None = None,
    min_value: float,
    max_value: float | None = None,
) -> float:
    if default is None:
        default = float(fallback or 0.0)
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        raw = fallback
    if raw in (None, ""):
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value
