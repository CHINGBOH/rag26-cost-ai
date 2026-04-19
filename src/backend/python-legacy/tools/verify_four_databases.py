#!/usr/bin/env python3
"""
四库数据一致性验证脚本
验证PostgreSQL、Qdrant、Neo4j和知识库中的数据一致性
"""

import os
import sys
import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any

import psycopg2
from qdrant_client import QdrantClient
from neo4j import GraphDatabase

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

KNOWLEDGE_BASE_DIR = "/home/l/rag-dashboard/data/knowledge_base"

# 数据库配置
POSTGRES_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'rag_db',
    'user': 'rag_user',
    'password': 'rag_password'
}

QDRANT_CONFIG = {
    'host': 'localhost',
    'port': 6333
}

NEO4J_CONFIG = {
    'uri': 'bolt://localhost:7687',
    'auth': ('neo4j', 'password')
}

class DataConsistencyVerifier:
    """四库数据一致性验证器"""

    def __init__(self):
        self.verification_results = {}

    def verify_postgresql(self) -> Dict[str, Any]:
        """验证PostgreSQL数据"""
        logger.info("开始验证PostgreSQL数据...")
        results = {}

        try:
            conn = psycopg2.connect(**POSTGRES_CONFIG)
            cursor = conn.cursor()

            # 统计文档数量
            cursor.execute("SELECT COUNT(*) FROM documents")
            doc_count = cursor.fetchone()[0]
            results['document_count'] = doc_count

            # 统计文本块数量
            cursor.execute("SELECT COUNT(*) FROM text_chunks")
            chunk_count = cursor.fetchone()[0]
            results['chunk_count'] = chunk_count

            # 统计每个文档的文本块数量
            cursor.execute("SELECT doc_id, COUNT(*) FROM text_chunks GROUP BY doc_id")
            doc_chunk_counts = {row[0]: row[1] for row in cursor.fetchall()}
            results['doc_chunk_counts'] = doc_chunk_counts

            cursor.close()
            conn.close()

            logger.info(f"PostgreSQL验证完成: {doc_count}个文档, {chunk_count}个文本块")
            return results
        except Exception as e:
            logger.error(f"PostgreSQL验证失败: {e}")
            return {'error': str(e)}

    def verify_qdrant(self) -> Dict[str, Any]:
        """验证Qdrant数据"""
        logger.info("开始验证Qdrant数据...")
        results = {}

        try:
            client = QdrantClient(**QDRANT_CONFIG)

            # 获取集合信息
            collections = client.get_collections()
            collection_names = [coll.name for coll in collections.collections]
            results['collections'] = collection_names

            # 统计向量数量（使用简单方法）
            if 'document_chunks' in collection_names:
                # 尝试使用count方法
                try:
                    count = client.count(collection_name='document_chunks')
                    results['vector_count'] = count.count
                    logger.info(f"Qdrant验证完成: {count.count}个向量")
                except Exception as e:
                    logger.warning(f"使用count方法失败: {e}")
                    results['vector_count'] = '无法获取'
                    logger.info("Qdrant验证完成: 集合存在但无法获取向量数量")
            else:
                results['vector_count'] = 0
                logger.info("Qdrant验证完成: 未找到document_chunks集合")

            return results
        except Exception as e:
            logger.error(f"Qdrant验证失败: {e}")
            return {'error': str(e)}

    def verify_neo4j(self) -> Dict[str, Any]:
        """验证Neo4j数据"""
        logger.info("开始验证Neo4j数据...")
        results = {}

        try:
            driver = GraphDatabase.driver(**NEO4J_CONFIG)

            with driver.session() as session:
                # 统计文档节点数量
                result = session.run("MATCH (d:Document) RETURN COUNT(d) AS count")
                doc_count = result.single()['count']
                results['document_count'] = doc_count

                # 统计文本块节点数量
                result = session.run("MATCH (c:TextChunk) RETURN COUNT(c) AS count")
                chunk_count = result.single()['count']
                results['chunk_count'] = chunk_count

                # 统计实体节点数量
                result = session.run("MATCH (e:Entity) RETURN COUNT(e) AS count")
                entity_count = result.single()['count']
                results['entity_count'] = entity_count

                # 统计关系数量
                result = session.run("MATCH ()-[r]->() RETURN COUNT(r) AS count")
                relationship_count = result.single()['count']
                results['relationship_count'] = relationship_count

            driver.close()

            logger.info(f"Neo4j验证完成: {doc_count}个文档, {chunk_count}个文本块, {entity_count}个实体, {relationship_count}个关系")
            return results
        except Exception as e:
            logger.error(f"Neo4j验证失败: {e}")
            return {'error': str(e)}

    def verify_knowledge_base(self) -> Dict[str, Any]:
        """验证知识库数据"""
        logger.info("开始验证知识库数据...")
        results = {}

        try:
            kb_dir = Path(KNOWLEDGE_BASE_DIR)

            # 检查目录结构
            doc_dir = kb_dir / "documents"
            metadata_dir = kb_dir / "metadata"
            index_dir = kb_dir / "index"

            # 统计文档数量
            doc_count = len(list(doc_dir.iterdir())) if doc_dir.exists() else 0
            results['document_count'] = doc_count

            # 统计元数据文件数量
            metadata_count = len(list(metadata_dir.glob("*.json"))) if metadata_dir.exists() else 0
            results['metadata_count'] = metadata_count

            # 读取统计信息
            stats_file = index_dir / "statistics.json"
            if stats_file.exists():
                with open(stats_file, 'r', encoding='utf-8') as f:
                    stats = json.load(f)
                    results['statistics'] = stats
                    logger.info(f"知识库验证完成: {doc_count}个文档, {stats.get('total_chunks', 0)}个文本块, {stats.get('total_text_length', 0)}个字符")
            else:
                logger.info(f"知识库验证完成: {doc_count}个文档")

            return results
        except Exception as e:
            logger.error(f"知识库验证失败: {e}")
            return {'error': str(e)}

    def run_verification(self):
        """运行完整的验证"""
        logger.info("=" * 80)
        logger.info("开始四库数据一致性验证")
        logger.info("=" * 80)

        # 执行各个验证
        self.verification_results = {
            'postgresql': self.verify_postgresql(),
            'qdrant': self.verify_qdrant(),
            'neo4j': self.verify_neo4j(),
            'knowledge_base': self.verify_knowledge_base()
        }

        # 生成一致性报告
        self.generate_report()

    def generate_report(self):
        """生成一致性报告"""
        logger.info("=" * 80)
        logger.info("四库数据一致性报告")
        logger.info("=" * 80)

        # 提取关键指标
        postgres_docs = self.verification_results.get('postgresql', {}).get('document_count', 0)
        postgres_chunks = self.verification_results.get('postgresql', {}).get('chunk_count', 0)
        
        qdrant_vectors = self.verification_results.get('qdrant', {}).get('vector_count', 0)
        
        neo4j_docs = self.verification_results.get('neo4j', {}).get('document_count', 0)
        neo4j_chunks = self.verification_results.get('neo4j', {}).get('chunk_count', 0)
        
        kb_docs = self.verification_results.get('knowledge_base', {}).get('document_count', 0)
        kb_chunks = self.verification_results.get('knowledge_base', {}).get('statistics', {}).get('total_chunks', 0)

        # 打印指标
        logger.info("\n1. 文档数量一致性:")
        logger.info(f"   PostgreSQL: {postgres_docs}")
        logger.info(f"   Qdrant: {'N/A' if qdrant_vectors == 0 else '向量数量: ' + str(qdrant_vectors)}")
        logger.info(f"   Neo4j: {neo4j_docs}")
        logger.info(f"   知识库: {kb_docs}")

        logger.info("\n2. 文本块/向量数量一致性:")
        logger.info(f"   PostgreSQL: {postgres_chunks}")
        logger.info(f"   Qdrant: {qdrant_vectors}")
        logger.info(f"   Neo4j: {neo4j_chunks}")
        logger.info(f"   知识库: {kb_chunks}")

        # 检查一致性
        doc_counts = [count for count in [postgres_docs, neo4j_docs, kb_docs] if count > 0]
        chunk_counts = [count for count in [postgres_chunks, qdrant_vectors, neo4j_chunks, kb_chunks] if count > 0]

        doc_consistent = len(set(doc_counts)) == 1 if doc_counts else True
        chunk_consistent = len(set(chunk_counts)) == 1 if chunk_counts else True

        logger.info("\n3. 一致性检查:")
        logger.info(f"   文档数量一致性: {'✓ 一致' if doc_consistent else '✗ 不一致'}")
        logger.info(f"   文本块/向量数量一致性: {'✓ 一致' if chunk_consistent else '✗ 不一致'}")

        # 详细结果
        logger.info("\n4. 详细验证结果:")
        for db, results in self.verification_results.items():
            logger.info(f"\n   {db.upper()}:")
            for key, value in results.items():
                if key != 'doc_chunk_counts':  # 跳过详细的文档-文本块映射
                    logger.info(f"      {key}: {value}")

        logger.info("=" * 80)
        logger.info("验证完成")
        logger.info("=" * 80)

def main():
    """主函数"""
    verifier = DataConsistencyVerifier()
    verifier.run_verification()

if __name__ == "__main__":
    main()
