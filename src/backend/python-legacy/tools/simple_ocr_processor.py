#!/usr/bin/env python3
"""
简化的OCR数据处理工具
直接处理OCR数据并存储到数据库，不依赖完整的API服务
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime
import asyncpg
import hashlib

# 配置
OCR_OUTPUT_DIR = "/home/l/rag-dashboard/data/ocr_outputs"
PROCESSED_LOG = "/home/l/rag-dashboard/data/ocr_outputs/processed_documents.log"

# 数据库配置
POSTGRES_HOST = "localhost"
POSTGRES_PORT = 5432
POSTGRES_DB = "rag_db"
POSTGRES_USER = "rag_user"
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "rag_password")

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SimpleOCRProcessor:
    """简化的OCR处理器"""
    
    def __init__(self):
        self.processed_files = set()
        self.load_processed_log()
    
    def load_processed_log(self):
        """加载已处理文件记录"""
        if os.path.exists(PROCESSED_LOG):
            with open(PROCESSED_LOG, 'r') as f:
                self.processed_files = set(line.strip() for line in f)
            logger.info(f"已加载 {len(self.processed_files)} 个已处理文件记录")
    
    def save_processed_log(self, file_name: str):
        """保存已处理文件记录"""
        with open(PROCESSED_LOG, 'a') as f:
            f.write(f"{file_name}\n")
        self.processed_files.add(file_name)
    
    def get_ocr_files(self):
        """获取所有OCR文件"""
        ocr_dir = Path(OCR_OUTPUT_DIR)
        ocr_files = []
        
        for file in ocr_dir.glob("*.json"):
            if file.name not in ["processing_summary.json", "processed_documents.log"]:
                # 只处理merged文件或单文件
                if "merged" in file.name or ("chunk" not in file.name):
                    ocr_files.append(file)
        
        logger.info(f"找到 {len(ocr_files)} 个OCR文件")
        return ocr_files
    
    async def process_single_file(self, ocr_file, conn):
        """处理单个OCR文件"""
        file_name = ocr_file.name
        
        # 检查是否已处理
        if file_name in self.processed_files:
            logger.info(f"跳过已处理文件: {file_name}")
            return {"status": "skipped", "file_name": file_name}
        
        try:
            # 读取OCR结果
            with open(ocr_file, 'r', encoding='utf-8') as f:
                ocr_result = json.load(f)
            
            logger.info(f"开始处理: {file_name}")
            
            # 插入文档记录
            document_id = await conn.fetchval("""
                INSERT INTO documents
                (file_name, file_path, file_size, page_count, status, ocr_completed, ocr_result_path)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (file_name) DO UPDATE SET
                    status = $5, ocr_completed = $6, ocr_result_path = $7
                RETURNING id
            """,
                file_name,
                str(ocr_file),
                ocr_file.stat().st_size,
                ocr_result.get('total_pages', 0),
                'processing',
                True,
                str(ocr_file)
            )
            
            # 处理文档块
            total_chunks = 0
            for page in ocr_result.get('pages', []):
                page_number = page.get('page_number', 0)
                
                # 处理文本块
                for block in page.get('text_blocks', []):
                    content = block.get('text', '').strip()
                    if not content:
                        continue
                    
                    # 插入文档块
                    await conn.execute("""
                        INSERT INTO document_chunks
                        (document_id, chunk_index, content, page_number, metadata)
                        VALUES ($1, $2, $3, $4, $5)
                    """,
                        document_id,
                        block.get('bbox', {}).get('x', 0),
                        content,
                        page_number,
                        json.dumps({
                            'confidence': block.get('confidence', 0),
                            'bbox': block.get('bbox', {})
                        })
                    )
                    total_chunks += 1
                
                # 处理表格
                for table in page.get('tables', []):
                    html_content = table.get('html', '')
                    if html_content:
                        await conn.execute("""
                            INSERT INTO tables_data
                            (document_id, table_name, html_content, markdown_content, page_number, metadata)
                            VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                            document_id,
                            f"table_page_{page_number}",
                            html_content,
                            table.get('markdown', ''),
                            page_number,
                            json.dumps({
                                'row_count': table.get('row_count', 0),
                                'col_count': table.get('col_count', 0)
                            })
                        )
            
            # 更新文档状态
            await conn.execute("""
                UPDATE documents
                SET status = 'completed', processed_at = $1
                WHERE id = $2
            """, datetime.now(), document_id)
            
            # 保存处理记录
            self.save_processed_log(file_name)
            
            logger.info(f"✓ 成功处理: {file_name} (文档ID: {document_id}, 块数: {total_chunks})")
            
            return {
                "status": "success",
                "file_name": file_name,
                "document_id": document_id,
                "total_chunks": total_chunks
            }
            
        except Exception as e:
            logger.error(f"✗ 处理失败: {file_name}, 错误: {e}")
            return {
                "status": "failed",
                "file_name": file_name,
                "error": str(e)
            }
    
    async def process_all_files(self, batch_size=5):
        """批量处理所有OCR文件"""
        logger.info("开始批量处理OCR文件...")
        
        # 连接数据库
        conn = await asyncpg.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            database=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD
        )
        
        try:
            # 获取所有OCR文件
            ocr_files = self.get_ocr_files()
            
            if not ocr_files:
                logger.warning("没有找到OCR文件")
                return
            
            # 统计信息
            total_files = len(ocr_files)
            skipped_files = 0
            success_files = 0
            failed_files = 0
            
            results = []
            
            # 批量处理
            for i in range(0, total_files, batch_size):
                batch = ocr_files[i:i + batch_size]
                logger.info(f"处理批次 {i//batch_size + 1}/{(total_files + batch_size - 1)//batch_size}")
                
                for file in batch:
                    result = await self.process_single_file(file, conn)
                    results.append(result)
                    
                    if result["status"] == "success":
                        success_files += 1
                    elif result["status"] == "skipped":
                        skipped_files += 1
                    else:
                        failed_files += 1
            
            # 输出统计
            logger.info("=" * 60)
            logger.info("批量处理完成！")
            logger.info(f"总文件数: {total_files}")
            logger.info(f"成功处理: {success_files}")
            logger.info(f"跳过文件: {skipped_files}")
            logger.info(f"失败文件: {failed_files}")
            logger.info("=" * 60)
            
            return {
                "total_files": total_files,
                "success_files": success_files,
                "skipped_files": skipped_files,
                "failed_files": failed_files,
                "results": results
            }
            
        finally:
            await conn.close()

