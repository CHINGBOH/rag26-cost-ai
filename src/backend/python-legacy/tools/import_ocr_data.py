#!/usr/bin/env python3
"""
OCR数据导入工具
将现有的OCR结果导入到RAG系统的四库中
"""

import os
import json
import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

# 配置
OCR_OUTPUT_DIR = "/home/l/rag-dashboard/data/ocr_outputs"
PROCESSED_LOG = "/home/l/rag-dashboard/data/ocr_outputs/processed_documents.log"

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class OCRDataImporter:
    """OCR数据导入器"""
    
    def __init__(self):
        self.four_db_service = None
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
    
    def get_ocr_files(self) -> List[Path]:
        """获取所有OCR结果文件"""
        ocr_dir = Path(OCR_OUTPUT_DIR)
        
        # 过滤掉处理日志和合并文件
        ocr_files = []
        for file in ocr_dir.glob("*.json"):
            if file.name not in ["processing_summary.json", "processed_documents.log"]:
                # 跳过chunk文件，只处理merged或单文件
                if "chunk" not in file.name or "merged" in file.name:
                    ocr_files.append(file)
        
        logger.info(f"找到 {len(ocr_files)} 个OCR结果文件")
        return ocr_files
    
    async def initialize(self):
        """初始化服务"""
        logger.info("初始化OCR数据导入器...")
        
        import sys
        import os
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
        from services.four_database_service import get_four_db_service
        self.four_db_service = await get_four_db_service()
        
        logger.info("✓ OCR数据导入器初始化完成")
    
    async def import_single_file(self, ocr_file: Path) -> Dict[str, Any]:
        """导入单个OCR文件"""
        file_name = ocr_file.name
        
        # 检查是否已处理
        if file_name in self.processed_files:
            logger.info(f"跳过已处理文件: {file_name}")
            return {"status": "skipped", "file_name": file_name}
        
        try:
            # 读取OCR结果
            with open(ocr_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # 找到JSON数据的开始位置（跳过前面的非JSON内容）
            json_start = content.find('{')
            if json_start == -1:
                raise ValueError("No JSON content found in file")
            
            # 解析JSON部分
            json_content = content[json_start:]
            ocr_result = json.loads(json_content)
            
            logger.info(f"开始处理: {file_name}")
            
            # 构建文件路径
            file_path = str(ocr_file)
            
            # 处理文档并存储到四库
            result = await self.four_db_service.process_document(
                file_path=file_path,
                file_name=file_name,
                ocr_result=ocr_result
            )
            
            # 保存处理记录
            self.save_processed_log(file_name)
            
            logger.info(f"✓ 成功处理: {file_name}")
            logger.info(f"  - 总页数: {result.total_chunks}")
            logger.info(f"  - 向量化块数: {result.embedded_chunks}")
            logger.info(f"  - 提取表格数: {result.tables_extracted}")
            logger.info(f"  - 提取实体数: {result.entities_extracted}")
            logger.info(f"  - 知识图谱节点: {result.knowledge_graph_nodes}")
            logger.info(f"  - 处理时间: {result.processing_time:.2f}秒")
            
            return {
                "status": "success",
                "file_name": file_name,
                "result": {
                    "document_id": result.document_id,
                    "total_chunks": result.total_chunks,
                    "embedded_chunks": result.embedded_chunks,
                    "tables_extracted": result.tables_extracted,
                    "entities_extracted": result.entities_extracted,
                    "knowledge_graph_nodes": result.knowledge_graph_nodes,
                    "processing_time": result.processing_time
                }
            }
            
        except Exception as e:
            logger.error(f"✗ 处理失败: {file_name}, 错误: {e}")
            return {
                "status": "failed",
                "file_name": file_name,
                "error": str(e)
            }
    
    async def import_all_files(self, batch_size: int = 5):
        """批量导入所有OCR文件"""
        logger.info("开始批量导入OCR数据...")
        
        # 获取所有OCR文件
        ocr_files = self.get_ocr_files()
        
        if not ocr_files:
            logger.warning("没有找到OCR结果文件")
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
            
            # 并发处理批次
            batch_results = await asyncio.gather(
                *[self.import_single_file(file) for file in batch],
                return_exceptions=True
            )
            
            # 统计结果
            for result in batch_results:
                if isinstance(result, Exception):
                    logger.error(f"处理异常: {result}")
                    failed_files += 1
                else:
                    results.append(result)
                    if result["status"] == "success":
                        success_files += 1
                    elif result["status"] == "skipped":
                        skipped_files += 1
                    else:
                        failed_files += 1
            
            # 短暂休息
            await asyncio.sleep(1)
        
        # 输出统计
        logger.info("=" * 60)
        logger.info("批量导入完成！")
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
    
    async def get_import_statistics(self) -> Dict[str, Any]:
        """获取导入统计信息"""
        try:
            stats = await self.four_db_service.get_system_statistics()
            
            # 添加OCR相关统计
            ocr_files = self.get_ocr_files()
            processed_count = len([f for f in ocr_files if f.name in self.processed_files])
            
            stats["ocr_import"] = {
                "total_ocr_files": len(ocr_files),
                "processed_files": processed_count,
                "pending_files": len(ocr_files) - processed_count,
                "progress_percentage": round(processed_count / len(ocr_files) * 100, 2) if ocr_files else 0
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {}

async def main():
    """主函数"""
    import sys
    
    # 创建导入器
    importer = OCRDataImporter()
    
    # 初始化
    await importer.initialize()
    
    # 检查命令行参数
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "stats":
            # 显示统计信息
            stats = await importer.get_import_statistics()
            print("\n" + "=" * 60)
            print("OCR数据导入统计")
            print("=" * 60)
            print(json.dumps(stats, indent=2, ensure_ascii=False))
            print("=" * 60)
            
        elif command == "import":
            # 导入所有文件
            batch_size = int(sys.argv[2]) if len(sys.argv) > 2 else 5
            await importer.import_all_files(batch_size=batch_size)
            
        elif command == "test":
            # 测试导入单个文件
            ocr_files = importer.get_ocr_files()
            if ocr_files:
                result = await importer.import_single_file(ocr_files[0])
                print("\n测试结果:")
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print("没有找到OCR文件")
                
        else:
            print("未知命令。可用命令: stats, import, test")
    else:
        # 默认：显示统计信息
        stats = await importer.get_import_statistics()
        print("\n" + "=" * 60)
        print("OCR数据导入统计")
        print("=" * 60)
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        print("=" * 60)
        print("\n使用方法:")
        print("  python import_ocr_data.py stats     - 显示统计信息")
        print("  python import_ocr_data.py import   - 导入所有OCR文件")
        print("  python import_ocr_data.py test      - 测试导入单个文件")
        print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())