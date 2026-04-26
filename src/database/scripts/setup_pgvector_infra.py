#!/usr/bin/env python3
"""
Bootstrap pgvector infrastructure for retrieval tables.

What this script does:
1. Ensures required PostgreSQL extensions (vector, pg_trgm).
2. Resolves embedding dimension (CLI override > embedding backend probe).
3. Ensures `embedding` columns exist with the expected vector dimension.
4. Ensures retrieval indexes (HNSW + trigram + tsv GIN) exist.

Usage examples:
    python src/database/scripts/setup_pgvector_infra.py --dimension 1024
    python src/database/scripts/setup_pgvector_infra.py --probe-backend
    python src/database/scripts/setup_pgvector_infra.py --probe-backend --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable

import psycopg2


ROOT = Path(__file__).resolve().parents[3]
RETRIEVAL_SERVICE_ROOT = ROOT / "src/backend/retrieval-service"

PG_CONFIG = {
    "host": os.environ.get("PG_HOST", "localhost"),
    "port": int(os.environ.get("PG_PORT", "5432")),
    "database": os.environ.get("PG_DB", "rag_db"),
    "user": os.environ.get("PG_USER", "rag_user"),
    "password": os.environ.get("PG_PASSWORD") or "",
}

TARGET_TABLES = ("text_chunks", "price_records", "fee_rates", "canonical_concepts", "chunk_vector_views")


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def get_pg_conn():
    return psycopg2.connect(**PG_CONFIG)


def table_exists(cur, table_name: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
    return cur.fetchone()[0] is not None


def column_exists(cur, table_name: str, column_name: str) -> bool:
    cur.execute(
        """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
              AND column_name = %s
            LIMIT 1
        """,
        (table_name, column_name),
    )
    return cur.fetchone() is not None


def get_vector_dimension(cur, table_name: str, column_name: str = "embedding") -> int | None:
    cur.execute(
        """
            SELECT a.atttypmod
            FROM pg_attribute a
            WHERE a.attrelid = %s::regclass
              AND a.attname = %s
              AND NOT a.attisdropped
            LIMIT 1
        """,
        (f"public.{table_name}", column_name),
    )
    row = cur.fetchone()
    if not row:
        return None
    typmod = int(row[0] or 0)
    if typmod <= 0:
        return None
    return typmod


def execute(cur, statement: str, dry_run: bool = False) -> None:
    print(f"{'[DRY-RUN] ' if dry_run else ''}{statement.strip()}")
    if not dry_run:
        cur.execute(statement)


def ensure_extensions(cur, dry_run: bool) -> None:
    execute(cur, "CREATE EXTENSION IF NOT EXISTS vector;", dry_run)
    execute(cur, "CREATE EXTENSION IF NOT EXISTS pg_trgm;", dry_run)


def ensure_embedding_column(cur, table_name: str, dim: int, dry_run: bool) -> None:
    if not table_exists(cur, table_name):
        print(f"Skip table '{table_name}': does not exist")
        return

    if not column_exists(cur, table_name, "embedding"):
        execute(
            cur,
            f"ALTER TABLE public.{_quote_ident(table_name)} "
            f"ADD COLUMN embedding vector({dim});",
            dry_run,
        )
        return

    current_dim = get_vector_dimension(cur, table_name, "embedding")
    if current_dim is None:
        raise RuntimeError(
            f"Unable to detect vector dimension for public.{table_name}.embedding. "
            "Please inspect the column type manually."
        )
    if current_dim != dim:
        raise RuntimeError(
            f"Dimension mismatch for public.{table_name}.embedding: "
            f"db={current_dim}, expected={dim}. "
            "Fix by recreating the column or re-running with the correct dimension."
        )
    print(f"OK public.{table_name}.embedding dimension={current_dim}")


def ensure_text_chunks_tsv(cur, dry_run: bool) -> None:
    if not table_exists(cur, "text_chunks"):
        return
    if column_exists(cur, "text_chunks", "tsv"):
        return
    execute(
        cur,
        """
        ALTER TABLE public.text_chunks
        ADD COLUMN tsv tsvector
        GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED;
        """,
        dry_run,
    )


def ensure_indexes(cur, dry_run: bool) -> None:
    index_statements: Iterable[tuple[str, str, str]] = (
        (
            "text_chunks",
            "idx_tc_embedding",
            """
            CREATE INDEX IF NOT EXISTS idx_tc_embedding
            ON public.text_chunks USING hnsw (embedding vector_cosine_ops)
            WHERE embedding IS NOT NULL;
            """,
        ),
        (
            "text_chunks",
            "idx_tc_tsv",
            """
            CREATE INDEX IF NOT EXISTS idx_tc_tsv
            ON public.text_chunks USING gin (tsv);
            """,
        ),
        (
            "text_chunks",
            "idx_tc_content",
            """
            CREATE INDEX IF NOT EXISTS idx_tc_content
            ON public.text_chunks USING gin (content gin_trgm_ops);
            """,
        ),
        (
            "price_records",
            "idx_pr_embedding",
            """
            CREATE INDEX IF NOT EXISTS idx_pr_embedding
            ON public.price_records USING hnsw (embedding vector_cosine_ops)
            WHERE embedding IS NOT NULL;
            """,
        ),
        (
            "price_records",
            "idx_pr_name_trgm",
            """
            CREATE INDEX IF NOT EXISTS idx_pr_name_trgm
            ON public.price_records USING gin (material_name gin_trgm_ops);
            """,
        ),
        (
            "price_records",
            "idx_pr_spec_trgm",
            """
            CREATE INDEX IF NOT EXISTS idx_pr_spec_trgm
            ON public.price_records USING gin (specification gin_trgm_ops);
            """,
        ),
        (
            "fee_rates",
            "idx_fr_embedding",
            """
            CREATE INDEX IF NOT EXISTS idx_fr_embedding
            ON public.fee_rates USING hnsw (embedding vector_cosine_ops)
            WHERE embedding IS NOT NULL;
            """,
        ),
        (
            "fee_rates",
            "idx_fr_name_trgm",
            """
            CREATE INDEX IF NOT EXISTS idx_fr_name_trgm
            ON public.fee_rates USING gin (fee_name gin_trgm_ops);
            """,
        ),
        (
            "canonical_concepts",
            "idx_cc_embedding",
            """
            CREATE INDEX IF NOT EXISTS idx_cc_embedding
            ON public.canonical_concepts USING hnsw (embedding vector_cosine_ops)
            WHERE embedding IS NOT NULL;
            """,
        ),
        (
            "canonical_concepts",
            "idx_cc_name_trgm",
            """
            CREATE INDEX IF NOT EXISTS idx_cc_name_trgm
            ON public.canonical_concepts USING gin (concept_name gin_trgm_ops);
            """,
        ),
        (
            "chunk_vector_views",
            "idx_cvv_embedding",
            """
            CREATE INDEX IF NOT EXISTS idx_cvv_embedding
            ON public.chunk_vector_views USING hnsw (embedding vector_cosine_ops)
            WHERE embedding IS NOT NULL;
            """,
        ),
        (
            "chunk_vector_views",
            "idx_cvv_view_text_trgm",
            """
            CREATE INDEX IF NOT EXISTS idx_cvv_view_text_trgm
            ON public.chunk_vector_views USING gin (view_text gin_trgm_ops);
            """,
        ),
    )

    for table_name, _, ddl in index_statements:
        if not table_exists(cur, table_name):
            print(f"Skip indexes for '{table_name}': table does not exist")
            continue
        if table_name == "text_chunks" and "idx_tc_tsv" in ddl and not column_exists(cur, "text_chunks", "tsv"):
            print("Skip idx_tc_tsv: tsv column does not exist")
            continue
        if table_name == "price_records" and "idx_pr_spec_trgm" in ddl and not column_exists(
            cur, "price_records", "specification"
        ):
            print("Skip idx_pr_spec_trgm: specification column does not exist")
            continue
        execute(cur, ddl, dry_run)


def probe_embedding_dimension() -> tuple[int, dict]:
    if str(RETRIEVAL_SERVICE_ROOT) not in sys.path:
        sys.path.insert(0, str(RETRIEVAL_SERVICE_ROOT))
    from infrastructure.embedding_service import EmbeddingService  # pylint: disable=import-error

    service = EmbeddingService(use_mock=False)
    info = service.runtime_info()
    return int(service.dimension), info


def resolve_dimension(cli_dimension: int, probe_backend: bool) -> tuple[int, dict]:
    if cli_dimension > 0:
        return cli_dimension, {"source": "cli"}
    if probe_backend:
        dim, info = probe_embedding_dimension()
        info = {**info, "source": "embedding_backend_probe"}
        return dim, info
    raise ValueError("Dimension is required. Use --dimension or enable --probe-backend.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Setup pgvector infra for retrieval tables.")
    parser.add_argument("--dimension", type=int, default=0, help="Embedding vector dimension (e.g., 1024).")
    parser.add_argument(
        "--probe-backend",
        action="store_true",
        help="Probe embedding backend to auto-detect vector dimension.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print SQL without executing.")
    args = parser.parse_args()

    dimension, source_info = resolve_dimension(args.dimension, args.probe_backend)
    print(f"Resolved embedding dimension: {dimension} ({source_info})")

    conn = get_pg_conn()
    try:
        with conn.cursor() as cur:
            ensure_extensions(cur, args.dry_run)
            for table_name in TARGET_TABLES:
                ensure_embedding_column(cur, table_name, dimension, args.dry_run)
            ensure_text_chunks_tsv(cur, args.dry_run)
            ensure_indexes(cur, args.dry_run)
        if args.dry_run:
            conn.rollback()
            print("Dry-run complete. No changes committed.")
        else:
            conn.commit()
            print("pgvector infrastructure setup complete.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
