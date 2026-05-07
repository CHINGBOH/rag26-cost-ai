from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
from typing import Callable

import yaml


@dataclass(frozen=True)
class RuntimeOverrideSpec:
    type_name: str
    validator: Callable[[str], bool]
    normalizer: Callable[[str], str]
    legacy_default: str


ALLOWED_RUNTIME_OVERRIDES: dict[str, RuntimeOverrideSpec] = {
    "score_threshold": RuntimeOverrideSpec(
        type_name="float",
        validator=lambda value: 0.0 <= float(value) <= 1.0,
        normalizer=lambda value: f"{float(value):.4f}".rstrip("0").rstrip("."),
        legacy_default="0.25",
    ),
    "top_k": RuntimeOverrideSpec(
        type_name="int",
        validator=lambda value: 1 <= int(value) <= 50,
        normalizer=lambda value: str(int(value)),
        legacy_default="10",
    ),
    "rerank_enabled": RuntimeOverrideSpec(
        type_name="bool",
        validator=lambda value: value.lower() in {"true", "false", "1", "0"},
        normalizer=lambda value: "true" if value.lower() in {"true", "1"} else "false",
        legacy_default="true",
    ),
    "keyword_backend": RuntimeOverrideSpec(
        type_name="str",
        validator=lambda value: value in {"es", "pg"},
        normalizer=lambda value: value,
        legacy_default="pg",
    ),
    "vector_backend": RuntimeOverrideSpec(
        type_name="str",
        validator=lambda value: value in {"qdrant", "milvus", "pgvector"},
        normalizer=lambda value: "pgvector" if value == "qdrant" else value,
        legacy_default="qdrant",
    ),
}


def validate_runtime_override(key: str, value: str) -> tuple[bool, str | None]:
    spec = ALLOWED_RUNTIME_OVERRIDES.get(key)
    if spec is None:
        return False, f"配置项 {key} 不在白名单"
    try:
        if not spec.validator(value):
            return False, f"值 {value!r} 未通过校验（期望 {spec.type_name} 且符合范围）"
    except Exception as exc:
        return False, f"值校验失败: {exc}"
    return True, None


def normalize_runtime_override_value(key: str, value: str) -> str:
    spec = ALLOWED_RUNTIME_OVERRIDES[key]
    return spec.normalizer(value)


def legacy_default_runtime_override(key: str) -> str:
    return ALLOWED_RUNTIME_OVERRIDES[key].legacy_default


def get_runtime_override(key: str, default, *, refresh: bool = False):
    if refresh:
        _load_runtime_override_rows.cache_clear()
    rows = _load_runtime_override_rows()
    if key not in rows:
        return default
    raw_value = rows[key]
    return _coerce_runtime_override_value(key, raw_value, default)


