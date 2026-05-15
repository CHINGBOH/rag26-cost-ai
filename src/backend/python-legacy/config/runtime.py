from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PYTHON_LEGACY_ROOT = Path(__file__).resolve().parents[1]
try:
    REPO_ROOT = Path(__file__).resolve().parents[4]
except IndexError:
    # Docker: service files live at /app/, only 2 parents deep
    REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_CONFIG_PATH = REPO_ROOT / "config" / "config.yaml"
DEFAULT_CORS_ORIGINS = ("http://localhost:3000", "http://localhost:8080")


@dataclass(frozen=True)
class LegacyRuntimeConfig:
    api_host: str
    api_port: int
    api_reload: bool
    enhanced_api_port: int
    simple_llm_port: int
    log_level: str
    cors_origins: tuple[str, ...]
    rag_api_url: str
    ocr_api_url: str
    ocr_output_dir: str
    knowledge_base_dir: str
    knowledge_base_documents_dir: str
    include_legacy_kb_ocr: bool
    cache_ttl_seconds: int
    embedding_model_name: str
    embedding_model_path: str
    rerank_model_path: str
    rerank_model_name: str
    rerank_batch_size: int
    query_analysis_enabled: bool
    qdrant_host: str
    qdrant_port: int
    qdrant_timeout: int
    qdrant_pool_size: int
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str
    postgres_max_connections: int
    redis_host: str
    redis_port: int
    redis_db: int
    redis_password: str | None
    redis_max_connections: int
    redis_socket_timeout: int
    embedding_backend: str
    tei_url: str
    elasticsearch_url: str
    elasticsearch_index_name: str
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    models_dir: str
    sentence_transformers_home: str
    hf_home: str
    llama_cpp_path: str
    llama_model_path: str
    vllm_api_url: str
    vllm_model_name: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    openai_api_base: str
    openai_api_key: str
    local_model_dir: str


def bootstrap_runtime_environment() -> None:
    for env_path in (
        PYTHON_LEGACY_ROOT / ".env",
        PYTHON_LEGACY_ROOT.parent / ".env",
        REPO_ROOT / ".env",
    ):
        if env_path.exists():
            load_dotenv(env_path, override=False)


def _read_shared_config() -> dict[str, Any]:
    if not SHARED_CONFIG_PATH.exists():
        return {}

    with SHARED_CONFIG_PATH.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}

    return payload if isinstance(payload, dict) else {}


