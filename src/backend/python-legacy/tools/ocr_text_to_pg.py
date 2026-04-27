#!/usr/bin/env python3
"""
OCR JSON → text_chunks
批量 embedding + 批量插入，避免逐条生成向量。
"""

import os
import sys
import json
import re
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

project_root = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(project_root))

import psycopg2
from psycopg2.extras import execute_values
from psycopg2 import sql as pgsql

from src.database.scripts.ocr_output_reconciliation import build_ocr_source_candidate_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OCR_DIR = Path(os.environ.get("OCR_OUTPUT_DIR", project_root / "data" / "ocr_outputs"))
KB_DIR = Path(os.environ.get("KB_DIR", project_root / "data" / "knowledge_base" / "documents"))
INCLUDE_LEGACY_KB_OCR = os.environ.get("INCLUDE_LEGACY_KB_OCR", "").lower() in {"1", "true", "yes"}
_SKIP_OCR_FILENAMES = {"processing_summary.json", "processed_documents.log", "_scan_state.json"}

PG_CONFIG = {
    "host": os.environ.get("PG_HOST", "localhost"),
    "port": int(os.environ.get("PG_PORT", "5432")),
    "database": os.environ.get("PG_DB", "rag_db"),
    "user": os.environ.get("PG_USER", "rag_user"),
    "password": os.environ.get("PG_PASSWORD", "rag_password"),
}

CHUNK_SIZE = 400
CHUNK_OVERLAP = 50
_PERIOD_RE = re.compile(r"(20\d{2})[-年](\d{1,2})")
_DOCUMENT_REGISTRY_SUPPORTED: Optional[bool] = None
_DOCUMENT_REGISTRY_KEY_COLUMN: Optional[str] = None
_REGISTRY_COUNT_COLUMNS: dict[str, bool] = {}


def get_pg_conn():
    return psycopg2.connect(**PG_CONFIG)


def extract_period(name: str) -> str | None:
    match = _PERIOD_RE.search(name)
    if not match:
        return None
    return f"{match.group(1)}-{int(match.group(2)):02d}"


