#!/usr/bin/env python3
"""
四库整合服务 - Qdrant + PostgreSQL + 知识库 + 知识图谱
统一管理四个核心数据库的数据流和查询
"""

import os
import asyncio
import logging
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime
import json
import hashlib

import asyncpg
import redis
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, SearchRequest
from neo4j import GraphDatabase

# 配置
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", 5432))
POSTGRES_DB = os.getenv("POSTGRES_DB", "rag_db")
POSTGRES_USER = os.getenv("POSTGRES_USER", "rag_user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "rag_password")

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "rag_password")

# 日志配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class DocumentProcessed:
    """文档处理结果"""
    document_id: int
    file_name: str
    total_chunks: int
    embedded_chunks: int
    tables_extracted: int
    entities_extracted: int
    knowledge_graph_nodes: int
    processing_time: float
    status: str

class FourDatabaseService:
    """四库整合服务"""
    
    def __init__(self):
        self.redis_client = None
        self.postgres_pool = None
        self.qdrant_client = None
        self.neo4j_driver = None
        
    async def initialize(self):
        """初始化四库连接"""
        logger.info("初始化四库服务...")
        
        # 1. Redis - 缓存和消息队列
        self.redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True
        )
        logger.info("✓ Redis连接成功")
        
        # 2. PostgreSQL - 结构化数据库
        self.postgres_pool = await asyncpg.create_pool(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            database=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            min_size=2,
            max_size=10
        )
        logger.info("✓ PostgreSQL连接成功")
        
        # 3. Qdrant - 向量数据库
        self.qdrant_client = QdrantClient(
            url=f"http://{QDRANT_HOST}:{QDRANT_PORT}"
        )
        logger.info("✓ Qdrant连接成功")
        
        # 4. Neo4j - 知识图谱
        self.neo4j_driver = GraphDatabase.driver(
            "bolt://localhost:7687",
            auth=("neo4j", "rag_password")
        )
        logger.info("✓ Neo4j连接成功")
        
        logger.info("四库服务初始化完成")
    
    async def process_document(
        self,
        file_path: str,
        file_name: str,
        ocr_result: Dict[str, Any]
    ) -> DocumentProcessed:
        """处理文档并存储到四库"""
        start_time = datetime.now()
        
        try:
            # 1. 存储到PostgreSQL - 文档元数据
            document_id = await self._store_document_metadata(file_path, file_name, ocr_result)
            logger.info(f"✓ 文档元数据已存储到PostgreSQL: document_id={document_id}")
            
            # 2. 处理文档块并存储到四库
            chunks_processed = await self._process_and_store_chunks(document_id, ocr_result)
            logger.info(f"✓ 文档块已处理并存储: chunks={chunks_processed}")
            
            # 3. 提取表格数据
            tables_extracted = await self._extract_and_store_tables(document_id, ocr_result)
            logger.info(f"✓ 表格数据已提取并存储: tables={tables_extracted}")
            
            # 4. 提取知识实体
            entities_extracted = await self._extract_and_store_entities(document_id, ocr_result)
            logger.info(f"✓ 知识实体已提取并存储: entities={entities_extracted}")
            
            # 5. 构建知识图谱
            graph_nodes = await self._build_knowledge_graph(document_id, ocr_result)
            logger.info(f"✓ 知识图谱节点已创建: nodes={graph_nodes}")
            
            # 6. 更新文档状态
            await self._update_document_status(document_id, "completed")
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            return DocumentProcessed(
                document_id=document_id,
                file_name=file_name,
                total_chunks=len(ocr_result.get('pages', [])),
                embedded_chunks=chunks_processed,
                tables_extracted=tables_extracted,
                entities_extracted=entities_extracted,
                knowledge_graph_nodes=graph_nodes,
                processing_time=processing_time,
                status="completed"
            )
            
        except Exception as e:
            logger.error(f"文档处理失败: {e}")
            raise
    
    async def _store_document_metadata(
        self,
        file_path: str,
        file_name: str,
        ocr_result: Dict[str, Any]
    ) -> int:
        """存储文档元数据到PostgreSQL"""
        try:
            async with self.postgres_pool.acquire() as conn:
                # 插入文档记录
                document_id = await conn.fetchval("""
                    INSERT INTO documents 
                    (file_name, file_path, file_size, page_count, status, ocr_completed, ocr_result_path)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    RETURNING id
                """,
                    file_name,
                    file_path,
                    os.path.getsize(file_path),
                    ocr_result.get('total_pages', 0),
                    'processing',
                    True,
                    file_path.replace('.pdf', '_ocr.json')
                )
                
                await conn.close()
                return document_id
                
        except Exception as e:
            logger.error(f"存储文档元数据失败: {e}")
            raise
    
    async def _process_and_store_chunks(
        self,
        document_id: int,
        ocr_result: Dict[str, Any]
    ) -> int:
        """处理文档块并存储到四库"""
        try:
            from services.embedding_service import get_embedding_service
            embedding_service = await get_embedding_service()
            
            chunks_processed = 0
            
            # 使用raw_text作为完整页面内容，而不是分散的text_blocks
            for page in ocr_result.get('pages', []):
                page_number = page.get('page_number', 0)
                raw_text = page.get('raw_text', '')
                
                if not raw_text.strip():
                    continue
                
                block_info = {'source': 'raw_text', 'page_number': page_number}
                
                # 存储完整页面到PostgreSQL
                chunk_id = await self._store_chunk_to_postgres(
                    document_id, page_number, raw_text, block_info
                )
                
                # 向量化并存储到Qdrant
                await embedding_service.embed_document_chunk(
                    document_id=document_id,
                    chunk_id=chunk_id,
                    content=raw_text,
                    page_number=page_number
                )
                
                chunks_processed += 1
            
            return chunks_processed
            
        except Exception as e:
            logger.error(f"处理文档块失败: {e}")
            raise
    
    async def _store_chunk_to_postgres(
        self,
        document_id: int,
        page_number: int,
        content: str,
        block: Dict[str, Any]
    ) -> int:
        """存储文档块到PostgreSQL"""
        try:
            async with self.postgres_pool.acquire() as conn:
                chunk_id = await conn.fetchval("""
                    INSERT INTO document_chunks
                    (document_id, chunk_index, content_type, content, page_number, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING id
                """,
                    document_id,
                    block.get('bbox', {}).get('x', 0) if isinstance(block, dict) and 'bbox' in block else 0,
                    'text',
                    content,
                    page_number,
                    json.dumps(block if isinstance(block, dict) else {'source': 'unknown'})
                )

            await conn.close()
            return chunk_id
                
        except Exception as e:
            logger.error(f"存储文档块到PostgreSQL失败: {e}")
            raise
    
    async def _extract_and_store_tables(
        self,
        document_id: int,
        ocr_result: Dict[str, Any]
    ) -> int:
        """提取表格数据并存储"""
        try:
            tables_extracted = 0
            
            for page in ocr_result.get('pages', []):
                page_number = page.get('page_number', 0)
                
                for table in page.get('tables', []):
                    html_content = table.get('html', '')
                    markdown_content = table.get('markdown', '')
                    
                    if not html_content and not markdown_content:
                        continue
                    
                    # 存储到PostgreSQL
                    await self._store_table_to_postgres(
                        document_id, page_number, table
                    )
                    
                    tables_extracted += 1
            
            return tables_extracted
            
        except Exception as e:
            logger.error(f"提取表格数据失败: {e}")
            raise
    
    async def _store_table_to_postgres(
        self,
        document_id: int,
        page_number: int,
        table: Dict[str, Any]
    ) -> int:
        """存储表格数据到PostgreSQL"""
        try:
            async with self.postgres_pool.acquire() as conn:
                table_id = await conn.fetchval("""
                    INSERT INTO tables_data
                    (document_id, table_name, html_content, markdown_content, 
                     row_count, column_count, page_number, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING id
                """,
                    document_id,
                    f"table_page_{page_number}_{table.get('bbox', {}).get('x', 0)}",
                    table.get('html', ''),
                    table.get('markdown', ''),
                    table.get('cells', []),
                    table.get('row_count', 0),
                    table.get('col_count', 0),
                    page_number,
                    json.dumps({
                        'bbox': table.get('bbox', {}),
                        'confidence': table.get('confidence', 0),
                        'page_number': page_number
                    })
                )
                
                await conn.close()
                return table_id
                
        except Exception as e:
            logger.error(f"存储表格数据失败: {e}")
            raise
    
    async def _extract_and_store_entities(
        self,
        document_id: int,
        ocr_result: Dict[str, Any]
    ) -> int:
        """提取知识实体并存储"""
        try:
            entities_extracted = 0
            
            # 简单的实体提取逻辑
            # 实际应用中可以使用更复杂的NLP模型
            full_text = ocr_result.get('full_text', '')
            
            # 提取实体规则（示例）
            entity_patterns = {
                '费用类型': ['计价费率', '企业管理费', '利润', '安全文明施工费'],
                '工程类型': ['建筑工程', '市政工程', '装饰工程', '安装工程'],
                '地区': ['深圳市', '广东省', '全国']
            }
            
            extracted_entities = []
            
            for entity_type, keywords in entity_patterns.items():
                for keyword in keywords:
                    if keyword in full_text:
                        # 检查是否已存在
                        exists = await self._check_entity_exists(keyword, entity_type)
                        if not exists:
                            entity_id = await self._store_entity_to_postgres(
                                document_id, keyword, entity_type
                            )
                            extracted_entities.append(entity_id)
                            entities_extracted += 1
            
            return entities_extracted
            
        except Exception as e:
            logger.error(f"提取知识实体失败: {e}")
            raise
    
    async def _check_entity_exists(self, entity_name: str, entity_type: str) -> bool:
        """检查实体是否已存在"""
        try:
            async with self.postgres_pool.acquire() as conn:
                exists = await conn.fetchval("""
                    SELECT EXISTS(
                        SELECT 1 FROM knowledge_entities 
                        WHERE entity_name = $1 AND entity_type = $2
                    )
                """, entity_name, entity_type)
                
                await conn.close()
                return exists
                
        except Exception as e:
            logger.error(f"检查实体存在失败: {e}")
            return False
    
    async def _store_entity_to_postgres(
        self,
        document_id: int,
        entity_name: str,
        entity_type: str
    ) -> int:
        """存储实体到PostgreSQL"""
        try:
            async with self.postgres_pool.acquire() as conn:
                entity_id = await conn.fetchval("""
                    INSERT INTO knowledge_entities
                    (entity_name, entity_type, source_type, source_document_id, confidence)
                    VALUES ($1, $2, $3, $4, $5, 0.9)
                    RETURNING id
                """, entity_name, entity_type, 'extracted', document_id)
                
                await conn.close()
                return entity_id
                
        except Exception as e:
            logger.error(f"存储实体失败: {e}")
            raise
    
    async def _build_knowledge_graph(
        self,
        document_id: int,
        ocr_result: Dict[str, Any]
    ) -> int:
        """构建知识图谱"""
        try:
            with self.neo4j_driver.session() as session:
                graph_nodes = 0
                
                # 创建文档节点
                session.run("""
                    MERGE (d:Document {id: $id, name: $name})
                    SET d.type = 'document', d.created_at = $created_at
                """, 
                    id=document_id,
                    name=ocr_result.get('file_name', ''),
                    created_at=datetime.now().isoformat()
                )
                graph_nodes += 1
                
                # 创建实体节点和关系
                entities = await self._get_entities_for_document(document_id)
                for entity in entities:
                    # 创建实体节点
                    session.run("""
                        MERGE (e:Entity {id: $id, name: $name, type: $type})
                        SET e.category = $category, e.created_at = $created_at
                    """,
                        id=f"entity_{entity['id']}",
                        name=entity['entity_name'],
                        type=entity['entity_type'],
                        category=entity.get('entity_category', ''),
                        created_at=datetime.now().isoformat()
                    )
                    graph_nodes += 1
                    
                    # 创建文档-实体关系
                    session.run("""
                        MATCH (d:Document {id: $doc_id})
                        MERGE (e:Entity {id: $entity_id})
                        MERGE (d)-[:CONTAINS]->(e)
                    """, doc_id=document_id, entity_id=f"entity_{entity['id']}")
                
                # 创建实体之间的关系
                await self._create_entity_relationships(session, document_id)
                
                return graph_nodes
            
        except Exception as e:
            logger.error(f"构建知识图谱失败: {e}")
            return 0
    
    async def _get_entities_for_document(self, document_id: int) -> List[Dict[str, Any]]:
        """获取文档的所有实体"""
        try:
            async with self.postgres_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT id, entity_name, entity_type, entity_category
                    FROM knowledge_entities
                    WHERE source_document_id = $1
                """, document_id)
                
                await conn.close()
                
                return [
                    {
                        'id': row['id'],
                        'entity_name': row['entity_name'],
                        'entity_type': row['entity_type'],
                        'entity_category': row['entity_category']
                    }
                    for row in rows
                ]
                
        except Exception as e:
            logger.error(f"获取文档实体失败: {e}")
            return []
    
    async def _create_entity_relationships(self, session, document_id: int):
        """创建实体之间的关系"""
        try:
            # 获取文档的所有实体
            entities = await self._get_entities_for_document(document_id)
            
            # 简单的关系创建逻辑
            for i, entity1 in enumerate(entities):
                for entity2 in entities[i+1:]:
                    # 如果实体类型相同，创建相关关系
                    if entity1['entity_type'] == entity2['entity_type']:
                        session.run("""
                            MATCH (e1:Entity {id: $id1})
                            MATCH (e2:Entity {id: $id2})
                            MERGE (e1)-[:RELATED_TO]->(e2)
                        """, 
                            id1=f"entity_{entity1['id']}",
                            id2=f"entity_{entity2['id']}"
                        )
            
        except Exception as e:
            logger.error(f"创建实体关系失败: {e}")
    
    async def _update_document_status(self, document_id: int, status: str):
        """更新文档状态"""
        try:
            async with self.postgres_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE documents
                    SET status = $1, processing_status = $2, processed_at = $3
                    WHERE id = $4
                """, status, status, datetime.now(), document_id)
                
                await conn.close()
                
        except Exception as e:
            logger.error(f"更新文档状态失败: {e}")
    
    async def search_four_databases(
        self,
        query_text: str,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """四库联合搜索"""
        try:
            # 1. 向量搜索 (Qdrant)
            from services.embedding_service import get_embedding_service
            embedding_service = await get_embedding_service()
            
            vector_results = await embedding_service.search_similar_chunks(
                query_text=query_text,
                top_k=top_k * 2,  # 召回更多结果用于重排
                score_threshold=0.6
            )
            
            # 2. 知识图谱查询 (Neo4j)
            graph_results = await self._search_knowledge_graph(query_text)
            
            # 3. 关键词搜索 (Elasticsearch)
            keyword_results = await self._search_elasticsearch(query_text, top_k=top_k)
            
            # 4. 结构化数据查询 (PostgreSQL)
            structured_results = await self._search_postgresql(query_text, top_k=top_k)
            
            # 合并和重排结果
            final_results = await self._merge_and_rerank(
                query_text=query_text,
                vector_results=vector_results,
                graph_results=graph_results,
                keyword_results=keyword_results,
                structured_results=structured_results,
                top_k=top_k
            )
            
            return final_results
            
        except Exception as e:
            logger.error(f"四库搜索失败: {e}")
            raise
    
    async def _search_knowledge_graph(self, query_text: str) -> List[Dict[str, Any]]:
        """搜索知识图谱"""
        try:
            with self.neo4j.driver.session() as session:
                # 查找相关实体
                result = session.run("""
                    MATCH (e:Entity)
                    WHERE e.name CONTAINS $query_text
                    RETURN e.id, e.name, e.type, e.category
                    LIMIT 10
                """, query_text=query_text)
                
                results = []
                for record in result:
                    results.append({
                        'entity_id': record['e.id'],
                        'entity_name': record['e.name'],
                        'entity_type': record['e.type'],
                        'entity_category': record['e.category']
                    })
                
                return results
                
        except Exception as e:
            logger.error(f"知识图谱搜索失败: {e}")
            return []
    
    async def _search_elasticsearch(self, query_text: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """搜索Elasticsearch"""
        try:
            import requests
            
            # 简化的Elasticsearch搜索
            # 实际应用中应该使用elasticsearch-py客户端
            es_url = "http://localhost:9200"
            
            search_body = {
                "query": {
                    "multi_match": {
                        "query": query_text,
                        "fields": ["content", "file_name", "metadata"],
                        "type": "best_fields"
                    }
                },
                "size": top_k
            }
            
            response = requests.post(
                f"{es_url}/document_chunks/_search",
                json=search_body,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                results = []
                for hit in data.get('hits', {}).get('hits', []):
                    results.append({
                        'chunk_id': hit['_id'],
                        'score': hit['_score'],
                        'source': hit['_source']
                    })
                return results
            
            return []
            
        except Exception as e:
            logger.error(f"Elasticsearch搜索失败: {e}")
            return []
    
    async def _search_postgresql(self, query_text: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """搜索PostgreSQL"""
        try:
            async with self.postgres_pool.acquire() as conn:
                # 全文搜索
                results = await conn.fetch("""
                    SELECT 
                        dc.id as chunk_id,
                        dc.content,
                        dc.page_number,
                        d.file_name,
                        ts_rank(dc.content, to_tsquery('chinese', $query)) as rank
                    FROM document_chunks dc
                    JOIN documents d ON dc.document_id = d.id
                    WHERE to_tsvector('chinese', dc.content) @@ to_tsquery('chinese', $query)
                    ORDER BY rank
                    LIMIT $1
                """, query_text, top_k)
                
                await conn.close()
                
                return [
                    {
                        'chunk_id': row['chunk_id'],
                        'content': row['content'],
                        'page_number': row['page_number'],
                        'file_name': row['file_name'],
                        'rank': row['rank']
                    }
                    for row in results
                ]
                
        except Exception as e:
            logger.error(f"PostgreSQL搜索失败: {e}")
            return []
    
    async def _merge_and_rerank(
        self,
        query_text: str,
        vector_results: List[Dict[str, Any]],
        graph_results: List[Dict[str, Any]],
        keyword_results: List[Dict[str, Any]],
        structured_results: List[Dict[str, Any]],
        top_k: int = 10
    ) -> Dict[str, Any]:
        """合并和重排结果"""
        try:
            from services.rerank_service import get_rerank_service
            rerank_service = await get_rerank_service()
            
            # 收集所有候选结果
            all_candidates = []
            
            # 添加向量搜索结果
            for result in vector_results:
                all_candidates.append({
                    'chunk_id': result['chunk_id'],
                    'source': 'vector',
                    'score': result['score'],
                    'content': result['content']
                })
            
            # 添加知识图谱结果
            for result in graph_results:
                all_candidates.append({
                    'chunk_id': f"graph_{result['entity_id']}",
                    'source': 'graph',
                    'score': 0.8,  # 默认分数
                    'content': f"实体: {result['entity_name']}"
                })
            
            # 添加关键词搜索结果
            for result in keyword_results:
                all_candidates.append({
                    'chunk_id': result['chunk_id'],
                    'source': 'keyword',
                    'score': result['score'],
                    'content': result['source'].get('content', '')
                })
            
            # 添加结构化搜索结果
            for result in structured_results:
                all_candidates.append({
                    'chunk_id': result['chunk_id'],
                    'source': 'structured',
                    'score': 1.0 / (result['rank'] + 1),  # 转换rank为分数
                    'content': result['content']
                })
            
            # 去重
            seen_chunk_ids = set()
            unique_candidates = []
            for candidate in all_candidates:
                chunk_id = candidate['chunk_id'].replace('graph_', '')
                if chunk_id not in seen_chunk_ids:
                    seen_chunk_ids.add(chunk_id)
                    unique_candidates.append(candidate)
            
            # Rerank重排
            reranked_results = await rerank_service.rerank(
                query_text=query_text,
                candidates=unique_candidates,
                top_k=top_k
            )
            
            return {
                'query_text': query_text,
                'total_candidates': len(unique_candidates),
                'final_results': reranked_results,
                'search_stats': {
                    'vector_results': len(vector_results),
                    'graph_results': len(graph_results),
                    'keyword_results': len(keyword_results),
                    'structured_results': len(structured_results),
                    'total_after_dedup': len(unique_candidates)
                }
            }
            
        except Exception as e:
            logger.error(f"合并重排结果失败: {e}")
            raise
    
    async def get_system_statistics(self) -> Dict[str, Any]:
        """获取系统统计信息"""
        try:
            # PostgreSQL统计
            async with self.postgres_pool.acquire() as conn:
                doc_count = await conn.fetchval("SELECT COUNT(*) FROM documents")
                chunk_count = await conn.fetchval("SELECT COUNT(*) FROM document_chunks")
                table_count = await conn.fetchval("SELECT COUNT(*) FROM tables_data")
                entity_count = await conn.fetchval("SELECT COUNT(*) FROM knowledge_entities")
                
                processed_docs = await conn.fetchval("SELECT COUNT(*) FROM documents WHERE status = 'completed'")
                
                await conn.close()
            
            # Qdrant统计
            qdrant_collections = self.qdrant_client.get_collections().collections
            qdrant_stats = {
                'collections': [collection.name for collection in qdrant_collections]
            }
            
            # Neo4j统计
            with self.neo4j_driver.session() as session:
                node_count = session.run("MATCH (n) RETURN count(n) as count").single()["count"]
                relationship_count = session.run("MATCH ()-[r]->() RETURN count(r) as count").single()["count"]
            
            # Redis统计
            redis_info = self.redis_client.info()
            
            stats = {
                'documents': {
                    'total': doc_count,
                    'processed': processed_docs,
                    'processing': doc_count - processed_docs
                },
                'chunks': {
                    'total': chunk_count,
                    'embedded': await self._get_embedded_count()
                },
                'tables': table_count,
                'entities': entity_count,
                'knowledge_graph': {
                    'nodes': node_count,
                    'relationships': relationship_count
                },
                'qdrant': qdrant_stats,
                'redis': {
                    'used_memory': redis_info['used_memory_human'],
                    'connected_clients': redis_info['connected_clients']
                },
                'processing_progress': {
                    'completion_rate': round(processed_docs / doc_count * 100, 2) if doc_count > 0 else 0
                }
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"获取系统统计失败: {e}")
            raise
    
    async def _get_embedded_count(self) -> int:
        """获取已向量化的块数"""
        try:
            async with self.postgres_pool.acquire() as conn:
                count = await conn.fetchval("SELECT COUNT(*) FROM document_chunks WHERE embedding_id IS NOT NULL")
                await conn.close()
                return count
        except Exception as e:
            logger.error(f"获取向量化统计失败: {e}")
            return 0
    
    async def close(self):
        """关闭所有连接"""
        logger.info("关闭四库服务...")
        
        if self.postgres_pool:
            await self.postgres_pool.close()
        
        if self.redis_client:
            self.redis_client.close()
        
        if self.qdrant_client:
            self.qdrant_client.close()
        
        if self.neo4j_driver:
            self.neo4j_driver.close()
        
        logger.info("四库服务已关闭")

# 全局实例
four_db_service = FourDatabaseService()

async def get_four_db_service() -> FourDatabaseService:
    """获取四库服务实例"""
    if four_db_service.postgres_pool is None:
        await four_db_service.initialize()
    return four_db_service