def apply_runtime_override(
    *,
    key: str,
    value: str,
    apply: bool,
    reason: str,
    actor: str = "guide-agent",
) -> tuple[int, str, str]:
    normalized_value = normalize_runtime_override_value(key, value)
    old_value = get_runtime_override(key, legacy_default_runtime_override(key), refresh=True)
    old_value_str = _stringify_override_value(old_value)

    conn = None
    try:
        conn = _borrow_pg_connection()
        with conn.cursor() as cur:
            _ensure_runtime_override_tables(cur)
            cur.execute(
                """
                INSERT INTO runtime_config_audit (config_key, old_value, new_value, applied, reason, actor)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (key, old_value_str, normalized_value, bool(apply), reason or "(未填)", actor),
            )
            audit_id = int(cur.fetchone()[0])
            if apply:
                cur.execute(
                    """
                    INSERT INTO runtime_config_overrides
                        (config_key, config_value, updated_at, updated_by, reason, audit_id)
                    VALUES (%s, %s, NOW(), %s, %s, %s)
                    ON CONFLICT (config_key) DO UPDATE SET
                        config_value = EXCLUDED.config_value,
                        updated_at = EXCLUDED.updated_at,
                        updated_by = EXCLUDED.updated_by,
                        reason = EXCLUDED.reason,
                        audit_id = EXCLUDED.audit_id
                    """,
                    (key, normalized_value, actor, reason or "(未填)", audit_id),
                )
            conn.commit()
    finally:
        if conn is not None:
            _return_pg_connection(conn)

    _load_runtime_override_rows.cache_clear()
    return audit_id, old_value_str, normalized_value


@lru_cache(maxsize=1)
def _load_runtime_override_rows() -> dict[str, str]:
    conn = None
    try:
        conn = _borrow_pg_connection()
        with conn.cursor() as cur:
            _ensure_runtime_override_tables(cur)
            cur.execute("SELECT config_key, config_value FROM runtime_config_overrides")
            rows = cur.fetchall()
        conn.commit()
        return {str(key): str(value) for key, value in rows}
    except Exception:
        if conn is not None:
            conn.rollback()
        return {}
    finally:
        if conn is not None:
            _return_pg_connection(conn)


def _coerce_runtime_override_value(key: str, raw_value: str, default):
    if key == "score_threshold":
        return float(raw_value)
    if key == "top_k":
        return int(raw_value)
    if key == "rerank_enabled":
        return raw_value.lower() == "true"
    return raw_value or default


def _stringify_override_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _ensure_runtime_override_tables(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_config_audit (
            id SERIAL PRIMARY KEY,
            ts TIMESTAMPTZ DEFAULT now(),
            config_key TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            applied BOOLEAN NOT NULL DEFAULT false,
            reason TEXT,
            actor TEXT DEFAULT 'guide-agent'
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_config_overrides (
            config_key TEXT PRIMARY KEY,
            config_value TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_by TEXT NOT NULL DEFAULT 'guide-agent',
            reason TEXT,
            audit_id INTEGER REFERENCES runtime_config_audit(id)
        )
        """
    )


def _borrow_pg_connection():
    import psycopg2

    return psycopg2.connect(**_postgres_connection_kwargs())


def _return_pg_connection(conn) -> None:
    try:
        conn.close()
    except Exception:
        pass


def _postgres_connection_kwargs() -> dict[str, str | int]:
    if database_url := os.environ.get("DATABASE_URL"):
        return _kwargs_from_database_url(database_url)
    if any(os.environ.get(key) for key in ("PG_HOST", "PG_PORT", "PG_DB", "PG_USER", "PG_PASSWORD", "POSTGRES_PASSWORD")):
        return {
            "host": os.environ.get("PG_HOST", "localhost"),
            "port": int(os.environ.get("PG_PORT", "5432")),
            "dbname": os.environ.get("PG_DB", "rag_db"),
            "user": os.environ.get("PG_USER", "rag_user"),
            "password": os.environ.get("PG_PASSWORD") or os.environ.get("POSTGRES_PASSWORD", "rag_password"),
            "connect_timeout": 5,
        }

    repo_root = Path(__file__).resolve().parents[4]
    config_path = repo_root / "config" / "config.yaml"
    file_config = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as handle:
            file_config = yaml.safe_load(handle) or {}
    structured = file_config.get("structured_store", {}) if isinstance(file_config, dict) else {}
    return {
        "host": structured.get("host", "localhost"),
        "port": int(structured.get("port", 5432)),
        "dbname": structured.get("database", "rag_db"),
        "user": structured.get("username", "rag_user"),
        "password": structured.get("password", "rag_password"),
        "connect_timeout": 5,
    }


def _kwargs_from_database_url(database_url: str) -> dict[str, str | int]:
    from urllib.parse import urlparse

    parsed = urlparse(database_url)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "dbname": (parsed.path or "/rag_db").lstrip("/"),
        "user": parsed.username or "rag_user",
        "password": parsed.password or "",
        "connect_timeout": 5,
    }
