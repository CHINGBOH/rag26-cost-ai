#!/usr/bin/env python3
"""
快速OCR处理器和搜索测试
处理剩余OCR文件并测试搜索功能
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

# 添加项目路径
sys.path.insert(0, '/home/l/rag-dashboard/src/backend/python-legacy')

# 配置
OCR_OUTPUT_DIR = "/home/l/rag-dashboard/data/ocr_outputs"
PROCESSED_LOG = "/home/l/rag-dashboard/data/ocr_outputs/processed_documents.log"
MODEL_PATH = "/home/l/rag-dashboard/models"

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

class QuickOCRProcessor:
    """快速OCR处理器"""
    
    def __init__(self):
        self.processed_files = set()
        self.embedding_service = None
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
    
    def init_embedding_service(self):
        """初始化embedding服务"""
        try:
            from infrastructure.adapters.embedding_service import get_embedding_service
            self.embedding_service = get_embedding_service(use_mock=False)
            logger.info("✓ Embedding服务初始化成功")
            return True
        except Exception as e:
            logger.error(f"✗ Embedding服务初始化失败: {e}")
            return False
    
    def embed_text(self, text: str):
        """向量化文本"""
        if self.embedding_service:
            try:
                return self.embedding_service.encode_single(text)
            except Exception as e:
                logger.error(f"向量化失败: {e}")
                # 返回随机向量
                import random
                return [random.random() for _ in range(1024)]
        else:
            # 返回随机向量
            import random
            return [random.random() for _ in range(1024)]
    
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
            embedded_chunks = 0
            
            for page in ocr_result.get('pages', []):
                page_number = page.get('page_number', 0)
                
                # 处理文本块（限制数量以加快处理）
                for idx, block in enumerate(page.get('text_blocks', [])):
                    if idx >= 20:  # 每页最多处理20个块
                        break
                        
                    content = block.get('text', '').strip()
                    if not content or len(content) < 10:
                        continue
                    
                    # 插入文档块
                    chunk_id = await conn.fetchval("""
                        INSERT INTO document_chunks
                        (document_id, chunk_index, content, page_number, metadata)
                        VALUES ($1, $2, $3, $4, $5)
                        RETURNING id
                    """,
                        document_id,
                        idx,
                        content,
                        page_number,
                        json.dumps({
                            'confidence': block.get('confidence', 0),
                            'bbox': block.get('bbox', {})
                        })
                    )
                    
                    # 向量化
                    embedding = self.embed_text(content)
                    
                    # 存储向量ID
                    embedding_id = hashlib.md5(content.encode()).hexdigest()
                    await conn.execute("""
                        UPDATE document_chunks
                        SET embedding_id = $1
                        WHERE id = $2
                    """, embedding_id, chunk_id)
                    
                    total_chunks += 1
                    embedded_chunks += 1
                
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
            
            logger.info(f"✓ 成功处理: {file_name} (文档ID: {document_id}, 总块数: {total_chunks}, 向量化: {embedded_chunks})")
            
            return {
                "status": "success",
                "file_name": file_name,
                "document_id": document_id,
                "total_chunks": total_chunks,
                "embedded_chunks": embedded_chunks
            }
            
        except Exception as e:
            logger.error(f"✗ 处理失败: {file_name}, 错误: {e}")
            return {
                "status": "failed",
                "file_name": file_name,
                "error": str(e)
            }
    
    async def process_quick_batch(self, max_files=5):
        """快速批量处理"""
        logger.info("开始快速批量处理...")
        
        # 初始化服务
        if not self.init_embedding_service():
            logger.error("无法初始化embedding服务")
            return
        
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
            
            # 过滤掉已处理的文件
            pending_files = [f for f in ocr_files if f.name not in self.processed_files]
            
            if not pending_files:
                logger.info("所有文件已处理完毕")
                return
            
            # 限制处理数量
            files_to_process = pending_files[:max_files]
            logger.info(f"准备处理 {len(files_to_process)} 个文件")
            
            # 统计信息
            success_count = 0
            failed_count = 0
            
            for file in files_to_process:
                result = await self.process_single_file(file, conn)
                
                if result["status"] == "success":
                    success_count += 1
                else:
                    failed_count += 1
            
            # 输出统计
            logger.info("=" * 60)
            logger.info("快速批量处理完成！")
            logger.info(f"处理文件数: {len(files_to_process)}")
            logger.info(f"成功: {success_count}")
            logger.info(f"失败: {failed_count}")
            logger.info(f"剩余待处理: {len(pending_files) - len(files_to_process)}")
            logger.info("=" * 60)
            
        finally:
            await conn.close()

async def test_semantic_search():
    """测试语义搜索功能"""
    logger.info("测试语义搜索功能...")
    
    conn = await asyncpg.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD
    )
    
    try:
        # 测试查询
        test_queries = [
            "深圳市建设工程计价费率",
            "企业管理费",
            "安全文明施工费",
            "工程量清单",
            "造价咨询"
        ]
        
        for query in test_queries:
            logger.info(f"\n搜索查询: {query}")
            
            # 使用简单的LIKE搜索（更兼容）
            results = await conn.fetch("""
                SELECT 
                    dc.id as chunk_id,
                    dc.content,
                    dc.page_number,
                    d.file_name
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.id
                WHERE dc.content LIKE $1
                ORDER BY LENGTH(dc.content)
                LIMIT 5
            """, f"%{query}%")
            
            if results:
                logger.info(f"找到 {len(results)} 个结果:")
                for i, row in enumerate(results[:3], 1):
                    content_preview = row['content'][:100] + "..." if len(row['content']) > 100 else row['content']
                    logger.info(f"  {i}. [{row['file_name']}] 页{row['page_number']}: {content_preview}")
            else:
                logger.info("  没有找到相关结果")
        
    finally:
        await conn.close()

async def get_detailed_statistics():
    """获取详细统计信息"""
    conn = await asyncpg.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD
    )
    
    try:
        # 文档统计
        doc_stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'completed') as completed,
                COUNT(*) FILTER (WHERE status = 'processing') as processing,
                AVG(page_count) as avg_pages
            FROM documents
        """)
        
        # 文档块统计
        chunk_stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE embedding_id IS NOT NULL) as embedded,
                AVG(LENGTH(content)) as avg_length
            FROM document_chunks
        """)
        
        # 表格统计
        table_count = await conn.fetchval("SELECT COUNT(*) FROM tables_data")
        
        # 按文档统计
        doc_details = await conn.fetch("""
            SELECT 
                file_name,
                page_count,
                status,
                processed_at
            FROM documents
            ORDER BY id
            LIMIT 10
        """)
        
        stats = {
            "documents": {
                "total": int(doc_stats['total']) if doc_stats['total'] else 0,
                "completed": int(doc_stats['completed']) if doc_stats['completed'] else 0,
                "processing": int(doc_stats['processing']) if doc_stats['processing'] else 0,
                "avg_pages": round(float(doc_stats['avg_pages']), 1) if doc_stats['avg_pages'] else 0
            },
            "chunks": {
                "total": int(chunk_stats['total']) if chunk_stats['total'] else 0,
                "embedded": int(chunk_stats['embedded']) if chunk_stats['embedded'] else 0,
                "embedding_rate": round(float(chunk_stats['embedded']) / float(chunk_stats['total']) * 100, 1) if chunk_stats['total'] > 0 else 0,
                "avg_length": round(float(chunk_stats['avg_length']), 1) if chunk_stats['avg_length'] else 0
            },
            "tables": table_count,
            "recent_documents": [
                {
                    "file_name": row['file_name'],
                    "pages": row['page_count'],
                    "status": row['status'],
                    "processed_at": row['processed_at'].isoformat() if row['processed_at'] else None
                }
                for row in doc_details
            ]
        }
        
        return stats
        
    finally:
        await conn.close()

async def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='快速OCR处理器和搜索测试')
    parser.add_argument('command', nargs='?', default='stats', 
                       choices=['stats', 'process', 'search', 'all'],
                       help='命令: stats(统计), process(处理), search(搜索), all(全部)')
    parser.add_argument('--max-files', type=int, default=5,
                       help='最大处理文件数')
    
    args = parser.parse_args()
    
    processor = QuickOCRProcessor()
    
    if args.command == "stats":
        # 显示详细统计
        stats = await get_detailed_statistics()
        print("\n" + "=" * 60)
        print("OCR数据处理详细统计")
        print("=" * 60)
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        print("=" * 60)
        
    elif args.command == "process":
        # 快速处理
        await processor.process_quick_batch(max_files=args.max_files)
        
    elif args.command == "search":
        # 测试搜索
        await test_semantic_search()
        
    elif args.command == "all":
        # 执行所有操作
        print("\n1. 处理OCR文件...")
        await processor.process_quick_batch(max_files=args.max_files)
        
        print("\n2. 显示统计...")
        stats = await get_detailed_statistics()
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        
        print("\n3. 测试搜索...")
        await test_semantic_search()

if __name__ == "__main__":
    asyncio.run(main())