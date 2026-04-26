#!/usr/bin/env python3
"""
Build explicit concept graph and concept->evidence mappings.

Graph model:
- canonical_concepts
- concept_relations (co-occurrence)
- concept_evidence_links:
  canonical concept -> structured row -> OCR row -> PDF page -> embedding chunk
"""

from __future__ import annotations

import json
import os
import re

import psycopg2


PG_CONFIG = {
    "host": os.environ.get("PG_HOST", "localhost"),
    "port": int(os.environ.get("PG_PORT", "5432")),
    "database": os.environ.get("PG_DB", "rag_db"),
    "user": os.environ.get("PG_USER", "rag_user"),
    "password": os.environ.get("PG_PASSWORD") or "",
}

CLAUSE_THEMES = {
    "安全文明施工费": ["安全文明施工费", "文明施工费", "组成内容", "计取规定"],
    "赶工措施费": ["赶工措施费", "推荐系数", "赶工"],
    "企业管理费": ["企业管理费", "计算基数", "推荐费率"],
    "利润率": ["利润率", "参考范围", "推荐费率"],
    "总包管理服务费": ["总包管理服务费", "发包人供应材料", "计算基数"],
    "填写要求": ["填写要求", "应按什么要求填写", "工程概况表"],
}


def get_pg_conn():
    return psycopg2.connect(**PG_CONFIG)


def normalize_concept_name(name: str) -> str:
    return re.sub(r"\s+", "", (name or "")).replace("～", "~").replace("㎡", "m²").strip().lower()