async def get_statistics():
    """获取统计信息"""
    conn = await asyncpg.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD
    )
    
    try:
        doc_count = await conn.fetchval("SELECT COUNT(*) FROM documents")
        chunk_count = await conn.fetchval("SELECT COUNT(*) FROM document_chunks")
        table_count = await conn.fetchval("SELECT COUNT(*) FROM tables_data")
        
        processed_docs = await conn.fetchval("SELECT COUNT(*) FROM documents WHERE status = 'completed'")
        
        stats = {
            "documents": {
                "total": doc_count,
                "processed": processed_docs,
                "processing": doc_count - processed_docs
            },
            "chunks": chunk_count,
            "tables": table_count
        }
        
        return stats
        
    finally:
        await conn.close()

async def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='OCR数据处理工具')
    parser.add_argument('command', nargs='?', default='stats', 
                       choices=['stats', 'import', 'test'],
                       help='命令: stats(统计), import(导入), test(测试)')
    parser.add_argument('--batch', type=int, default=5,
                       help='批量处理大小')
    
    args = parser.parse_args()
    
    processor = SimpleOCRProcessor()
    
    if args.command == "stats":
        # 显示统计
        stats = await get_statistics()
        print("\n" + "=" * 60)
        print("OCR数据统计")
        print("=" * 60)
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        print("=" * 60)
        
    elif args.command == "import":
        # 导入所有文件
        await processor.process_all_files(batch_size=args.batch)
        
    elif args.command == "test":
        # 测试单个文件
        ocr_files = processor.get_ocr_files()
        if ocr_files:
            conn = await asyncpg.connect(
                host=POSTGRES_HOST,
                port=POSTGRES_PORT,
                database=POSTGRES_DB,
                user=POSTGRES_USER,
                password=POSTGRES_PASSWORD
            )
            
            try:
                result = await processor.process_single_file(ocr_files[0], conn)
                print("\n测试结果:")
                print(json.dumps(result, indent=2, ensure_ascii=False))
            finally:
                await conn.close()
        else:
            print("没有找到OCR文件")

if __name__ == "__main__":
    asyncio.run(main())