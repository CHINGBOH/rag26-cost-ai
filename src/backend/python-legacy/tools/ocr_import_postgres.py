#!/usr/bin/env python3
"""
OCR数据PostgreSQL导入脚本
将OCR数据导入到PostgreSQL数据库
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

import psycopg2
from psycopg2.extras import execute_batch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

OCR_OUTPUT_DIR = "/home/l/rag-dashboard/data/ocr_outputs"

# PostgreSQL配置
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'rag_db',
    'user': 'rag_user',
    'password': os.environ.get('POSTGRES_PASSWORD', 'rag_password')
}

class OCRPostgresImporter:
    """OCR数据PostgreSQL导入器"""

    def __init__(self):
        self.connection = None
        self.cursor = None

    def initialize(self):
        """初始化数据库连接"""
        logger.info("初始化PostgreSQL连接...")

        try:
            self.connection = psycopg2.connect(**DB_CONFIG)
            self.cursor = self.connection.cursor()
            logger.info("PostgreSQL连接成功")

            self._create_tables()
        except Exception as e:
            logger.error(f"PostgreSQL连接失败: {e}")
            raise

    def _create_tables(self):
        """创建表结构"""
        logger.info("创建表结构...")

        # 创建documents表
        create_documents_table = """
        CREATE TABLE IF NOT EXISTS documents (
            doc_id VARCHAR(255) PRIMARY KEY,
            file_name VARCHAR(255) NOT NULL,
            total_pages INT,
            total_chunks INT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """

        # 创建text_chunks表
        create_chunks_table = """
        CREATE TABLE IF NOT EXISTS text_chunks (
            chunk_id VARCHAR(255) PRIMARY KEY,
            doc_id VARCHAR(255) REFERENCES documents(doc_id),
            chunk_index INT,
            text TEXT NOT NULL,
            page_number INT,
            source VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """

        # 创建索引
        create_indexes = """
        CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON text_chunks(doc_id);
        CREATE INDEX IF NOT EXISTS idx_documents_file_name ON documents(file_name);
        """

        try:
            self.cursor.execute(create_documents_table)
            self.cursor.execute(create_chunks_table)
            self.cursor.execute(create_indexes)
            self.connection.commit()
            logger.info("表结构创建成功")
        except Exception as e:
            logger.error(f"创建表结构失败: {e}")
            self.connection.rollback()
            raise

    def get_ocr_files(self) -> List[Path]:
        """获取所有OCR结果文件"""
        ocr_dir = Path(OCR_OUTPUT_DIR)

        ocr_files = []
        for file in ocr_dir.glob("*_ocr.json"):
            if "chunk" not in file.name:
                ocr_files.append(file)

        logger.info(f"找到 {len(ocr_files)} 个OCR文件")
        return ocr_files

    def chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
        """将文本分块"""
        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]

            if start > 0:
                chunk = chunk[overlap:]

            chunks.append(chunk.strip())
            start = end - overlap if end < len(text) else len(text)

        return chunks

    def process_ocr_file(self, ocr_file: Path):
        """处理单个OCR文件"""
        logger.info(f"处理文件: {ocr_file.name}")

        with open(ocr_file, 'r', encoding='utf-8') as f:
            content = f.read()

        json_start = content.find('{')
        if json_start == -1:
            logger.error(f"文件中没有JSON内容: {ocr_file.name}")
            return

        json_content = content[json_start:]

        try:
            ocr_data = json.loads(json_content)
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {ocr_file.name}, 错误: {e}")
            return

        doc_id = ocr_data.get("document_id", ocr_file.stem)
        file_name = ocr_data.get("file_name", ocr_file.name)
        total_pages = len(ocr_data.get("pages", []))

        # 提取所有文本
        all_text = []
        for page_idx, page in enumerate(ocr_data.get("pages", [])):
            for block in page.get("text_blocks", []):
                text = block.get("text", "").strip()
                if text:
                    all_text.append((page_idx + 1, text))  # (页码, 文本)

        # 合并文本并分块
        full_text = " ".join([text for _, text in all_text])
        chunks = self.chunk_text(full_text)
        total_chunks = len(chunks)

        # 插入文档信息
        try:
            insert_document = """
            INSERT INTO documents (doc_id, file_name, total_pages, total_chunks)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (doc_id) DO UPDATE
            SET file_name = EXCLUDED.file_name,
                total_pages = EXCLUDED.total_pages,
                total_chunks = EXCLUDED.total_chunks
            """

            self.cursor.execute(insert_document, (doc_id, file_name, total_pages, total_chunks))

            # 准备文本块数据
            chunk_data = []
            for i, chunk in enumerate(chunks):
                chunk_id = f"{doc_id}_chunk_{i}"
                # 简单的页码映射（实际项目中可能需要更精确的映射）
                page_number = min(i // 10 + 1, total_pages) if total_pages > 0 else None
                
                chunk_data.append((
                    chunk_id,
                    doc_id,
                    i,
                    chunk,
                    page_number,
                    "ocr"
                ))

            # 批量插入文本块
            insert_chunk = """
            INSERT INTO text_chunks (chunk_id, doc_id, chunk_index, text, page_number, source)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (chunk_id) DO UPDATE
            SET text = EXCLUDED.text,
                page_number = EXCLUDED.page_number
            """

            execute_batch(self.cursor, insert_chunk, chunk_data)
            self.connection.commit()

            logger.info(f"  插入 {total_chunks} 个文本块")

        except Exception as e:
            logger.error(f"插入数据失败: {e}")
            self.connection.rollback()

    def run(self, max_files: int = None):
        """运行导入"""
        self.initialize()

        ocr_files = self.get_ocr_files()

        if max_files:
            ocr_files = ocr_files[:max_files]

        total_files = len(ocr_files)
        processed_files = 0

        for ocr_file in ocr_files:
            try:
                self.process_ocr_file(ocr_file)
                processed_files += 1
                logger.info(f"进度: {processed_files}/{total_files}")
            except Exception as e:
                logger.error(f"处理文件失败 {ocr_file.name}: {e}")

        logger.info("=" * 60)
        logger.info(f"导入完成！")
        logger.info(f"处理文件数: {processed_files}")
        logger.info(f"总文件数: {total_files}")
        logger.info("=" * 60)

        # 关闭连接
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()

        return processed_files

def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="OCR数据PostgreSQL导入")
    parser.add_argument("--max-files", type=int, default=None, help="最大处理文件数")

    args = parser.parse_args()

    importer = OCRPostgresImporter()
    importer.run(max_files=args.max_files)

if __name__ == "__main__":
    main()
