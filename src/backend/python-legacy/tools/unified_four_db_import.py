#!/usr/bin/env python3
"""
Unified Four-Database Import Script for OCR Data (Optimized)
Imports OCR results into PostgreSQL, Qdrant, Elasticsearch, and Neo4j.

Usage:
    ~/miniconda3/envs/py310/bin/python unified_four_db_import.py [--critical-only] [--max-files N]
"""

import os
import sys
import json
import re
import logging
import argparse
import hashlib
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional

import numpy as np
from sentence_transformers import SentenceTransformer

# Database clients
import psycopg2
from psycopg2.extras import execute_values, Json
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from neo4j import GraphDatabase
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

# Reduce ES verbosity
logging.getLogger('elasticsearch').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

# Paths
OCR_OUTPUT_DIR = Path("/home/l/rag-dashboard/data/ocr_outputs")
KB_DIR = Path("/home/l/rag-dashboard/data/knowledge_base/documents")
MODEL_PATH = "/home/l/rag-dashboard/models/BAAI/bge-m3"
EMBEDDING_DIM = 1024

# Chunking
CHUNK_SIZE = 400
CHUNK_OVERLAP = 50

# PostgreSQL
POSTGRES_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'rag_db',
    'user': 'rag_user',
    'password': 'rag_password'
}

# Qdrant
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
QDRANT_COLLECTION = "document_chunks"

# Elasticsearch
ES_HOST = "http://localhost:9200"
ES_INDEX = "documents"

# Neo4j
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password"

# Priority order for critical files (most important first)
CRITICAL_DOC_PATTERNS = [
    "费率标准（2023）", "费率标准（2025）", "费率标准2023", "费率标准2025",
    "2023-12", "2024-12",
    "2025-01", "2025-02", "2025-04", "2025-05", "2025-07", "2025-08",
    "2025-10", "2025-11", "2025-12",
    "2026", "价格信息",
    "装饰工程消耗量",
    "通风空调工程", "热力设备安装工程",
    "房屋建筑工程造价文件",
    "市政工程造价文件",
]

# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================