def _nested(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def _parse_cors_origins(raw_value: str | None, yaml_value: Any) -> tuple[str, ...]:
    if raw_value:
        return tuple(origin.strip() for origin in raw_value.split(",") if origin.strip())
    if isinstance(yaml_value, list):
        values = tuple(str(origin).strip() for origin in yaml_value if str(origin).strip())
        if values:
            return values
    return DEFAULT_CORS_ORIGINS


def _parse_bool(raw_value: str | None, default: bool) -> bool:
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _first_value(value: Any, default: str) -> str:
    if isinstance(value, list):
        for item in value:
            text = str(item).strip()
            if text:
                return text
        return default
    if value is None:
        return default
    text = str(value).strip()
    return text or default


@lru_cache(maxsize=1)
def _read_runtime_config_cached() -> LegacyRuntimeConfig:
    bootstrap_runtime_environment()
    shared = _read_shared_config()

    return LegacyRuntimeConfig(
        api_host=os.getenv("API_HOST") or _nested(shared, "server", "host", default="0.0.0.0"),
        api_port=int(
            os.getenv("API_PORT")
            or _nested(shared, "services", "api", "port", default=_nested(shared, "server", "port", default=8000))
        ),
        api_reload=_parse_bool(
            os.getenv("API_RELOAD") or os.getenv("UVICORN_RELOAD"),
            bool(_nested(shared, "server", "reload", default=False)),
        ),
        enhanced_api_port=int(os.getenv("ENHANCED_API_PORT") or 8001),
        simple_llm_port=int(os.getenv("SIMPLE_LLM_PORT") or 8003),
        log_level=str(os.getenv("LOG_LEVEL") or _nested(shared, "logging", "level", default="INFO")).upper(),
        rag_api_url=os.getenv("RAG_API", "http://localhost:8080"),
        ocr_api_url=os.getenv("OCR_API") or f"http://localhost:{_nested(shared, 'services', 'ocr', 'port', default=8001)}",
        ocr_output_dir=os.getenv("OCR_OUTPUT_DIR", str(REPO_ROOT / "data" / "ocr_outputs")),
        knowledge_base_dir=os.getenv("KNOWLEDGE_BASE_DIR", str(REPO_ROOT / "data" / "knowledge_base")),
        knowledge_base_documents_dir=os.getenv(
            "KB_DIR",
            str(Path(os.getenv("KNOWLEDGE_BASE_DIR", str(REPO_ROOT / 'data' / 'knowledge_base'))) / "documents"),
        ),
        include_legacy_kb_ocr=_parse_bool(os.getenv("INCLUDE_LEGACY_KB_OCR"), default=False),
        cache_ttl_seconds=int(os.getenv("CACHE_TTL_SECONDS") or _nested(shared, "cache", "ttl", default=3600)),
        embedding_model_name=os.getenv("EMBEDDING_MODEL_NAME")
        or _nested(shared, "models", "embedding", "name", default="BAAI/bge-m3"),
        embedding_model_path=os.getenv("EMBEDDING_MODEL", str(REPO_ROOT / "models" / "BAAI" / "bge-m3")),
        rerank_model_path=os.getenv(
            "RERANK_MODEL_PATH",
            str(
                REPO_ROOT
                / "models"
                / "models--BAAI--bge-reranker-v2-m3"
                / "snapshots"
                / "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
            ),
        ),
        rerank_model_name=os.getenv("RERANK_MODEL_NAME") or _nested(
            shared,
            "models",
            "rerank",
            "name",
            default="cross-encoder/ms-marco-MiniLM-L-12-v2",
        ),
        rerank_batch_size=int(
            os.getenv("RERANK_BATCH_SIZE")
            or _nested(shared, "models", "rerank", "batch_size", default=16)
        ),
        query_analysis_enabled=_parse_bool(os.getenv("ENABLE_QUERY_ANALYSIS"), default=False),
        cors_origins=_parse_cors_origins(
            os.getenv("CORS_ORIGINS"),
            _nested(shared, "services", "api", "cors_origins", default=None),
        ),
        qdrant_host=os.getenv("QDRANT_HOST") or _nested(shared, "vector_store", "host", default="localhost"),
        qdrant_port=int(os.getenv("QDRANT_PORT") or _nested(shared, "vector_store", "port", default=6333)),
        qdrant_timeout=int(
            os.getenv("QDRANT_TIMEOUT") or _nested(shared, "vector_store", "timeout", default=30)
        ),
        qdrant_pool_size=int(
            os.getenv("QDRANT_POOL_SIZE") or _nested(shared, "vector_store", "pool_size", default=10)
        ),
        postgres_host=os.getenv("POSTGRES_HOST", "localhost"),
        postgres_port=int(os.getenv("POSTGRES_PORT", "5432")),
        postgres_db=os.getenv("POSTGRES_DB") or _nested(shared, "structured_store", "database", default="rag_db"),
        postgres_user=os.getenv("POSTGRES_USER", "rag_user"),
        postgres_password=os.getenv("POSTGRES_PASSWORD") or os.getenv("PG_PASSWORD") or "",
        postgres_max_connections=int(os.getenv("POSTGRES_MAX_CONNECTIONS", "20")),
        redis_host=os.getenv("REDIS_HOST") or _nested(shared, "cache", "host", default="localhost"),
        redis_port=int(os.getenv("REDIS_PORT") or _nested(shared, "cache", "port", default=6379)),
        redis_db=int(os.getenv("REDIS_DB") or _nested(shared, "cache", "db", default=0)),
        redis_password=os.getenv("REDIS_PASSWORD"),
        redis_max_connections=int(
            os.getenv("REDIS_MAX_CONNECTIONS") or _nested(shared, "cache", "max_connections", default=50)
        ),
        redis_socket_timeout=int(os.getenv("REDIS_SOCKET_TIMEOUT", "10")),
        embedding_backend=os.getenv("EMBEDDING_BACKEND", "tei"),
        tei_url=os.getenv("TEI_URL") or _nested(shared, "models", "tei", "url", default="http://localhost:8003"),
        elasticsearch_url=os.getenv("ES_URL")
        or _first_value(
            _nested(shared, "keyword_store", "hosts", default=["http://localhost:9200"]),
            "http://localhost:9200",
        ),
        elasticsearch_index_name=os.getenv("ES_INDEX_NAME")
        or _nested(shared, "keyword_store", "index_name", default="documents"),
        neo4j_uri=os.getenv("NEO4J_URI") or _nested(shared, "graph_store", "uri", default="bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USERNAME")
        or os.getenv("NEO4J_USER")
        or _nested(shared, "graph_store", "username", default="neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD")
        or _nested(shared, "graph_store", "password", default="password"),
        models_dir=os.getenv("MODELS_DIR", str(REPO_ROOT / "models")),
        sentence_transformers_home=os.getenv("SENTENCE_TRANSFORMERS_HOME")
        or os.getenv("MODELS_DIR")
        or str(REPO_ROOT / "models"),
        hf_home=os.getenv("HF_HOME") or os.getenv("MODELS_DIR") or str(REPO_ROOT / "models"),
        llama_cpp_path=os.getenv("LLAMA_CPP_PATH", "/usr/local/bin/llama-cli"),
        llama_model_path=os.getenv(
            "LLAMA_MODEL_PATH",
            "/models/llama-3-8b-instruct-q4_k_m.gguf",
        ),
        vllm_api_url=os.getenv("VLLM_API_URL", "http://localhost:8000"),
        vllm_model_name=os.getenv("VLLM_MODEL_NAME", "meta-llama/Llama-2-7b-chat-hf"),
        llm_base_url=(
            os.getenv("LLM_BASE_URL")
            or os.getenv("DEEPSEEK_BASE_URL")
            or "https://api.deepseek.com"
        ),
        llm_api_key=(
            os.getenv("OPENAI_API_KEY")
            if (os.getenv("LLM_PROVIDER") or "deepseek").strip().lower() == "openai"
            else os.getenv("DEEPSEEK_API_KEY")
        )
        or os.getenv("LLM_API_KEY")
        or os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or "",
        llm_model=os.getenv("LLM_MODEL", "deepseek-chat"),
        openai_api_base=os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
        openai_api_key=os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY") or "",
        local_model_dir=os.getenv("LOCAL_MODEL_DIR", "/models"),
    )


def read_runtime_config(refresh: bool = False) -> LegacyRuntimeConfig:
    if refresh:
        _read_runtime_config_cached.cache_clear()
    return _read_runtime_config_cached()


def tool_pg_config(password_default: str = "rag_password") -> dict[str, Any]:
    runtime = read_runtime_config()
    return {
        "host": os.getenv("PG_HOST") or runtime.postgres_host,
        "port": int(os.getenv("PG_PORT", str(runtime.postgres_port))),
        "database": os.getenv("PG_DB") or runtime.postgres_db,
        "user": os.getenv("PG_USER") or runtime.postgres_user,
        "password": os.getenv("PG_PASSWORD") or runtime.postgres_password or password_default,
    }


def tool_pg_database(default: str | None = None) -> str:
    runtime = read_runtime_config()
    return os.getenv("PG_DB") or os.getenv("POSTGRES_DB") or default or runtime.postgres_db
