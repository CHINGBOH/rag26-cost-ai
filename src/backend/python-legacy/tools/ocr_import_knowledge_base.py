#!/usr/bin/env python3
"""
OCR数据知识库文档存储导入脚本
将OCR数据导入到知识库文档存储
"""

import os
import sys
import json
import logging
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

OCR_OUTPUT_DIR = os.environ.get("OCR_OUTPUT_DIR", "/home/l/rag-dashboard/data/ocr_outputs")
KNOWLEDGE_BASE_DIR = os.environ.get("KNOWLEDGE_BASE_DIR", "/home/l/rag-dashboard/data/knowledge_base")

class OCRKnowledgeBaseImporter:
    """OCR数据知识库导入器"""

    def __init__(self):
        self.knowledge_base_dir = Path(KNOWLEDGE_BASE_DIR)
        self.ensure_directories()

    def ensure_directories(self):
        """确保必要的目录存在"""
        # 创建知识库主目录
        self.knowledge_base_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建子目录
        (self.knowledge_base_dir / "documents").mkdir(parents=True, exist_ok=True)
        (self.knowledge_base_dir / "metadata").mkdir(parents=True, exist_ok=True)
        (self.knowledge_base_dir / "index").mkdir(parents=True, exist_ok=True)

    def get_ocr_files(self) -> List[Path]:
        """获取所有OCR结果文件"""
        ocr_dir = Path(OCR_OUTPUT_DIR)

        ocr_files = []
        for file in sorted(ocr_dir.rglob("*.json")):
            if file.name in {"processing_summary.json", "_scan_state.json"}:
                continue
            if "chunk" in file.name.lower():
                continue
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    ocr_data = json.load(f)
            except Exception:
                continue
            if isinstance(ocr_data.get("pages"), list):
                ocr_files.append(file)

        logger.info(f"找到 {len(ocr_files)} 个OCR文件")
        return ocr_files

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
        
        # 计算总文本块数
        total_chunks = 0
        for page in ocr_data.get("pages", []):
            total_chunks += len(page.get("text_blocks", []))

        # 生成文档目录
        doc_dir = self.knowledge_base_dir / "documents" / doc_id
        doc_dir.mkdir(parents=True, exist_ok=True)

        # 复制原始OCR文件
        ocr_dest = doc_dir / ocr_file.name
        shutil.copy2(ocr_file, ocr_dest)

        # 提取纯文本内容
        text_content = []
        for page_idx, page in enumerate(ocr_data.get("pages", [])):
            page_number = page_idx + 1
            for block in page.get("text_blocks", []):
                text = block.get("text", "").strip()
                if text:
                    text_content.append(text)

        # 保存纯文本
        text_dest = doc_dir / f"{doc_id}.txt"
        with open(text_dest, 'w', encoding='utf-8') as f:
            f.write('\n'.join(text_content))

        # 生成元数据
        metadata = {
            "doc_id": doc_id,
            "file_name": file_name,
            "original_file": ocr_file.name,
            "total_pages": total_pages,
            "total_chunks": total_chunks,
            "created_at": datetime.now().isoformat(),
            "source": "ocr",
            "text_length": sum(len(t) for t in text_content),
            "text_count": len(text_content)
        }

        # 保存元数据
        metadata_dest = self.knowledge_base_dir / "metadata" / f"{doc_id}.json"
        with open(metadata_dest, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        # 更新索引
        self.update_index(doc_id, metadata)

        logger.info(f"  处理完成，保存到: {doc_dir}")

    def update_index(self, doc_id: str, metadata: Dict[str, Any]):
        """更新知识库索引"""
        index_file = self.knowledge_base_dir / "index" / "document_index.json"

        # 读取现有索引
        if index_file.exists():
            with open(index_file, 'r', encoding='utf-8') as f:
                try:
                    index = json.load(f)
                except json.JSONDecodeError:
                    index = {}
        else:
            index = {}

        # 更新索引
        index[doc_id] = {
            "metadata": metadata,
            "last_updated": datetime.now().isoformat()
        }

        # 保存索引
        with open(index_file, 'w', encoding='utf-8') as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

    def run(self, max_files: int = None):
        """运行导入"""
        self.ensure_directories()

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

        # 生成统计信息
        self.generate_statistics()

        logger.info("=" * 60)
        logger.info(f"导入完成！")
        logger.info(f"处理文件数: {processed_files}")
        logger.info(f"总文件数: {total_files}")
        logger.info("=" * 60)

        return processed_files

    def generate_statistics(self):
        """生成知识库统计信息"""
        stats = {
            "total_documents": 0,
            "total_pages": 0,
            "total_chunks": 0,
            "total_text_length": 0,
            "last_updated": datetime.now().isoformat()
        }

        # 读取索引文件
        index_file = self.knowledge_base_dir / "index" / "document_index.json"
        if index_file.exists():
            with open(index_file, 'r', encoding='utf-8') as f:
                try:
                    index = json.load(f)
                    stats["total_documents"] = len(index)
                    
                    for doc_id, doc_info in index.items():
                        metadata = doc_info.get("metadata", {})
                        stats["total_pages"] += metadata.get("total_pages", 0)
                        stats["total_chunks"] += metadata.get("total_chunks", 0)
                        stats["total_text_length"] += metadata.get("text_length", 0)
                except json.JSONDecodeError:
                    pass

        # 保存统计信息
        stats_file = self.knowledge_base_dir / "index" / "statistics.json"
        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)

        logger.info(f"生成统计信息: {stats}")

def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="OCR数据知识库导入")
    parser.add_argument("--max-files", type=int, default=None, help="最大处理文件数")

    args = parser.parse_args()

    importer = OCRKnowledgeBaseImporter()
    importer.run(max_files=args.max_files)

if __name__ == "__main__":
    main()