def init_postgres():
    logger.info("Initializing PostgreSQL...")
    conn = psycopg2.connect(**POSTGRES_CONFIG)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id SERIAL PRIMARY KEY,
            doc_id VARCHAR(255) UNIQUE NOT NULL,
            file_name VARCHAR(255),
            page_count INTEGER,
            status VARCHAR(50) DEFAULT 'completed',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS document_chunks (
            id SERIAL PRIMARY KEY,
            document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
            chunk_index INTEGER,
            content TEXT NOT NULL,
            page_number INTEGER,
            metadata JSONB DEFAULT '{}',
            embedding_id VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON document_chunks(document_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_embedding_id ON document_chunks(embedding_id)")
    conn.commit()
    cur.close()
    conn.close()
    logger.info("PostgreSQL initialized.")


def init_qdrant():
    logger.info("Initializing Qdrant...")
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    collections = [c.name for c in client.get_collections().collections]
    if QDRANT_COLLECTION not in collections:
        logger.info(f"Creating Qdrant collection: {QDRANT_COLLECTION}")
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config={"size": EMBEDDING_DIM, "distance": "Cosine"}
        )
    else:
        logger.info(f"Qdrant collection exists: {QDRANT_COLLECTION}")
    return client


def init_neo4j():
    logger.info("Initializing Neo4j...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:
        session.run("RETURN 1")
    logger.info("Neo4j connected.")
    return driver


def init_es():
    logger.info("Initializing Elasticsearch...")
    es = Elasticsearch([ES_HOST])
    if not es.ping():
        raise ConnectionError("Elasticsearch ping failed")
    logger.info("Elasticsearch connected.")
    return es


# ============================================================================
# OCR FILE COLLECTION
# ============================================================================

def collect_ocr_files() -> List[Path]:
    seen_names = set()
    files = []

    for f in OCR_OUTPUT_DIR.glob("*_ocr.json"):
        if "chunk" not in f.name.lower() or "merged" in f.name.lower():
            if f.name not in seen_names:
                seen_names.add(f.name)
                files.append(f)

    for f in OCR_OUTPUT_DIR.glob("*.json"):
        if f.name in ["processing_summary.json", "processed_documents.log"]:
            continue
        if "_ocr" not in f.name and "chunk" not in f.name.lower():
            base = f.stem
            ocr_counterpart = f"{base}_ocr.json"
            if ocr_counterpart in seen_names or f.name in seen_names:
                continue
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                if "pages" in data and "document_id" in data:
                    seen_names.add(f.name)
                    files.append(f)
            except Exception:
                pass

    for d in KB_DIR.iterdir():
        if d.is_dir():
            for f in d.glob("*_ocr.json"):
                if f.name not in seen_names:
                    seen_names.add(f.name)
                    files.append(f)

    def priority(p: Path) -> int:
        name = p.name
        if '费率标准' in name:
            return 0
        if '2023-12' in name or '2024-12' in name or '2025-12' in name:
            return 1
        if '2026' in name and '价格信息' in name:
            return 2
        if '消耗量标准' in name or '通风空调' in name or '热力设备' in name:
            return 3
        if '房屋建筑' in name or '市政工程' in name or '分部分项' in name:
            return 4
        if '2025' in name:
            return 5
        return 10

    def sort_key(p: Path):
        crit = 0 if is_critical_file(p) else 1
        return (crit, priority(p), p.name)

    result = sorted(files, key=sort_key)
    logger.info(f"Collected {len(result)} unique OCR files.")
    return result


def is_critical_file(path: Path) -> bool:
    name = path.name
    for pattern in CRITICAL_DOC_PATTERNS:
        if pattern in name:
            return True
    return False


# ============================================================================
# TEXT PROCESSING
# ============================================================================

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            for delim in ['\n\n', '\n', '。', '；', ' ']:
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


def parse_ocr_file(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except Exception as e:
        logger.error(f"Failed to parse {path.name}: {e}")
        return None


def extract_pages_text(ocr_data: Dict[str, Any]) -> List[Tuple[int, str]]:
    pages = []
    for page in ocr_data.get("pages", []):
        page_num = page.get("page_number", 0)
        texts = []
        for block in page.get("text_blocks", []):
            txt = block.get("text", "").strip()
            if txt:
                texts.append(txt)
        if texts:
            pages.append((page_num, "\n".join(texts)))
    return pages


# ============================================================================
# IMPORT LOGIC
# ============================================================================

class UnifiedImporter:
    def __init__(self):
        self.pg_conn = None
        self.pg_cur = None
        self.qdrant = None
        self.neo4j = None
        self.es = None
        self.model = None

    def initialize(self):
        init_postgres()
        self.pg_conn = psycopg2.connect(**POSTGRES_CONFIG)
        self.pg_cur = self.pg_conn.cursor()
        self.qdrant = init_qdrant()
        self.neo4j = init_neo4j()
        self.es = init_es()

        logger.info(f"Loading embedding model from {MODEL_PATH}...")
        self.model = SentenceTransformer(MODEL_PATH, device="cpu")
        logger.info("Model loaded.")

    def get_or_create_document(self, doc_id: str, file_name: str, page_count: int) -> int:
        self.pg_cur.execute("SELECT id FROM documents WHERE doc_id = %s", (doc_id,))
        row = self.pg_cur.fetchone()
        if row:
            return row[0]
        self.pg_cur.execute(
            "INSERT INTO documents (doc_id, file_name, page_count, status) VALUES (%s, %s, %s, %s) RETURNING id",
            (doc_id, file_name, page_count, "completed")
        )
        new_id = self.pg_cur.fetchone()[0]
        self.pg_conn.commit()
        return new_id

    def insert_chunks_to_postgres(self, document_id: int, chunks: List[Tuple[int, str, int]]) -> List[int]:
        """Batch insert chunks and return IDs."""
        chunk_ids = []
        BATCH = 100
        for i in range(0, len(chunks), BATCH):
            batch = chunks[i:i+BATCH]
            values = [(document_id, idx, content, page, Json({"source": "ocr"})) for idx, content, page in batch]
            execute_values(
                self.pg_cur,
                "INSERT INTO document_chunks (document_id, chunk_index, content, page_number, metadata) VALUES %s RETURNING id",
                values
            )
            rows = self.pg_cur.fetchall()
            chunk_ids.extend([r[0] for r in rows])
        self.pg_conn.commit()
        return chunk_ids

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        return self.model.encode(texts, batch_size=64, show_progress_bar=False, convert_to_numpy=True)

    def insert_to_qdrant(self, chunk_ids: List[int], document_id: int, chunks: List[Tuple[int, str, int]], embeddings: np.ndarray):
        points = []
        for i, (chunk_index, content, page_number) in enumerate(chunks):
            qid = chunk_ids[i]
            points.append(PointStruct(
                id=qid,
                vector=embeddings[i].tolist(),
                payload={
                    "chunk_id": qid,
                    "document_id": document_id,
                    "content": content,
                    "page_number": page_number,
                    "chunk_index": chunk_index,
                    "source": "ocr",
                    "created_at": datetime.now().isoformat()
                }
            ))
        self.qdrant.upsert(collection_name=QDRANT_COLLECTION, points=points)

    def insert_to_es(self, doc_id: str, chunks: List[Tuple[int, str, int]]):
        actions = []
        for chunk_index, content, page_number in chunks:
            actions.append({
                "_index": ES_INDEX,
                "_source": {
                    "doc_id": doc_id,
                    "chunk_id": f"{doc_id}_{chunk_index}",
                    "content": content,
                    "page_number": page_number,
                    "section": "",
                    "keywords": []
                }
            })
        if actions:
            bulk(self.es, actions, raise_on_error=False)

    def insert_to_neo4j(self, doc_id: str, file_name: str, page_count: int, chunks: List[Tuple[int, str, int]]):
        with self.neo4j.session() as session:
            session.run("""
                MERGE (d:Document {doc_id: $doc_id})
                SET d.file_name = $file_name, d.total_pages = $page_count
            """, doc_id=doc_id, file_name=file_name, page_count=page_count)

            chunk_data = []
            for chunk_index, content, page_number in chunks:
                chunk_id = f"{doc_id}_chunk_{chunk_index}"
                chunk_data.append({
                    "chunk_id": chunk_id,
                    "text": content[:5000],
                    "page_number": page_number,
                    "chunk_index": chunk_index
                })

            for i in range(0, len(chunk_data), 500):
                batch = chunk_data[i:i+500]
                session.run("""
                    UNWIND $chunks AS chunk
                    MERGE (c:TextChunk {chunk_id: chunk.chunk_id})
                    SET c.text = chunk.text, c.page_number = chunk.page_number,
                        c.chunk_index = chunk.chunk_index, c.source = 'ocr'
                    WITH chunk
                    MATCH (d:Document {doc_id: $doc_id})
                    MERGE (d)-[:CONTAINS]->(c)
                """, chunks=batch, doc_id=doc_id)

    def process_file(self, path: Path) -> int:
        logger.info(f"Processing: {path.name}")

        ocr_data = parse_ocr_file(path)
        if not ocr_data:
            return 0

        doc_id = ocr_data.get("document_id", path.stem)
        file_name = ocr_data.get("file_name", path.name)
        pages = extract_pages_text(ocr_data)
        page_count = len(pages)

        if not pages:
            logger.warning(f"  No text found in {path.name}")
            return 0

        # Check if already fully imported
        self.pg_cur.execute("SELECT id FROM documents WHERE doc_id = %s", (doc_id,))
        row = self.pg_cur.fetchone()
        if row:
            document_db_id = row[0]
            self.pg_cur.execute(
                "SELECT COUNT(*), COUNT(embedding_id) FROM document_chunks WHERE document_id = %s",
                (document_db_id,)
            )
            total, embedded = self.pg_cur.fetchone()
            if total > 0 and total == embedded:
                logger.info(f"  Already imported ({total} chunks), skipping.")
                return 0
            else:
                logger.info(f"  Partial import found ({embedded}/{total}), re-importing.")
                self.pg_cur.execute("DELETE FROM document_chunks WHERE document_id = %s", (document_db_id,))
                self.pg_conn.commit()

        # Chunk all pages
        all_chunks = []
        chunk_index = 0
        for page_num, page_text in pages:
            page_chunks = chunk_text(page_text)
            for ch in page_chunks:
                all_chunks.append((chunk_index, ch, page_num))
                chunk_index += 1

        if not all_chunks:
            logger.warning(f"  No chunks generated for {path.name}")
            return 0

        logger.info(f"  Pages: {page_count}, Chunks: {len(all_chunks)}")

        # 1. PostgreSQL
        logger.info("  -> PG insert...")
        document_db_id = self.get_or_create_document(doc_id, file_name, page_count)
        chunk_ids = self.insert_chunks_to_postgres(document_db_id, all_chunks)
        logger.info(f"  -> PG done, ids {chunk_ids[0]}..{chunk_ids[-1]}")

        # 2. Embedding
        logger.info("  -> Embedding...")
        texts = [ch[1] for ch in all_chunks]
        embeddings = self.embed_batch(texts)
        logger.info("  -> Embedding done")

        # 3. Qdrant
        logger.info("  -> Qdrant...")
        self.insert_to_qdrant(chunk_ids, document_db_id, all_chunks, embeddings)
        logger.info("  -> Qdrant done")

        # 4. Elasticsearch (bulk)
        logger.info("  -> ES...")
        self.insert_to_es(doc_id, all_chunks)
        logger.info("  -> ES done")

        # 5. Neo4j
        logger.info("  -> Neo4j...")
        self.insert_to_neo4j(doc_id, file_name, page_count, all_chunks)
        logger.info("  -> Neo4j done")

        # Update embedding_id in PostgreSQL
        logger.info("  -> PG update embedding_id...")
        values = [(str(cid), cid) for cid in chunk_ids]
        execute_values(
            self.pg_cur,
            "UPDATE document_chunks SET embedding_id = data.v::varchar FROM (VALUES %s) AS data(v, id) WHERE document_chunks.id = data.id",
            values
        )
        self.pg_conn.commit()

        logger.info(f"  Imported {len(all_chunks)} chunks to all databases.")
        return len(all_chunks)

    def run(self, critical_only: bool = False, max_files: Optional[int] = None):
        self.initialize()

        files = collect_ocr_files()
        if critical_only:
            files = [f for f in files if is_critical_file(f)]
            logger.info(f"Filtered to {len(files)} critical files.")
        if max_files:
            files = files[:max_files]

        total_chunks = 0
        processed = 0
        failed = 0

        for i, f in enumerate(files):
            try:
                n = self.process_file(f)
                total_chunks += n
                processed += 1
                logger.info(f"Progress: {i+1}/{len(files)} files, {total_chunks} total chunks")
            except Exception as e:
                logger.error(f"Failed to process {f.name}: {e}")
                failed += 1

        logger.info("=" * 60)
        logger.info(f"Import complete: {processed} files processed, {failed} failed")
        logger.info(f"Total chunks imported: {total_chunks}")
        logger.info("=" * 60)

        self.close()
        return total_chunks

    def close(self):
        if self.pg_cur:
            self.pg_cur.close()
        if self.pg_conn:
            self.pg_conn.close()
        if self.neo4j:
            self.neo4j.close()


def main():
    parser = argparse.ArgumentParser(description="Unified Four-Database OCR Import")
    parser.add_argument("--critical-only", action="store_true", help="Import only critical documents")
    parser.add_argument("--max-files", type=int, default=None, help="Max files to process")
    args = parser.parse_args()

    importer = UnifiedImporter()
    importer.run(critical_only=args.critical_only, max_files=args.max_files)


if __name__ == "__main__":
    main()
