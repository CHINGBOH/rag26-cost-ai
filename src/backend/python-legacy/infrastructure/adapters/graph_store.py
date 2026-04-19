"""
基础设施层 - 图存储适配器
实现 GraphStorePort 接口
"""

from typing import List
from neo4j import GraphDatabase
import hashlib
import re

from domain.models import Document, DocumentChunk
from domain.ports import GraphStorePort
from config.settings import GraphStoreConfig


class Neo4jGraphStoreAdapter(GraphStorePort):
    """
    Neo4j 图存储适配器

    实现实体关系存储和图谱检索
    """

    def __init__(self, config: GraphStoreConfig):
        self.config = config
        self._driver = None
        self._connect()

    def _connect(self) -> None:
        """连接到 Neo4j"""
        try:
            self._driver = GraphDatabase.driver(
                self.config.uri,
                auth=(self.config.username, self.config.password.get_secret_value()),
            )
            self._driver.verify_connectivity()
            self._ensure_schema()
        except Exception as e:
            print(f"Neo4j 连接失败: {e}")
            self._driver = None

    def _ensure_schema(self) -> None:
        """确保数据库模式"""
        with self._driver.session() as session:
            # 创建约束
            try:
                session.run("""
                    CREATE CONSTRAINT entity_id IF NOT EXISTS
                    FOR (e:Entity) REQUIRE e.id IS UNIQUE
                """)
            except Exception:
                pass

            # 创建索引
            try:
                session.run("""
                    CREATE INDEX entity_name IF NOT EXISTS
                    FOR (e:Entity) ON (e.name)
                """)
            except Exception:
                pass

    def is_available(self) -> bool:
        """检查是否可用"""
        if self._driver is None:
            return False
        try:
            self._driver.verify_connectivity()
            return True
        except Exception:
            return False

    async def expand_entities(
        self, entity_names: List[str], depth: int = 2, top_k: int = 10
    ) -> List[Document]:
        """
        实体扩展检索

        从给定实体出发，在图谱中扩展找到相关文档
        """
        if not self.is_available() or not entity_names:
            return []

        try:
            query = (
                """
            MATCH (start:Entity)
            WHERE start.name IN $entity_names
            MATCH path = (start)-[:RELATED|PART_OF*1..%d]-(related:Entity)
            MATCH (related)-[:MENTIONED_IN]->(d:Document)
            OPTIONAL MATCH (d)<-[:PART_OF]-(c:Chunk)
            
            WITH d, c, related, path,
                 length(path) as path_length,
                 count(DISTINCT related) as entity_count
            
            WITH d, c, related,
                 (1.0 / path_length) * entity_count as relevance
            
            RETURN d.id as doc_id,
                   d.title as title,
                   collect(DISTINCT c.content)[0..5] as contents,
                   collect(DISTINCT related.name) as related_entities,
                   sum(relevance) as total_relevance
            ORDER BY total_relevance DESC
            LIMIT $top_k
            """
                % depth
            )

            with self._driver.session() as session:
                result = session.run(query, {"entity_names": entity_names, "top_k": top_k})

                documents = []
                for record in result:
                    contents = record["contents"] or [""]
                    doc = Document(
                        id=f"{record['doc_id']}_graph",
                        content="\n".join(contents),
                        doc_id=record["doc_id"],
                        title=record["title"],
                        graph_score=record["total_relevance"],
                        metadata={"related_entities": record["related_entities"]},
                    )
                    documents.append(doc)

                return documents

        except Exception as e:
            print(f"实体扩展失败: {e}")
            return []

    async def build_from_document(self, doc_id: str, chunks: List[DocumentChunk]) -> bool:
        """
        从文档构建知识图谱

        提取实体和关系，构建知识图谱
        """
        if not self.is_available():
            return False

        try:
            all_entities = []
            all_relationships = []

            for chunk in chunks:
                # 提取实体
                entities = self._extract_entities(chunk.content)
                all_entities.extend(entities)

                # 提取关系
                relationships = self._extract_relationships(entities, chunk.content)
                all_relationships.extend(relationships)

                # 链接文档和实体
                entity_ids = [e["id"] for e in entities]
                self._link_document_entities(doc_id, entity_ids, [chunk.id])

            # 去重实体
            seen = set()
            unique_entities = []
            for e in all_entities:
                if e["id"] not in seen:
                    seen.add(e["id"])
                    unique_entities.append(e)

            # 存储到图谱
            self._create_entities(unique_entities)
            self._create_relationships(all_relationships)

            return True

        except Exception as e:
            print(f"图谱构建失败: {e}")
            return False

    def _extract_entities(self, text: str) -> List[dict]:
        """从文本中提取实体"""
        patterns = [
            (r"[\u4e00-\u9fa5]{2,10}(?:公司|集团|企业)", "company"),
            (r"[\u4e00-\u9fa5]{2,8}(?:标准|规范|规定|办法|指南)", "standard"),
            (r"HJ\d+(?:\.\d+)?(?:-\d+)?", "standard_code"),
            (r"GB[\/T]?\d+(?:\.\d+)?(?:-\d+)?", "standard_code"),
            (r"(?:人工费|材料费|机械费|企业管理费|利润|规费|税金)", "cost_concept"),
            (r"(?:分部分项工程|措施项目|其他项目)", "project_concept"),
        ]

        entities = []
        for pattern, entity_type in patterns:
            matches = re.finditer(pattern, text)
            for match in matches:
                name = match.group()
                entity_id = hashlib.md5(f"{entity_type}:{name}".encode()).hexdigest()[:16]

                entities.append({"id": entity_id, "name": name, "type": entity_type})

        return entities

    def _extract_relationships(self, entities: List[dict], text: str) -> List[dict]:
        """提取实体间关系"""
        relationships = []

        if len(entities) >= 2:
            for i, e1 in enumerate(entities):
                for e2 in entities[i + 1 :]:
                    relationships.append(
                        {
                            "source": e1["id"],
                            "target": e2["id"],
                            "type": "RELATED",
                            "context": text[:100],
                        }
                    )

        return relationships

    def _create_entities(self, entities: List[dict]) -> None:
        """创建实体节点"""
        with self._driver.session() as session:
            for entity in entities:
                session.run(
                    """
                    MERGE (e:Entity {id: $id})
                    SET e.name = $name,
                        e.entity_type = $entity_type
                """,
                    {"id": entity["id"], "name": entity["name"], "entity_type": entity["type"]},
                )

    def _create_relationships(self, relationships: List[dict]) -> None:
        """创建关系边"""
        with self._driver.session() as session:
            for rel in relationships:
                session.run(
                    f"""
                    MATCH (a:Entity {{id: $source}})
                    MATCH (b:Entity {{id: $target}})
                    MERGE (a)-[r:{rel["type"]}]->(b)
                    SET r.context = $context
                """,
                    {
                        "source": rel["source"],
                        "target": rel["target"],
                        "context": rel.get("context", ""),
                    },
                )

    def _link_document_entities(
        self, doc_id: str, entity_ids: List[str], chunk_ids: List[str]
    ) -> None:
        """链接文档和实体"""
        with self._driver.session() as session:
            # 创建文档节点
            session.run(
                """
                MERGE (d:Document {id: $doc_id})
            """,
                {"doc_id": doc_id},
            )

            # 链接实体到文档
            for entity_id in entity_ids:
                session.run(
                    """
                    MATCH (e:Entity {id: $entity_id})
                    MATCH (d:Document {id: $doc_id})
                    MERGE (e)-[:MENTIONED_IN]->(d)
                """,
                    {"entity_id": entity_id, "doc_id": doc_id},
                )

            # 链接到具体片段
            for chunk_id in chunk_ids:
                session.run(
                    """
                    MATCH (d:Document {id: $doc_id})
                    MERGE (c:Chunk {id: $chunk_id})
                    MERGE (c)-[:PART_OF]->(d)
                """,
                    {"doc_id": doc_id, "chunk_id": chunk_id},
                )


