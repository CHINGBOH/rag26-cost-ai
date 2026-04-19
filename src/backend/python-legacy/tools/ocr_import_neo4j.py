#!/usr/bin/env python3
"""
OCR数据Neo4j知识图谱导入脚本（UNWIND批量优化版）
将OCR数据批量导入到Neo4j知识图谱
"""

import os
import sys
import json
import logging
import re
from pathlib import Path
from typing import List, Set
from neo4j import GraphDatabase

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

OCR_OUTPUT_DIR = "/home/l/rag-dashboard/data/ocr_outputs"

NEO4J_CONFIG = {
    'uri': 'bolt://localhost:7687',
    'user': 'neo4j',
    'password': 'password'
}

BATCH_SIZE = 500

class OCRNeo4jImporter:
    """OCR数据Neo4j导入器（批量优化版）"""

    def __init__(self):
        self.driver = None

    def initialize(self):
        """初始化Neo4j连接"""
        logger.info("初始化Neo4j连接...")

        try:
            self.driver = GraphDatabase.driver(
                NEO4J_CONFIG['uri'],
                auth=(NEO4J_CONFIG['user'], NEO4J_CONFIG['password'])
            )
            with self.driver.session() as session:
                session.run("RETURN 1")
                logger.info("Neo4j连接成功")

                self._create_constraints(session)
        except Exception as e:
            logger.error(f"Neo4j连接失败: {e}")
            raise

    def _create_constraints(self, session):
        """创建索引和约束"""
        logger.info("创建索引...")
        constraints = [
            "CREATE CONSTRAINT FOR (d:Document) REQUIRE d.doc_id IS UNIQUE",
            "CREATE CONSTRAINT FOR (c:TextChunk) REQUIRE c.chunk_id IS UNIQUE",
            "CREATE CONSTRAINT FOR (e:Entity) REQUIRE e.name IS UNIQUE",
        ]
        indexes = [
            "CREATE INDEX FOR (c:TextChunk) ON (c.page_number)",
            "CREATE INDEX FOR (e:Entity) ON (e.type)",
        ]
        for c in constraints:
            try:
                session.run(c)
            except Exception: pass
        for i in indexes:
            try:
                session.run(i)
            except Exception: pass

    def get_ocr_files(self) -> List[Path]:
        """获取所有OCR结果文件"""
        ocr_dir = Path(OCR_OUTPUT_DIR)
        ocr_files = [f for f in ocr_dir.glob("*_ocr.json") if "chunk" not in f.name]
        logger.info(f"找到 {len(ocr_files)} 个OCR文件")
        return ocr_files

    def extract_entities(self, text: str) -> Set[str]:
        """从文本中提取实体"""
        entities = set()
        entities.update(re.findall(r'\d+\.?\d*', text))
        entities.update(re.findall(r'[\u4e00-\u9fa5]+公司|[\u4e00-\u9fa5]+局|[\u4e00-\u9fa5]+部|[\u4e00-\u9fa5]+委员会', text))
        entities.update(re.findall(r'[\u4e00-\u9fa5]+省|[\u4e00-\u9fa5]+市|[\u4e00-\u9fa5]+区|[\u4e00-\u9fa5]+县', text))
        return {e for e in entities if len(e) <= 50 and len(e) >= 2}

    def process_ocr_file(self, ocr_file: Path):
        """处理单个OCR文件（批量优化）"""
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

        chunks = []
        entities = set()

        for page_idx, page in enumerate(ocr_data.get("pages", [])):
            page_number = page_idx + 1
            for block_idx, block in enumerate(page.get("text_blocks", [])):
                text = block.get("text", "").strip()
                if not text:
                    continue

                chunk_id = f"{doc_id}_page_{page_number}_block_{block_idx}"
                chunks.append({
                    'chunk_id': chunk_id,
                    'text': text,
                    'page_number': page_number,
                    'block_index': block_idx
                })

                entities.update(self.extract_entities(text))

        with self.driver.session() as session:
            session.run("""
                MERGE (d:Document {doc_id: $doc_id})
                SET d.file_name = $file_name, d.total_pages = $total_pages
            """, doc_id=doc_id, file_name=file_name, total_pages=total_pages)

            for i in range(0, len(chunks), BATCH_SIZE):
                batch = chunks[i:i+BATCH_SIZE]
                session.run("""
                    UNWIND $chunks AS chunk
                    MERGE (c:TextChunk {chunk_id: chunk.chunk_id})
                    SET c.text = chunk.text, c.page_number = chunk.page_number,
                        c.block_index = chunk.block_index, c.source = 'ocr'
                    WITH chunk
                    MATCH (d:Document {doc_id: $doc_id})
                    MERGE (d)-[:CONTAINS]->(c)
                """, chunks=batch, doc_id=doc_id)

            entity_list = [{'name': e, 'type': 'general'} for e in entities]
            for i in range(0, len(entity_list), BATCH_SIZE):
                batch = entity_list[i:i+BATCH_SIZE]
                session.run("""
                    UNWIND $entities AS entity
                    MERGE (e:Entity {name: entity.name})
                    SET e.type = entity.type
                """, entities=batch)

            entity_chunk_rels = []
            for chunk in chunks:
                chunk_ents = self.extract_entities(chunk['text'])
                for ent in chunk_ents:
                    entity_chunk_rels.append({
                        'chunk_id': chunk['chunk_id'],
                        'entity_name': ent
                    })

            for i in range(0, len(entity_chunk_rels), BATCH_SIZE):
                batch = entity_chunk_rels[i:i+BATCH_SIZE]
                session.run("""
                    UNWIND $rels AS rel
                    MATCH (c:TextChunk {chunk_id: rel.chunk_id})
                    MATCH (e:Entity {name: rel.entity_name})
                    MERGE (c)-[:MENTIONS]->(e)
                """, rels=batch)

        logger.info(f"  完成: {len(chunks)} chunks, {len(entities)} entities")

    def run(self, max_files: int = None):
        """运行导入"""
        self.initialize()
        ocr_files = self.get_ocr_files()
        if max_files:
            ocr_files = ocr_files[:max_files]

        total_files = len(ocr_files)
        processed = 0

        for ocr_file in ocr_files:
            try:
                self.process_ocr_file(ocr_file)
                processed += 1
                logger.info(f"进度: {processed}/{total_files}")
            except Exception as e:
                logger.error(f"处理文件失败 {ocr_file.name}: {e}")

        logger.info(f"导入完成! 处理: {processed}/{total_files}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-files", type=int, default=None)
    args = parser.parse_args()

    importer = OCRNeo4jImporter()
    importer.run(max_files=args.max_files)
