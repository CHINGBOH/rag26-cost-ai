#!/usr/bin/env python3
"""
Generate embeddings for text_chunks and upsert to Qdrant documents collection.
Uses local BAAI/bge-m3 model.
Updates text_chunks.embedding column in PostgreSQL.
"""
import os
import sys
import psycopg2
import numpy as np
from pathlib import Path
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

MODEL_PATH = '/home/l/rag-dashboard/models/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181'
QDRANT_URL = 'http://localhost:6333'
COLLECTION = 'documents'
BATCH_SIZE = 128

DB_CONFIG = dict(host='localhost', dbname='rag_db', user='rag_user', password=os.environ.get('POSTGRES_PASSWORD', 'rag_password'))


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def main():
    print('Loading BGE-M3 model...')
    model = SentenceTransformer(MODEL_PATH, device='cuda')
    print('Model loaded, embedding dim:', model.get_sentence_embedding_dimension())
    print('Model device:', next(model.parameters()).device)

    qdrant = QdrantClient(url=QDRANT_URL)
    conn = get_conn()
    cur = conn.cursor()

    # Check if embedding column exists
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name='text_chunks' AND column_name='embedding'
    """)
    has_embedding_col = cur.fetchone() is not None

    if not has_embedding_col:
        print('Adding embedding column to text_chunks...')
        cur.execute("ALTER TABLE text_chunks ADD COLUMN embedding vector(1024)")
        conn.commit()

    # Fetch chunks needing embeddings
    cur.execute("""
        SELECT id, document_id, page_number, chunk_index, content, chunk_type
        FROM text_chunks
        WHERE embedding IS NULL
        ORDER BY document_id, chunk_index
    """)
    rows = cur.fetchall()
    print(f'Chunks to embed: {len(rows)}')

    if not rows:
        print('All chunks already have embeddings.')
    else:
        # Process in batches
        total_upserted = 0
        for batch_start in range(0, len(rows), BATCH_SIZE):
            batch = rows[batch_start:batch_start + BATCH_SIZE]
            ids = [r[0] for r in batch]
            contents = [r[4] or '' for r in batch]

            # Generate embeddings
            embeddings = model.encode(contents, normalize_embeddings=True, batch_size=BATCH_SIZE)

            # Update PG
            for chunk_id, emb in zip(ids, embeddings):
                emb_list = emb.tolist()
                cur.execute(
                    "UPDATE text_chunks SET embedding = %s WHERE id = %s",
                    (emb_list, chunk_id)
                )

            # Build Qdrant points
            points = []
            for row, emb in zip(batch, embeddings):
                chunk_id, doc_id, page_num, chunk_idx, content, chunk_type = row
                points.append(PointStruct(
                    id=chunk_id,
                    vector=emb.tolist(),
                    payload={
                        'document_id': doc_id,
                        'page_number': page_num,
                        'chunk_index': chunk_idx,
                        'content': content[:500],
                        'chunk_type': chunk_type,
                    }
                ))

            # Upsert to Qdrant
            qdrant.upsert(collection_name=COLLECTION, points=points)
            total_upserted += len(points)

            conn.commit()
            progress = min(batch_start + BATCH_SIZE, len(rows))
            print(f'  [{progress}/{len(rows)}] embedded & upserted', end='\r')

        print(f'\nDone. Total upserted to Qdrant: {total_upserted}')

    # Also upsert price_records as searchable content (top 2000 by relevance)
    print('\nIndexing price records to Qdrant...')
    cur.execute("""
        SELECT id, document_id, period, category, material_name, spec, unit, price, page_number
        FROM price_records
        WHERE material_name IS NOT NULL
        ORDER BY document_id, id
        LIMIT 5000
    """)
    price_rows = cur.fetchall()
    print(f'Price records to index: {len(price_rows)}')

    price_points = []
    price_texts = []
    for row in price_rows:
        pid, doc_id, period, category, mat_name, spec, unit, price, page_num = row
        text = f"{mat_name or ''} {spec or ''} {category or ''} {period or ''} 价格:{price or ''}元/{unit or ''}"
        price_texts.append(text.strip())

    if price_texts:
        # Use large ID offset to avoid collision with text_chunks (which start from 1)
        ID_OFFSET = 1_000_000
        for batch_start in range(0, len(price_texts), BATCH_SIZE):
            batch_texts = price_texts[batch_start:batch_start + BATCH_SIZE]
            batch_rows = price_rows[batch_start:batch_start + BATCH_SIZE]
            embeddings = model.encode(batch_texts, normalize_embeddings=True, batch_size=BATCH_SIZE)

            points = []
            for row, text, emb in zip(batch_rows, batch_texts, embeddings):
                pid, doc_id, period, category, mat_name, spec, unit, price, page_num = row
                points.append(PointStruct(
                    id=ID_OFFSET + pid,
                    vector=emb.tolist(),
                    payload={
                        'type': 'price_record',
                        'price_record_id': pid,
                        'document_id': doc_id,
                        'period': period,
                        'category': category,
                        'material_name': mat_name,
                        'spec': spec,
                        'unit': unit,
                        'price': float(price) if price else None,
                        'page_number': page_num,
                        'content': text,
                    }
                ))

            qdrant.upsert(collection_name=COLLECTION, points=points)
            progress = min(batch_start + BATCH_SIZE, len(price_rows))
            print(f'  [{progress}/{len(price_rows)}] price records indexed', end='\r')

        print(f'\nDone indexing {len(price_rows)} price records')

    # Final stats
    print('\n=== Final Qdrant collection info ===')
    info = qdrant.get_collection(COLLECTION)
    print(f'Qdrant {COLLECTION}: {info.points_count} points')

    cur.close()
    conn.close()
    print('Done!')


if __name__ == '__main__':
    main()
