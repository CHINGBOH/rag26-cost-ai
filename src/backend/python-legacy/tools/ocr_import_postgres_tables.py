#!/usr/bin/env python3
"""
OCR数据PostgreSQL结构化表格导入脚本
将OCR表格数据导入到PostgreSQL作为结构化数据
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

import psycopg2
from psycopg2.extras import execute_batch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

OCR_OUTPUT_DIR = "/home/l/rag-dashboard/data/ocr_outputs"

POSTGRES_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'rag_dashboard',
    'user': 'rag_user',
    'password': os.environ.get('POSTGRES_PASSWORD', 'rag_password')
}

class OCRPostgresTableImporter:
    """OCR表格数据PostgreSQL导入器"""

    def __init__(self):
        self.connection = None
        self.cursor = None

    def initialize(self):
        """初始化数据库连接"""
        logger.info("初始化PostgreSQL连接...")

        try:
            self.connection = psycopg2.connect(**POSTGRES_CONFIG)
            self.cursor = self.connection.cursor()
            logger.info("PostgreSQL连接成功")
        except Exception as e:
            logger.error(f"PostgreSQL连接失败: {e}")
            raise

    def _create_tables(self):
        """创建表格数据结构"""
        logger.info("创建表格结构...")

        # 创建documents表（文档元数据）
        create_documents_table = """
        CREATE TABLE IF NOT EXISTS ocr_documents (
            doc_id VARCHAR(255) PRIMARY KEY,
            file_name VARCHAR(255) NOT NULL,
            total_pages INT,
            total_tables INT,
            total_cells INT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """

        # 创建tables表（表格元数据）
        create_tables_table = """
        CREATE TABLE IF NOT EXISTS ocr_tables (
            table_id VARCHAR(255) PRIMARY KEY,
            doc_id VARCHAR(255) REFERENCES ocr_documents(doc_id),
            page_number INT,
            table_index INT,
            num_rows INT,
            num_cols INT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """

        # 创建cells表（单元格数据 - 核心结构化数据）
        create_cells_table = """
        CREATE TABLE IF NOT EXISTS ocr_cells (
            cell_id VARCHAR(255) PRIMARY KEY,
            table_id VARCHAR(255) REFERENCES ocr_tables(table_id),
            doc_id VARCHAR(255) REFERENCES ocr_documents(doc_id),
            row_index INT,
            col_index INT,
            text TEXT NOT NULL,
            page_number INT,
            source_file VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """

        # 创建索引
        create_indexes = """
        CREATE INDEX IF NOT EXISTS idx_tables_doc_id ON ocr_tables(doc_id);
        CREATE INDEX IF NOT EXISTS idx_cells_doc_id ON ocr_cells(doc_id);
        CREATE INDEX IF NOT EXISTS idx_cells_table_id ON ocr_cells(table_id);
        CREATE INDEX IF NOT EXISTS idx_cells_row_col ON ocr_cells(table_id, row_index, col_index);
        CREATE INDEX IF NOT EXISTS idx_cells_text ON ocr_cells USING gin(to_tsvector('simple', text));
        """

        try:
            self.cursor.execute(create_documents_table)
            self.cursor.execute(create_tables_table)
            self.cursor.execute(create_cells_table)
            self.cursor.execute(create_indexes)
            self.connection.commit()
            logger.info("表格结构创建成功")
        except Exception as e:
            logger.error(f"创建表格结构失败: {e}")
            self.connection.rollback()
            raise

    def get_ocr_files(self) -> list:
        """获取所有OCR结果文件"""
        ocr_dir = Path(OCR_OUTPUT_DIR)

        ocr_files = []
        for file in ocr_dir.glob("*_ocr.json"):
            if "chunk" not in file.name:
                ocr_files.append(file)

        logger.info(f"找到 {len(ocr_files)} 个OCR文件")
        return ocr_files

    def process_ocr_file(self, ocr_file: Path):
        """处理单个OCR文件，提取表格数据"""
        logger.info(f"处理文件: {ocr_file.name}")

        with open(ocr_file, 'r', encoding='utf-8') as f:
            content = f.read()

        json_start = content.find('{')
        if json_start == -1:
            logger.error(f"文件中没有JSON内容: {ocr_file.name}")
            return 0

        json_content = content[json_start:]

        try:
            ocr_data = json.loads(json_content)
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {ocr_file.name}, 错误: {e}")
            return 0

        doc_id = ocr_data.get("document_id", ocr_file.stem)
        file_name = ocr_data.get("file_name", ocr_file.name)
        total_pages = len(ocr_data.get("pages", []))

        # 统计表格数量
        total_tables = 0
        total_cells = 0

        # 收集所有表格和单元格数据
        tables_data = []
        cells_data = []

        for page_idx, page in enumerate(ocr_data.get("pages", [])):
            page_number = page_idx + 1
            tables = page.get("tables", [])

            for table_idx, table in enumerate(tables):
                total_tables += 1
                table_id = f"{doc_id}_page_{page_number}_table_{table_idx}"

                # 获取表格行列数
                cells = table.get("cells", [])
                max_row = 0
                max_col = 0
                for cell in cells:
                    max_row = max(max_row, cell.get("row", 0) + 1)
                    max_col = max(max_col, cell.get("col", 0) + 1)

                # 存储表格元数据
                tables_data.append({
                    'table_id': table_id,
                    'doc_id': doc_id,
                    'page_number': page_number,
                    'table_index': table_idx,
                    'num_rows': max_row,
                    'num_cols': max_col
                })

                # 存储单元格数据
                for cell in cells:
                    total_cells += 1
                    cell_id = f"{table_id}_cell_{cell.get('row')}_{cell.get('col')}"
                    cells_data.append({
                        'cell_id': cell_id,
                        'table_id': table_id,
                        'doc_id': doc_id,
                        'row_index': cell.get('row', 0),
                        'col_index': cell.get('col', 0),
                        'text': cell.get('text', ''),
                        'page_number': page_number,
                        'source_file': ocr_file.name
                    })

        # 插入文档记录
        self.cursor.execute(
            """
            INSERT INTO ocr_documents (doc_id, file_name, total_pages, total_tables, total_cells)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (doc_id) DO UPDATE SET
                total_tables = EXCLUDED.total_tables,
                total_cells = EXCLUDED.total_cells
            """,
            (doc_id, file_name, total_pages, total_tables, total_cells)
        )

        # 批量插入表格数据
        if tables_data:
            self.cursor.executemany(
                """
                INSERT INTO ocr_tables (table_id, doc_id, page_number, table_index, num_rows, num_cols)
                VALUES (%(table_id)s, %(doc_id)s, %(page_number)s, %(table_index)s, %(num_rows)s, %(num_cols)s)
                ON CONFLICT (table_id) DO NOTHING
                """,
                tables_data
            )

        # 批量插入单元格数据
        if cells_data:
            self.cursor.executemany(
                """
                INSERT INTO ocr_cells (cell_id, table_id, doc_id, row_index, col_index, text, page_number, source_file)
                VALUES (%(cell_id)s, %(table_id)s, %(doc_id)s, %(row_index)s, %(col_index)s, %(text)s, %(page_number)s, %(source_file)s)
                ON CONFLICT (cell_id) DO NOTHING
                """,
                cells_data
            )

        self.connection.commit()
        logger.info(f"  文档ID: {doc_id}, 表格: {total_tables}, 单元格: {total_cells}")

        return total_cells

    def run(self, max_files: int = None):
        """运行导入"""
        self.initialize()
        self._create_tables()

        ocr_files = self.get_ocr_files()

        if max_files:
            ocr_files = ocr_files[:max_files]

        total_files = len(ocr_files)
        processed_files = 0
        total_cells = 0

        for ocr_file in ocr_files:
            try:
                cells = self.process_ocr_file(ocr_file)
                total_cells += cells
                processed_files += 1
                logger.info(f"进度: {processed_files}/{total_files}")
            except Exception as e:
                logger.error(f"处理文件失败 {ocr_file.name}: {e}")

        # 打印统计
        self.cursor.execute("SELECT COUNT(*) FROM ocr_documents")
        doc_count = self.cursor.fetchone()[0]

        self.cursor.execute("SELECT COUNT(*) FROM ocr_tables")
        table_count = self.cursor.fetchone()[0]

        self.cursor.execute("SELECT COUNT(*) FROM ocr_cells")
        cell_count = self.cursor.fetchone()[0]

        logger.info("=" * 60)
        logger.info(f"导入完成！")
        logger.info(f"处理文件数: {processed_files}")
        logger.info(f"总文件数: {total_files}")
        logger.info(f"文档数: {doc_count}")
        logger.info(f"表格数: {table_count}")
        logger.info(f"单元格数: {cell_count}")
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

    parser = argparse.ArgumentParser(description="OCR表格数据PostgreSQL导入")
    parser.add_argument("--max-files", type=int, default=None, help="最大处理文件数")

    args = parser.parse_args()

    importer = OCRPostgresTableImporter()
    importer.run(max_files=args.max_files)

if __name__ == "__main__":
    main()
