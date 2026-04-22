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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OCR_DIR = Path(os.environ.get("OCR_OUTPUT_DIR", project_root / "data" / "ocr_outputs"))
KB_DIR = Path(os.environ.get("KB_DIR", project_root / "data" / "knowledge_base" / "documents"))

PG_CONFIG = {
    "host": os.environ.get("PG_HOST", "localhost"),
    "port": int(os.environ.get("PG_PORT", "5432")),
    "database": os.environ.get("PG_DB", "rag_db"),
    "user": os.environ.get("PG_USER", "rag_user"),
    "password": os.environ.get("PG_PASSWORD", "rag_password"),
}

CHUNK_SIZE = 400
CHUNK_OVERLAP = 50


def get_pg_conn():
    return psycopg2.connect(**PG_CONFIG)


def _get_embedding_model():
    from sentence_transformers import SentenceTransformer
    model_path = os.environ.get("EMBEDDING_MODEL", str(project_root / "models" / "BAAI" / "bge-m3"))
    logger.info(f"Loading embedding model: {model_path}")
    return SentenceTransformer(model_path, device="cpu")


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
        logger.info(f"  No text chunks in {path.name}")
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

    with conn.cursor() as cur:
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
        try:
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"  Insert failed: {e}")

    logger.info(f"  ✅ Imported {len(records)} text chunks from {path.name}")
    return len(records), len(pages)


def find_ocr_files() -> List[Path]:
    files = set()
    for d in [OCR_DIR, KB_DIR]:
        if not d.exists():
            continue
        for f in d.rglob("*_ocr.json"):
            files.add(f)
        for f in d.rglob("*.json"):
            if f.name in ("processing_summary.json", "processed_documents.log"):
                continue
            if "_ocr" in f.name or "chunk" not in f.name.lower():
                files.add(f)
    return sorted(files)


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
