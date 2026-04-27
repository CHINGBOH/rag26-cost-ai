#!/usr/bin/env python3
"""
Build parent/multi-vector text views for text_chunks.

View types:
1. raw_chunk: chunk text itself
2. parent_page_summary: aggregated page context (same doc_id + page_number)
3. semantic_terms: structured terms aligned to the same page
"""

from __future__ import annotations

import json
import os
from collections import defaultdict

import psycopg2
from psycopg2.extras import execute_values


PG_CONFIG = {
    "host": os.environ.get("PG_HOST", "localhost"),
    "port": int(os.environ.get("PG_PORT", "5432")),
    "database": os.environ.get("PG_DB", "rag_db"),
    "user": os.environ.get("PG_USER", "rag_user"),
    "password": os.environ.get("PG_PASSWORD") or "",
}


def get_pg_conn():
    return psycopg2.connect(**PG_CONFIG)


def _truncate_text(text: str, max_len: int = 1400) -> str:
    normalized = " ".join((text or "").split())
    return normalized[:max_len]


def _load_chunks(conn) -> list[tuple[int, str, int, str, list[float] | None]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id,
                   doc_id,
                   COALESCE(page_number, 0) AS page_number,
                   COALESCE(content, ''),
                   embedding
            FROM text_chunks
            ORDER BY id
            """
        )
        return cur.fetchall()


def _load_page_semantic_terms(conn) -> dict[tuple[str, int], str]:
    page_terms: dict[tuple[str, int], list[str]] = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT doc_id, COALESCE(page_number, 0) AS page_number,
                   material_name, COALESCE(specification, '')
            FROM price_records
            WHERE COALESCE(material_name, '') <> ''
            """
        )
        for doc_id, page_number, material_name, specification in cur.fetchall():
            term = " ".join(part for part in [material_name, specification] if part).strip()
            if term:
                page_terms[(doc_id or "", int(page_number or 0))].append(term)

        cur.execute(
            """
            SELECT doc_id, COALESCE(page_number, 0) AS page_number, fee_name
            FROM fee_rates
            WHERE COALESCE(fee_name, '') <> ''
            """
        )
        for doc_id, page_number, fee_name in cur.fetchall():
            page_terms[(doc_id or "", int(page_number or 0))].append(fee_name)

    collapsed: dict[tuple[str, int], str] = {}
    for key, values in page_terms.items():
        deduped: list[str] = []
        seen = set()
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            deduped.append(value)
            if len(deduped) >= 24:
                break
        collapsed[key] = _truncate_text(" | ".join(deduped), max_len=900)
    return collapsed


def build_views() -> dict[str, int]:
    conn = get_pg_conn()
    try:
        chunks = _load_chunks(conn)
        if not chunks:
            return {"raw_chunk": 0, "parent_page_summary": 0, "semantic_terms": 0}

        page_chunks: dict[tuple[str, int], list[str]] = defaultdict(list)
        for _, doc_id, page_number, content, _ in chunks:
            page_chunks[(doc_id or "", int(page_number or 0))].append(content or "")

        page_summaries = {
            key: _truncate_text(" ".join(values[:6]), max_len=1200)
            for key, values in page_chunks.items()
        }
        page_terms = _load_page_semantic_terms(conn)

        rows: list[tuple[int, str, str, str, list[float] | None]] = []
        counts = {"raw_chunk": 0, "parent_page_summary": 0, "semantic_terms": 0}
        for chunk_id, doc_id, page_number, content, source_embedding in chunks:
            page_key = (doc_id or "", int(page_number or 0))
            raw_text = _truncate_text(content or "", max_len=1200)
            if raw_text:
                rows.append(
                    (
                        int(chunk_id),
                        "raw_chunk",
                        raw_text,
                        json.dumps({"source": "text_chunks.content"}, ensure_ascii=False),
                        source_embedding,
                    )
                )
                counts["raw_chunk"] += 1

            summary_text = page_summaries.get(page_key, "")
            if summary_text:
                rows.append(
                    (
                        int(chunk_id),
                        "parent_page_summary",
                        summary_text,
                        json.dumps(
                            {"source": "page_aggregate", "doc_id": doc_id or "", "page_number": page_number or 0},
                            ensure_ascii=False,
                        ),
                        None,
                    )
                )
                counts["parent_page_summary"] += 1

            semantic_terms = page_terms.get(page_key, "")
            if semantic_terms:
                rows.append(
                    (
                        int(chunk_id),
                        "semantic_terms",
                        semantic_terms,
                        json.dumps(
                            {"source": "structured_alignment", "doc_id": doc_id or "", "page_number": page_number or 0},
                            ensure_ascii=False,
                        ),
                        None,
                    )
                )
                counts["semantic_terms"] += 1

        with conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO chunk_vector_views (chunk_id, view_type, view_text, metadata, embedding)
                VALUES %s
                ON CONFLICT (chunk_id, view_type) DO UPDATE SET
                    view_text = EXCLUDED.view_text,
                    metadata = EXCLUDED.metadata,
                    embedding = CASE
                        WHEN EXCLUDED.embedding IS NOT NULL
                        THEN EXCLUDED.embedding
                        WHEN chunk_vector_views.view_text = EXCLUDED.view_text
                        THEN chunk_vector_views.embedding
                        ELSE NULL
                    END
                """,
                rows,
                template="(%s, %s, %s, %s::jsonb, %s::vector)",
                page_size=500,
            )
        conn.commit()
        return counts
    finally:
        conn.close()


def main() -> None:
    counts = build_views()
    print(
        "chunk_vector_views upserted: "
        f"raw_chunk={counts['raw_chunk']}, "
        f"parent_page_summary={counts['parent_page_summary']}, "
        f"semantic_terms={counts['semantic_terms']}"
    )


if __name__ == "__main__":
    main()