def upsert_concepts(conn) -> dict[str, int]:
    counts = {"material": 0, "fee_item": 0, "clause_theme": 0}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT material_name, COUNT(*) AS n
            FROM price_records
            WHERE COALESCE(material_name, '') <> ''
            GROUP BY material_name
            ORDER BY n DESC
            """
        )
        for concept_name, n in cur.fetchall():
            normalized = normalize_concept_name(concept_name)
            cur.execute(
                """
                INSERT INTO canonical_concepts
                    (concept_type, concept_name, normalized_name, preferred_route, metadata)
                VALUES
                    ('material', %s, %s, 'price_query', %s::jsonb)
                ON CONFLICT (concept_type, normalized_name) DO UPDATE SET
                    concept_name = EXCLUDED.concept_name,
                    preferred_route = EXCLUDED.preferred_route,
                    metadata = EXCLUDED.metadata
                """,
                (concept_name, normalized, json.dumps({"source": "price_records", "row_count": int(n)})),
            )
            counts["material"] += 1

        cur.execute(
            """
            SELECT fee_name, COUNT(*) AS n
            FROM fee_rates
            WHERE COALESCE(fee_name, '') <> ''
            GROUP BY fee_name
            ORDER BY n DESC
            """
        )
        for concept_name, n in cur.fetchall():
            normalized = normalize_concept_name(concept_name)
            cur.execute(
                """
                INSERT INTO canonical_concepts
                    (concept_type, concept_name, normalized_name, preferred_route, metadata)
                VALUES
                    ('fee_item', %s, %s, 'text_search', %s::jsonb)
                ON CONFLICT (concept_type, normalized_name) DO UPDATE SET
                    concept_name = EXCLUDED.concept_name,
                    preferred_route = EXCLUDED.preferred_route,
                    metadata = EXCLUDED.metadata
                """,
                (concept_name, normalized, json.dumps({"source": "fee_rates", "row_count": int(n)})),
            )
            counts["fee_item"] += 1

        for concept_name, terms in CLAUSE_THEMES.items():
            normalized = normalize_concept_name(concept_name)
            cur.execute(
                """
                INSERT INTO canonical_concepts
                    (concept_type, concept_name, normalized_name, aliases, preferred_route, metadata)
                VALUES
                    ('clause_theme', %s, %s, %s, 'text_search', %s::jsonb)
                ON CONFLICT (concept_type, normalized_name) DO UPDATE SET
                    aliases = EXCLUDED.aliases,
                    preferred_route = EXCLUDED.preferred_route,
                    metadata = EXCLUDED.metadata
                """,
                (concept_name, normalized, terms, json.dumps({"source": "clause_theme", "terms": terms})),
            )
            counts["clause_theme"] += 1

    conn.commit()
    return counts


def rebuild_evidence_links(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM concept_evidence_links")

        # material concepts -> structured/ocr rows
        cur.execute(
            """
            INSERT INTO concept_evidence_links
                (concept_id, evidence_kind, source_table, source_id, doc_id, file_name, page_number,
                 parent_doc_id, parent_page_number, chunk_id, link_score, metadata)
            SELECT c.id, 'structured_row', 'price_records', pr.id,
                   COALESCE(pr.doc_id, ''), COALESCE(pr.file_name, ''), COALESCE(pr.page_number, 0),
                   COALESCE(pr.doc_id, ''), COALESCE(pr.page_number, 0), 0, 0.95,
                   jsonb_build_object(
                     'year_month', COALESCE(pr.year_month, ''),
                     'unit', COALESCE(pr.unit, ''),
                     'category', COALESCE(pr.category, '')
                   )
            FROM price_records pr
            JOIN canonical_concepts c
              ON c.concept_type = 'material'
             AND c.concept_name = pr.material_name
            ON CONFLICT DO NOTHING
            """
        )
        material_structured = cur.rowcount

        cur.execute(
            """
            INSERT INTO concept_evidence_links
                (concept_id, evidence_kind, source_table, source_id, doc_id, file_name, page_number,
                 parent_doc_id, parent_page_number, chunk_id, link_score, metadata)
            SELECT c.id, 'ocr_row', 'price_records', pr.id,
                   COALESCE(pr.doc_id, ''), COALESCE(pr.file_name, ''), COALESCE(pr.page_number, 0),
                   COALESCE(pr.doc_id, ''), COALESCE(pr.page_number, 0), 0, 0.92,
                   jsonb_build_object('ocr_source', COALESCE(pr.metadata->>'source', 'unknown'))
            FROM price_records pr
            JOIN canonical_concepts c
              ON c.concept_type = 'material'
             AND c.concept_name = pr.material_name
            ON CONFLICT DO NOTHING
            """
        )
        material_ocr = cur.rowcount

        # material concepts -> page + chunks
        cur.execute(
            """
            INSERT INTO concept_evidence_links
                (concept_id, evidence_kind, source_table, source_id, doc_id, file_name, page_number,
                 parent_doc_id, parent_page_number, chunk_id, link_score, metadata)
            SELECT DISTINCT c.id, 'pdf_page', 'text_chunks', tc.id,
                   COALESCE(tc.doc_id, ''), COALESCE(tc.file_name, ''), COALESCE(tc.page_number, 0),
                   COALESCE(tc.doc_id, ''), COALESCE(tc.page_number, 0), 0, 0.90,
                   jsonb_build_object('source', 'text_chunks_page')
            FROM text_chunks tc
            JOIN canonical_concepts c
              ON c.concept_type = 'material'
             AND tc.content ILIKE ('%' || c.concept_name || '%')
            ON CONFLICT DO NOTHING
            """
        )
        material_pdf = cur.rowcount

        cur.execute(
            """
            INSERT INTO concept_evidence_links
                (concept_id, evidence_kind, source_table, source_id, doc_id, file_name, page_number,
                 parent_doc_id, parent_page_number, chunk_id, link_score, metadata)
            SELECT DISTINCT c.id, 'embedding_chunk', 'text_chunks', tc.id,
                   COALESCE(tc.doc_id, ''), COALESCE(tc.file_name, ''), COALESCE(tc.page_number, 0),
                   COALESCE(tc.doc_id, ''), COALESCE(tc.page_number, 0), tc.id, 0.88,
                   jsonb_build_object('source', 'text_chunks_embedding')
            FROM text_chunks tc
            JOIN canonical_concepts c
              ON c.concept_type = 'material'
             AND tc.content ILIKE ('%' || c.concept_name || '%')
            ON CONFLICT DO NOTHING
            """
        )
        material_chunks = cur.rowcount

        # fee concepts -> structured/ocr rows
        cur.execute(
            """
            INSERT INTO concept_evidence_links
                (concept_id, evidence_kind, source_table, source_id, doc_id, file_name, page_number,
                 parent_doc_id, parent_page_number, chunk_id, link_score, metadata)
            SELECT c.id, 'structured_row', 'fee_rates', fr.id,
                   COALESCE(fr.doc_id, ''), '', COALESCE(fr.page_number, 0),
                   COALESCE(fr.doc_id, ''), COALESCE(fr.page_number, 0), 0, 0.95,
                   jsonb_build_object(
                     'standard_year', COALESCE(fr.standard_year, ''),
                     'fee_category', COALESCE(fr.fee_category, '')
                   )
            FROM fee_rates fr
            JOIN canonical_concepts c
              ON c.concept_type = 'fee_item'
             AND c.concept_name = fr.fee_name
            ON CONFLICT DO NOTHING
            """
        )
        fee_structured = cur.rowcount

        cur.execute(
            """
            INSERT INTO concept_evidence_links
                (concept_id, evidence_kind, source_table, source_id, doc_id, file_name, page_number,
                 parent_doc_id, parent_page_number, chunk_id, link_score, metadata)
            SELECT DISTINCT c.id, 'pdf_page', 'text_chunks', tc.id,
                   COALESCE(tc.doc_id, ''), COALESCE(tc.file_name, ''), COALESCE(tc.page_number, 0),
                   COALESCE(tc.doc_id, ''), COALESCE(tc.page_number, 0), 0, 0.90,
                   jsonb_build_object('source', 'text_chunks_page')
            FROM text_chunks tc
            JOIN canonical_concepts c
              ON c.concept_type = 'fee_item'
             AND tc.content ILIKE ('%' || c.concept_name || '%')
            ON CONFLICT DO NOTHING
            """
        )
        fee_pdf = cur.rowcount

        cur.execute(
            """
            INSERT INTO concept_evidence_links
                (concept_id, evidence_kind, source_table, source_id, doc_id, file_name, page_number,
                 parent_doc_id, parent_page_number, chunk_id, link_score, metadata)
            SELECT DISTINCT c.id, 'embedding_chunk', 'text_chunks', tc.id,
                   COALESCE(tc.doc_id, ''), COALESCE(tc.file_name, ''), COALESCE(tc.page_number, 0),
                   COALESCE(tc.doc_id, ''), COALESCE(tc.page_number, 0), tc.id, 0.87,
                   jsonb_build_object('source', 'text_chunks_embedding')
            FROM text_chunks tc
            JOIN canonical_concepts c
              ON c.concept_type = 'fee_item'
             AND tc.content ILIKE ('%' || c.concept_name || '%')
            ON CONFLICT DO NOTHING
            """
        )
        fee_chunks = cur.rowcount

        # clause theme concepts -> text chunks (pdf + embedding chunk)
        cur.execute(
            """
            SELECT id, aliases
            FROM canonical_concepts
            WHERE concept_type = 'clause_theme'
            """
        )
        clause_rows = cur.fetchall()
        clause_links = 0
        clause_chunks = 0
        for concept_id, aliases in clause_rows:
            terms = [term for term in (aliases or []) if term]
            if not terms:
                continue
            clauses = " OR ".join(["tc.content ILIKE %s"] * len(terms))
            params = [f"%{term}%" for term in terms]
            cur.execute(
                f"""
                INSERT INTO concept_evidence_links
                    (concept_id, evidence_kind, source_table, source_id, doc_id, file_name, page_number,
                     parent_doc_id, parent_page_number, chunk_id, link_score, metadata)
                SELECT DISTINCT %s, 'pdf_page', 'text_chunks', tc.id,
                       COALESCE(tc.doc_id, ''), COALESCE(tc.file_name, ''), COALESCE(tc.page_number, 0),
                       COALESCE(tc.doc_id, ''), COALESCE(tc.page_number, 0), 0, 0.91,
                       jsonb_build_object('source', 'clause_terms')
                FROM text_chunks tc
                WHERE {clauses}
                ON CONFLICT DO NOTHING
                """,
                [concept_id, *params],
            )
            clause_links += cur.rowcount

            cur.execute(
                f"""
                INSERT INTO concept_evidence_links
                    (concept_id, evidence_kind, source_table, source_id, doc_id, file_name, page_number,
                     parent_doc_id, parent_page_number, chunk_id, link_score, metadata)
                SELECT DISTINCT %s, 'embedding_chunk', 'text_chunks', tc.id,
                       COALESCE(tc.doc_id, ''), COALESCE(tc.file_name, ''), COALESCE(tc.page_number, 0),
                       COALESCE(tc.doc_id, ''), COALESCE(tc.page_number, 0), tc.id, 0.86,
                       jsonb_build_object('source', 'clause_terms')
                FROM text_chunks tc
                WHERE {clauses}
                ON CONFLICT DO NOTHING
                """,
                [concept_id, *params],
            )
            clause_chunks += cur.rowcount

    conn.commit()
    return {
        "material_structured": int(material_structured),
        "material_ocr": int(material_ocr),
        "material_pdf": int(material_pdf),
        "material_chunks": int(material_chunks),
        "fee_structured": int(fee_structured),
        "fee_pdf": int(fee_pdf),
        "fee_chunks": int(fee_chunks),
        "clause_pdf": int(clause_links),
        "clause_chunks": int(clause_chunks),
    }


def rebuild_concept_relations(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM concept_relations")
        cur.execute(
            """
            INSERT INTO concept_relations
                (source_concept_id, target_concept_id, relation_kind, relation_weight, metadata)
            SELECT l1.concept_id, l2.concept_id, 'co_occurrence',
                   LEAST(10.0, COUNT(*)::numeric) AS relation_weight,
                   jsonb_build_object(
                       'doc_page_pairs', COUNT(*),
                       'doc_id', MAX(l1.doc_id)
                   ) AS metadata
            FROM concept_evidence_links l1
            JOIN concept_evidence_links l2
              ON l1.doc_id = l2.doc_id
             AND l1.page_number = l2.page_number
             AND l1.concept_id < l2.concept_id
            WHERE l1.doc_id <> ''
            GROUP BY l1.concept_id, l2.concept_id
            HAVING COUNT(*) >= 1
            ON CONFLICT DO NOTHING
            """
        )
        inserted = cur.rowcount

        cur.execute(
            """
            INSERT INTO concept_relations
                (source_concept_id, target_concept_id, relation_kind, relation_weight, metadata)
            SELECT target_concept_id, source_concept_id, relation_kind, relation_weight, metadata
            FROM concept_relations
            ON CONFLICT DO NOTHING
            """
        )
    conn.commit()
    return int(inserted)


def summarize(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM canonical_concepts")
        concepts = int(cur.fetchone()[0] or 0)
        cur.execute("SELECT COUNT(*) FROM concept_relations")
        relations = int(cur.fetchone()[0] or 0)
        cur.execute("SELECT COUNT(*) FROM concept_evidence_links")
        links = int(cur.fetchone()[0] or 0)
    return {"concepts": concepts, "relations": relations, "evidence_links": links}


def main() -> None:
    conn = get_pg_conn()
    try:
        concept_counts = upsert_concepts(conn)
        link_counts = rebuild_evidence_links(conn)
        relation_count = rebuild_concept_relations(conn)
        summary = summarize(conn)
    finally:
        conn.close()

    report = {
        "concept_upsert": concept_counts,
        "evidence_links": link_counts,
        "relation_inserted_forward": relation_count,
        "summary": summary,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