class MemoryGraphStoreAdapter(GraphStorePort):
    """
    内存图存储适配器

    用于测试和开发环境
    """

    def __init__(self, config: GraphStoreConfig | None = None):
        self._entities: dict[str, dict] = {}
        self._relationships: List[dict] = []
        self._doc_entities: dict[str, set] = {}

    def is_available(self) -> bool:
        return True

    async def expand_entities(
        self, entity_names: List[str], depth: int = 2, top_k: int = 10
    ) -> List[Document]:
        """简单实体扩展"""
        # 找到起始实体
        start_entities = [e for e in self._entities.values() if e["name"] in entity_names]

        # 简单匹配
        related_docs = []
        for doc_id, entity_ids in self._doc_entities.items():
            for entity in start_entities:
                if entity["id"] in entity_ids:
                    related_docs.append(
                        Document(
                            id=f"{doc_id}_graph",
                            content=f"Document {doc_id}",
                            doc_id=doc_id,
                            graph_score=1.0,
                        )
                    )
                    break

        return related_docs[:top_k]

    async def build_from_document(self, doc_id: str, chunks: List[DocumentChunk]) -> bool:
        """构建内存图谱"""
        import re

        patterns = [
            (r"[\u4e00-\u9fa5]{2,10}(?:公司|集团|企业)", "company"),
            (r"[\u4e00-\u9fa5]{2,8}(?:标准|规范|规定)", "standard"),
            (r"HJ\d+", "standard_code"),
            (r"(?:人工费|材料费|机械费|企业管理费)", "cost_concept"),
        ]

        entity_ids = []
        for chunk in chunks:
            for pattern, entity_type in patterns:
                matches = re.finditer(pattern, chunk.content)
                for match in matches:
                    name = match.group()
                    entity_id = hashlib.md5(f"{entity_type}:{name}".encode()).hexdigest()[:16]

                    self._entities[entity_id] = {"id": entity_id, "name": name, "type": entity_type}
                    entity_ids.append(entity_id)

        self._doc_entities[doc_id] = set(entity_ids)
        return True