def _has_registry_column(cur, column_name: str) -> bool:
    if column_name in _REGISTRY_COUNT_COLUMNS:
        return _REGISTRY_COUNT_COLUMNS[column_name]
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'document_registry' AND column_name = %s
        LIMIT 1
        """,
        (column_name,),
    )
    exists = cur.fetchone() is not None
    _REGISTRY_COUNT_COLUMNS[column_name] = exists
    return exists


def _get_registry_key_column(cur) -> Optional[str]:
    global _DOCUMENT_REGISTRY_SUPPORTED, _DOCUMENT_REGISTRY_KEY_COLUMN

    if _DOCUMENT_REGISTRY_SUPPORTED is False:
        return None
    if _DOCUMENT_REGISTRY_KEY_COLUMN is not None:
        return _DOCUMENT_REGISTRY_KEY_COLUMN

    for candidate in ("doc_id", "doc_code"):
        if _has_registry_column(cur, candidate):
            _DOCUMENT_REGISTRY_KEY_COLUMN = candidate
            _DOCUMENT_REGISTRY_SUPPORTED = True
            return candidate

    _DOCUMENT_REGISTRY_SUPPORTED = False
    logger.warning("document_registry upsert skipped: no doc_id/doc_code column found")
    return None


def register_document(cur, doc_id: str, file_name: str, total_pages: int) -> None:
    global _DOCUMENT_REGISTRY_SUPPORTED

    if _DOCUMENT_REGISTRY_SUPPORTED is False:
        return

    key_column = _get_registry_key_column(cur)
    if not key_column:
        return

    doc_type = "price_info" if extract_period(file_name) else "quota"
    cur.execute("SAVEPOINT text_register_doc")
    try:
        cur.execute(
            pgsql.SQL(
                """
                INSERT INTO document_registry ({}, file_name, doc_type, total_pages, status)
                VALUES (%s, %s, %s, %s, 'imported')
                ON CONFLICT ({}) DO UPDATE SET
                    file_name = EXCLUDED.file_name,
                    doc_type = EXCLUDED.doc_type,
                    total_pages = EXCLUDED.total_pages,
                    status = 'imported'
                """
            ).format(pgsql.Identifier(key_column), pgsql.Identifier(key_column)),
            (doc_id, file_name, doc_type, total_pages),
        )
    except Exception as exc:
        cur.execute("ROLLBACK TO SAVEPOINT text_register_doc")
        cur.execute("RELEASE SAVEPOINT text_register_doc")
        _DOCUMENT_REGISTRY_SUPPORTED = False
        logger.warning(f"document_registry upsert skipped: {exc}")
    else:
        cur.execute("RELEASE SAVEPOINT text_register_doc")
        _DOCUMENT_REGISTRY_SUPPORTED = True


def update_registry_count(cur, doc_id: str, column_name: str, table_name: str) -> None:
    global _DOCUMENT_REGISTRY_SUPPORTED

    if _DOCUMENT_REGISTRY_SUPPORTED is False or _REGISTRY_COUNT_COLUMNS.get(column_name) is False:
        return

    key_column = _get_registry_key_column(cur)
    if not key_column:
        return
    if not _has_registry_column(cur, column_name):
        return

    cur.execute(
        pgsql.SQL("SELECT COUNT(*) FROM {} WHERE doc_id = %s").format(pgsql.Identifier(table_name)),
        (doc_id,),
    )
    total = int(cur.fetchone()[0] or 0)

    cur.execute("SAVEPOINT text_update_registry_count")
    try:
        cur.execute(
            pgsql.SQL("UPDATE document_registry SET {} = %s WHERE {} = %s").format(
                pgsql.Identifier(column_name),
                pgsql.Identifier(key_column),
            ),
            (total, doc_id),
        )
    except Exception as exc:
        cur.execute("ROLLBACK TO SAVEPOINT text_update_registry_count")
        cur.execute("RELEASE SAVEPOINT text_update_registry_count")
        _REGISTRY_COUNT_COLUMNS[column_name] = False
        if _DOCUMENT_REGISTRY_SUPPORTED is not False:
            logger.warning(f"document_registry.{column_name} update skipped: {exc}")
    else:
        cur.execute("RELEASE SAVEPOINT text_update_registry_count")
        _REGISTRY_COUNT_COLUMNS[column_name] = True


def normalize_document_label(value: str) -> str:
    return re.sub(r"\s+", "", (value or "")).strip()


def score_ocr_source_candidate(path: Path, data: Dict[str, Any]) -> tuple[int, int, int, int, int, str]:
    return build_ocr_source_candidate_score(path, data, OCR_DIR)


def refresh_text_chunks(cur, doc_id: str, file_name: str) -> int:
    normalized_file_name = normalize_document_label(file_name)
    if normalized_file_name:
        cur.execute(
            """
            DELETE FROM text_chunks
            WHERE doc_id = %s
               OR regexp_replace(COALESCE(file_name, ''), '\\s+', '', 'g') = %s
            """,
            (doc_id, normalized_file_name),
        )
    else:
        cur.execute("DELETE FROM text_chunks WHERE doc_id = %s", (doc_id,))
    return int(cur.rowcount or 0)


def _get_embedding_model():
    import torch
    from sentence_transformers import SentenceTransformer

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for OCR text import embeddings")

    model_path = os.environ.get("EMBEDDING_MODEL", str(project_root / "models" / "BAAI" / "bge-m3"))
    logger.info(f"Loading embedding model: {model_path} [cuda]")
    return SentenceTransformer(model_path, device="cuda")


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    text = text.strip()
    if len(text) <= chunk_size:
        return [text] if text else []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            for delim in ["\n\n", "\n", "。", "；", " "]:
                pos = text.rfind(delim, start + chunk_size // 2, end)
                if pos != -1:
                    end = pos + len(delim)
                    break
        chunk = text[start:end].strip()
        if chunk and len(chunk) > 10:
            chunks.append(chunk)
        start = end - overlap if end < len(text) else len(text)
        if start >= len(text):
            break
    return chunks


def extract_text_from_page(page: Dict) -> str:
    parts = []
    for block in page.get("text_blocks", []):
        txt = block.get("text", "").strip()
        if txt:
            parts.append(txt)
    for table in page.get("tables", []):
        md = table.get("markdown", "").strip()
        if md and len(md) > 20:
            parts.append(f"[表格]\n{md}")
        else:
            raw = table.get("raw_text", "").strip()
            if raw:
                parts.append(f"[表格]\n{raw}")
    return "\n".join(parts)


def import_ocr_file(path: Path, conn, model) -> Tuple[int, int]:
    logger.info(f"Processing text: {path.name}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to parse {path}: {e}")
        return 0, 0

    doc_id = data.get("document_id", path.stem)
    file_name = data.get("file_name", path.name)
    pages = data.get("pages", [])

    try:
        with conn.cursor() as cur:
            register_document(cur, doc_id, file_name, len(pages))
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.warning(f"Failed to register {path.name} in document_registry: {exc}")

    # 收集所有 chunks（暂存，稍后批量 embedding）
    chunk_records = []  # [(chunk_index, content, page_number, section, metadata)]
    chunk_idx = 0
    for page in pages:
        page_num = page.get("page_number", 0)
        text = extract_text_from_page(page)
        if not text:
            continue
        chunks = chunk_text(text)
        for chunk in chunks:
            chunk_records.append((
                chunk_idx, chunk, page_num, None,
                json.dumps({"source": "ocr_text", "page": page_num})
            ))
            chunk_idx += 1

    if not chunk_records:
        try:
            with conn.cursor() as cur:
                deleted = refresh_text_chunks(cur, doc_id, file_name)
                update_registry_count(cur, doc_id, "text_chunk_count", "text_chunks")
            conn.commit()
            logger.info(f"  No text chunks in {path.name}; cleared {deleted} existing rows")
        except Exception as e:
            conn.rollback()
            logger.error(f"  Failed to refresh empty text rows for {path.name}: {e}")
        return 0, len(pages)

    # 批量生成 embedding
    texts = [r[1] for r in chunk_records]
    try:
        embeddings = model.encode(texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True)
        embedding_list = embeddings.tolist()
    except Exception as e:
        logger.error(f"  Batch embedding failed: {e}")
        embedding_list = [None] * len(chunk_records)

    # 批量插入
    records = []
    for i, rec in enumerate(chunk_records):
        records.append((
            doc_id, file_name, rec[0], rec[1], rec[2], rec[3], rec[4],
            embedding_list[i],
        ))

    try:
        with conn.cursor() as cur:
            deleted = refresh_text_chunks(cur, doc_id, file_name)
            execute_values(
                cur,
                """
                INSERT INTO text_chunks
                (doc_id, file_name, chunk_index, content, page_number, section, metadata, embedding)
                VALUES %s
                ON CONFLICT DO NOTHING
                """,
                records,
                template="(%s, %s, %s, %s, %s, %s, %s, %s::vector)",
            )
            update_registry_count(cur, doc_id, "text_chunk_count", "text_chunks")
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"  Insert failed: {e}")
        return 0, len(pages)

    logger.info(
        f"  ✅ Refreshed {len(records)} text chunks from {path.name}"
        + (f" (replaced {deleted} existing rows)" if deleted else "")
    )
    return len(records), len(pages)


def find_ocr_files() -> List[Path]:
    files_by_identity: Dict[str, tuple[tuple[int, int, int, int, str], Path]] = {}
    scan_dirs = [OCR_DIR]
    if INCLUDE_LEGACY_KB_OCR:
        scan_dirs.append(KB_DIR)
    for d in scan_dirs:
        if not d.exists():
            continue
        for f in sorted(d.rglob("*.json")):
            if f.name in _SKIP_OCR_FILENAMES or "chunk" in f.name.lower():
                continue
            try:
                with open(f, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except Exception:
                continue
            if not isinstance(data.get("pages"), list):
                continue
            file_name = str(data.get("file_name") or f.name)
            source_identity = normalize_document_label(file_name) or normalize_document_label(f.stem) or str(f)
            candidate = (score_ocr_source_candidate(f, data), f)
            current = files_by_identity.get(source_identity)
            if current is None or candidate[0] > current[0]:
                files_by_identity[source_identity] = candidate
    return sorted(path for _, path in files_by_identity.values())


def main():
    conn = get_pg_conn()
    files = find_ocr_files()
    logger.info(f"Found {len(files)} OCR files to process")

    model = _get_embedding_model()

    total_chunks = 0
    total_pages = 0
    for f in files:
        try:
            chunks, pages = import_ocr_file(f, conn, model)
            total_chunks += chunks
            total_pages += pages
        except Exception as e:
            logger.error(f"Failed to import {f}: {e}")

    logger.info(f"=== Total: {total_chunks} text chunks from {total_pages} pages ===")
    conn.close()


if __name__ == "__main__":
    main()
