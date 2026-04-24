"""
PostgreSQL + pgvector 导入器
"""

import json
import os
import logging
import hashlib
from typing import List, Dict, Optional
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

logger = logging.getLogger(__name__)


class PGStore:
    """PostgreSQL存储适配器"""

    def __init__(self, host: str = "localhost", port: int = 5432,
                 dbname: str = "rag_db", user: str = "rag_user",
                 password: str = os.environ.get("POSTGRES_PASSWORD", "rag_password")):
        self.conn = psycopg2.connect(
            host=host, port=port, dbname=dbname,
            user=user, password=password
        )
        self.conn.autocommit = False
        logger.info(f"✅ PostgreSQL connected: {host}:{port}/{dbname}")

    def close(self):
        if self.conn:
            self.conn.close()

    def doc_code_from_name(self, filename: str) -> str:
        return hashlib.md5(filename.encode()).hexdigest()[:16]

    def register_document(self, file_name: str, file_path: str,
                          doc_type: str, period: str,
                          total_pages: int, status: str = 'imported') -> int:
        """注册文档，返回document_id"""
        doc_code = self.doc_code_from_name(file_name)
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO documents (file_name, file_path, doc_type, period, total_pages, status, doc_code)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (doc_code) DO UPDATE SET
                    total_pages = EXCLUDED.total_pages,
                    file_path = EXCLUDED.file_path,
                    status = EXCLUDED.status
                RETURNING id
            """, (file_name, file_path, doc_type, period, total_pages, status, doc_code))
            doc_id = cur.fetchone()[0]
            self.conn.commit()
        logger.info(f"Document registered: id={doc_id}, code={doc_code}")
        return doc_id

    def insert_price_records(self, doc_id: int, period: str, records: List[Dict],
                             source_doc: str) -> int:
        """批量插入价格记录"""
        if not records:
            return 0
        
        batch = []
        for r in records:
            batch.append((
                doc_id, period,
                r.get('category'),
                r.get('material_name', '')[:200],
                r.get('spec', '')[:200],
                r.get('unit'),
                r.get('price'),
                r.get('page_number'),
                json.dumps(r, ensure_ascii=False),
                r.get('price_formula'),
                r.get('seq_no'),
                r.get('confidence', 0.85),
                source_doc
            ))
        
        inserted = 0
        with self.conn.cursor() as cur:
            for i in range(0, len(batch), 200):
                chunk = batch[i:i+200]
                execute_values(cur, """
                    INSERT INTO price_records
                        (document_id, period, category, material_name, spec, unit,
                         price, page_number, source_row, price_formula, seq_no,
                         confidence, source_doc)
                    VALUES %s
                    ON CONFLICT DO NOTHING
                """, chunk)
                inserted += cur.rowcount
            self.conn.commit()
        logger.info(f"Inserted {inserted} price records")
        return inserted

    def insert_text_chunks(self, doc_id: int, period: str, chunks: List[Dict]) -> int:
        """批量插入文本块"""
        if not chunks:
            return 0
        
        batch = []
        for i, tc in enumerate(chunks):
            batch.append((
                doc_id, i,
                tc['content'][:4000],
                tc.get('page_number'),
                period,
                tc.get('doc_type', 'price_info'),
                tc.get('chunk_type', 'article'),
                tc.get('confidence', 0.85)
            ))
        
        inserted = 0
        with self.conn.cursor() as cur:
            for i in range(0, len(batch), 200):
                chunk = batch[i:i+200]
                execute_values(cur, """
                    INSERT INTO text_chunks
                        (document_id, chunk_index, content, page_number, period,
                         doc_type, chunk_type, confidence)
                    VALUES %s
                    ON CONFLICT DO NOTHING
                """, chunk)
                inserted += cur.rowcount
            self.conn.commit()
        logger.info(f"Inserted {inserted} text chunks")
        return inserted

    def insert_chart_series(self, doc_id: int, doc_code: str, series_list: List[Dict]) -> int:
        """批量插入图表时间序列"""
        if not series_list:
            return 0
        
        inserted = 0
        with self.conn.cursor() as cur:
            for s in series_list:
                try:
                    cur.execute("""
                        INSERT INTO chart_series
                            (doc_code, document_id, page_number, chart_title,
                             series_name, year_month, price_value, extraction_method, confidence)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (doc_code, series_name, year_month) DO NOTHING
                    """, (
                        doc_code, doc_id, s.get('page_number'),
                        s.get('chart_title'), s.get('series_name'),
                        s.get('year_month'), s.get('price_value'),
                        s.get('extraction_method', 'ocr_table'),
                        s.get('confidence', 0.85)
                    ))
                    inserted += cur.rowcount
                except Exception as e:
                    logger.warning(f"Chart insert error: {e}")
            self.conn.commit()
        logger.info(f"Inserted {inserted} chart series")
        return inserted

    def insert_quarantine(self, doc_id: int, doc_code: str, records: List[Dict],
                          quarantine_type: str = 'auto') -> int:
        """将异常记录放入隔离区"""
        if not records:
            return 0
        
        inserted = 0
        with self.conn.cursor() as cur:
            for r in records:
                try:
                    cur.execute("""
                        INSERT INTO ocr_quarantine
                            (doc_code, target_table, quarantine_type, raw_data, error_detail)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (
                        doc_code, 'price_records',
                        r.get('_status', quarantine_type),
                        json.dumps(r, ensure_ascii=False),
                        '; '.join(r.get('_issues', []))
                    ))
                    inserted += cur.rowcount
                except Exception as e:
                    logger.warning(f"Quarantine insert error: {e}")
            self.conn.commit()
        logger.info(f"Inserted {inserted} quarantine records")
        return inserted

    def update_ocr_task(self, file_path: str, file_name: str, doc_code: str,
                        total_pages: int, page_number: int,
                        page_type: str, status: str, result_json: Optional[Dict] = None):
        """更新OCR任务状态"""
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ocr_tasks
                    (file_path, file_name, doc_code, total_pages, page_number,
                     page_type, status, result_json, processed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (file_path, page_number) DO UPDATE SET
                    page_type = EXCLUDED.page_type,
                    status = EXCLUDED.status,
                    result_json = EXCLUDED.result_json,
                    processed_at = EXCLUDED.processed_at
            """, (file_path, file_name, doc_code, total_pages, page_number,
                  page_type, status, json.dumps(result_json) if result_json else None))
            self.conn.commit()

    def get_pending_pages(self, file_path: str, total_pages: int) -> List[int]:
        """获取尚未完成的页码（断点续传）"""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT page_number FROM ocr_tasks
                WHERE file_path = %s AND status = 'completed'
            """, (file_path,))
            completed = {r[0] for r in cur.fetchall()}
        
        pending = [i for i in range(1, total_pages + 1) if i not in completed]
        return pending

    def clear_document_data(self, doc_id: int):
        """清理文档的所有关联数据（用于重新导入）"""
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM price_records WHERE document_id = %s", (doc_id,))
            cur.execute("DELETE FROM text_chunks WHERE document_id = %s", (doc_id,))
            cur.execute("DELETE FROM chart_series WHERE document_id = %s", (doc_id,))
            cur.execute("DELETE FROM ocr_quarantine WHERE doc_code = (SELECT doc_code FROM documents WHERE id = %s)", (doc_id,))
            self.conn.commit()
        logger.info(f"Cleared old data for document_id={doc_id}")

    def update_embeddings(self, table: str, id_column: str, embeddings: List[tuple]):
        """
        批量更新embedding向量
        Args:
            table: 表名
            id_column: ID列名
            embeddings: [(id, vector), ...]
        """
        if not embeddings:
            return
        
        with self.conn.cursor() as cur:
            for row_id, vector in embeddings:
                cur.execute(f"""
                    UPDATE {table} SET embedding = %s::vector
                    WHERE {id_column} = %s
                """, (vector, row_id))
            self.conn.commit()
        logger.info(f"Updated {len(embeddings)} embeddings in {table}")
