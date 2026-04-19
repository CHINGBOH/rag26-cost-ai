#!/usr/bin/env python3
"""
知识图谱客户端 - Neo4j 实现
支持实体关系检索和图谱推理
"""

from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, field
import json


@dataclass
class Entity:
    """实体节点"""

    id: str
    name: str
    entity_type: str  # 'company', 'standard', 'person', 'concept', etc.
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Relationship:
    """关系边"""

    source: str  # 源实体 ID
    target: str  # 目标实体 ID
    rel_type: str  # 关系类型
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphDocument:
    """图谱关联文档"""

    id: str
    content: str
    doc_id: str
    title: str = ""
    page: int = 0
    relevance_score: float = 0.0
    related_entities: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class Neo4jClient:
    """
    Neo4j 知识图谱客户端

    功能:
    - 实体和关系存储
    - 实体扩展检索
    - 路径发现
    - 图算法
    """

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        user: str = "neo4j",
        password: str = "password",
        database: str = "neo4j",
    ):
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database
        self._driver = None
        self._connect()

    def _connect(self):
        """连接到 Neo4j"""
        try:
            from neo4j import GraphDatabase

            self._driver = GraphDatabase.driver(
                self.uri, auth=(self.user, self.password)
            )

            # 验证连接
            self._driver.verify_connectivity()
            print(f"✓ 连接到 Neo4j: {self.uri}")

            # 确保约束和索引
            self._ensure_schema()

        except ImportError:
            print("⚠ 未安装 neo4j-driver，使用内存模式")
            self._driver = None
            self._memory_entities: Dict[str, Entity] = {}
            self._memory_relationships: List[Relationship] = []
            self._memory_doc_entities: Dict[str, Set[str]] = {}  # doc_id -> entity_ids
        except Exception as e:
            print(f"⚠ Neo4j 连接失败: {e}，使用内存模式")
            self._driver = None
            self._memory_entities = {}
            self._memory_relationships = []
            self._memory_doc_entities = {}

    def _ensure_schema(self):
        """确保数据库模式"""
        if self._driver is None:
            return

        with self._driver.session(database=self.database) as session:
            # 创建实体唯一约束
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
                session.run("""
                    CREATE INDEX entity_type IF NOT EXISTS
                    FOR (e:Entity) ON (e.entity_type)
                """)
            except Exception:
                pass

    def is_connected(self) -> bool:
        """检查是否已连接"""
        if self._driver is None:
            return False
        try:
            self._driver.verify_connectivity()
            return True
        except Exception:
            return False

    def close(self):
        """关闭连接"""
        if self._driver:
            self._driver.close()

    def create_entities(self, entities: List[Entity]) -> bool:
        """
        创建实体节点

        Args:
            entities: 实体列表

        Returns:
            是否成功
        """
        if not entities:
            return True

        if self._driver is None:
            # 内存模式
            for entity in entities:
                self._memory_entities[entity.id] = entity
            return True

        try:
            with self._driver.session(database=self.database) as session:
                for entity in entities:
                    session.run(
                        """
                        MERGE (e:Entity {id: $id})
                        SET e.name = $name,
                            e.entity_type = $entity_type,
                            e += $properties
                    """,
                        {
                            "id": entity.id,
                            "name": entity.name,
                            "entity_type": entity.entity_type,
                            "properties": entity.properties,
                        },
                    )
            return True

        except Exception as e:
            print(f"创建实体失败: {e}")
            return False

    def create_relationships(self, relationships: List[Relationship]) -> bool:
        """
        创建关系边

        Args:
            relationships: 关系列表

        Returns:
            是否成功
        """
        if not relationships:
            return True

        if self._driver is None:
            # 内存模式
            self._memory_relationships.extend(relationships)
            return True

        try:
            with self._driver.session(database=self.database) as session:
                for rel in relationships:
                    session.run(
                        f"""
                        MATCH (a:Entity {{id: $source}})
                        MATCH (b:Entity {{id: $target}})
                        MERGE (a)-[r:{rel.rel_type}]->(b)
                        SET r += $properties
                    """,
                        {
                            "source": rel.source,
                            "target": rel.target,
                            "properties": rel.properties,
                        },
                    )
            return True

        except Exception as e:
            print(f"创建关系失败: {e}")
            return False

    def link_document_entities(
        self, doc_id: str, entity_ids: List[str], chunk_ids: Optional[List[str]] = None
    ) -> bool:
        """
        链接文档和实体

        Args:
            doc_id: 文档 ID
            entity_ids: 实体 ID 列表
            chunk_ids: 片段 ID 列表

        Returns:
            是否成功
        """
        if self._driver is None:
            # 内存模式
            if doc_id not in self._memory_doc_entities:
                self._memory_doc_entities[doc_id] = set()
            self._memory_doc_entities[doc_id].update(entity_ids)
            return True

        try:
            with self._driver.session(database=self.database) as session:
                for entity_id in entity_ids:
                    session.run(
                        """
                        MATCH (e:Entity {id: $entity_id})
                        MERGE (d:Document {id: $doc_id})
                        MERGE (e)-[:MENTIONED_IN]->(d)
                    """,
                        {"entity_id": entity_id, "doc_id": doc_id},
                    )

                    # 链接到具体片段
                    if chunk_ids:
                        for chunk_id in chunk_ids:
                            session.run(
                                """
                                MATCH (e:Entity {id: $entity_id})
                                MATCH (d:Document {id: $doc_id})
                                MERGE (c:Chunk {id: $chunk_id})
                                MERGE (e)-[:APPEARS_IN]->(c)
                                MERGE (c)-[:PART_OF]->(d)
                            """,
                                {
                                    "entity_id": entity_id,
                                    "doc_id": doc_id,
                                    "chunk_id": chunk_id,
                                },
                            )
            return True

        except Exception as e:
            print(f"链接文档实体失败: {e}")
            return False

    def expand_entities(
        self, entity_names: List[str], depth: int = 2, top_k: int = 10
    ) -> List[GraphDocument]:
        """
        实体扩展检索

        从给定实体出发，在图谱中扩展找到相关实体，
        然后找到与这些实体相关的文档

        Args:
            entity_names: 实体名称列表
            depth: 扩展深度
            top_k: 返回文档数量

        Returns:
            关联文档列表
        """
        if self._driver is None:
            return self._memory_expand(entity_names, depth, top_k)

        try:
            # Cypher 查询：扩展实体并找到相关文档
            query = """
            // 找到起始实体
            MATCH (start:Entity)
            WHERE start.name IN $entity_names
            
            // 扩展到相关实体（可变深度）
            MATCH path = (start)-[:RELATED|PART_OF|SUBCLASS*1..{depth}]-(related:Entity)
            
            // 找到实体提及的文档
            MATCH (related)-[:MENTIONED_IN]->(d:Document)
            OPTIONAL MATCH (d)<-[:PART_OF]-(c:Chunk)
            
            // 计算相关性分数（基于路径长度和实体连接数）
            WITH d, c, related, path,
                 length(path) as path_length,
                 count(DISTINCT related) as entity_count
            
            // 计算分数：越短的路径、越多相关实体，分数越高
            WITH d, c, related,
                 (1.0 / path_length) * entity_count as relevance
            
            // 聚合结果
            RETURN d.id as doc_id,
                   d.title as title,
                   collect(DISTINCT c.content)[0..5] as contents,
                   collect(DISTINCT related.name) as related_entities,
                   sum(relevance) as total_relevance
            ORDER BY total_relevance DESC
            LIMIT $top_k
            """.format(depth=depth)

            with self._driver.session(database=self.database) as session:
                result = session.run(
                    query, {"entity_names": entity_names, "top_k": top_k}
                )

                documents = []
                for record in result:
                    contents = record["contents"] or [""]
                    doc = GraphDocument(
                        id=f"{record['doc_id']}_graph",
                        content="\n".join(contents),
                        doc_id=record["doc_id"],
                        title=record["title"],
                        relevance_score=record["total_relevance"],
                        related_entities=record["related_entities"],
                    )
                    documents.append(doc)

                return documents

        except Exception as e:
            print(f"实体扩展失败: {e}")
            return []

    def _memory_expand(
        self, entity_names: List[str], depth: int, top_k: int
    ) -> List[GraphDocument]:
        """内存模式实体扩展"""
        # 找到起始实体
        start_entities = []
        for entity in self._memory_entities.values():
            if entity.name in entity_names:
                start_entities.append(entity)

        # 简单扩展（仅一层）
        related_docs = []
        for doc_id, entity_ids in self._memory_doc_entities.items():
            for entity in start_entities:
                if entity.id in entity_ids:
                    related_docs.append(
                        GraphDocument(
                            id=f"{doc_id}_graph",
                            content=f"Document {doc_id}",
                            doc_id=doc_id,
                            relevance_score=1.0,
                        )
                    )
                    break

        return related_docs[:top_k]

    def find_path(self, entity1: str, entity2: str, max_depth: int = 4) -> List[Dict]:
        """
        查找两个实体之间的路径

        Args:
            entity1: 起始实体名称
            entity2: 目标实体名称
            max_depth: 最大深度

        Returns:
            路径列表
        """
        if self._driver is None:
            return []

        try:
            query = """
            MATCH path = shortestPath(
                (a:Entity {name: $entity1})-[:RELATED|PART_OF|SUBCLASS*1..{max_depth}]-(b:Entity {name: $entity2})
            )
            RETURN [node in nodes(path) | node.name] as node_names,
                   [rel in relationships(path) | type(rel)] as rel_types,
                   length(path) as path_length
            """.format(max_depth=max_depth)

            with self._driver.session(database=self.database) as session:
                result = session.run(query, {"entity1": entity1, "entity2": entity2})

                paths = []
                for record in result:
                    paths.append(
                        {
                            "nodes": record["node_names"],
                            "relationships": record["rel_types"],
                            "length": record["path_length"],
                        }
                    )

                return paths

        except Exception as e:
            print(f"路径查找失败: {e}")
            return []

    def get_entity_neighbors(
        self, entity_name: str, rel_types: Optional[List[str]] = None
    ) -> List[Entity]:
        """
        获取实体的邻居

        Args:
            entity_name: 实体名称
            rel_types: 关系类型过滤

        Returns:
            邻居实体列表
        """
        if self._driver is None:
            return []

        try:
            if rel_types:
                rel_filter = "|".join(f"`{r}`" for r in rel_types)
                query = f"""
                MATCH (e:Entity {{name: $name}})-[{rel_filter}]-(neighbor:Entity)
                RETURN DISTINCT neighbor
                """
            else:
                query = """
                MATCH (e:Entity {name: $name})--(neighbor:Entity)
                RETURN DISTINCT neighbor
                """

            with self._driver.session(database=self.database) as session:
                result = session.run(query, {"name": entity_name})

                neighbors = []
                for record in result:
                    node = record["neighbor"]
                    entity = Entity(
                        id=node["id"],
                        name=node["name"],
                        entity_type=node["entity_type"],
                        properties=dict(node),
                    )
                    neighbors.append(entity)

                return neighbors

        except Exception as e:
            print(f"获取邻居失败: {e}")
            return []

    def search_entities(
        self, keyword: str, entity_type: Optional[str] = None, top_k: int = 10
    ) -> List[Entity]:
        """
        搜索实体

        Args:
            keyword: 关键词
            entity_type: 实体类型过滤
            top_k: 返回数量

        Returns:
            实体列表
        """
        if self._driver is None:
            # 内存模式
            results = []
            for entity in self._memory_entities.values():
                if keyword in entity.name:
                    if entity_type is None or entity.entity_type == entity_type:
                        results.append(entity)
            return results[:top_k]

        try:
            if entity_type:
                query = """
                MATCH (e:Entity)
                WHERE e.name CONTAINS $keyword AND e.entity_type = $entity_type
                RETURN e
                LIMIT $top_k
                """
            else:
                query = """
                MATCH (e:Entity)
                WHERE e.name CONTAINS $keyword
                RETURN e
                LIMIT $top_k
                """

            with self._driver.session(database=self.database) as session:
                result = session.run(
                    query,
                    {"keyword": keyword, "entity_type": entity_type, "top_k": top_k},
                )

                entities = []
                for record in result:
                    node = record["e"]
                    entity = Entity(
                        id=node["id"],
                        name=node["name"],
                        entity_type=node["entity_type"],
                        properties={
                            k: v
                            for k, v in node.items()
                            if k not in ["id", "name", "entity_type"]
                        },
                    )
                    entities.append(entity)

                return entities

        except Exception as e:
            print(f"搜索实体失败: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """获取图谱统计"""
        if self._driver is None:
            return {
                "entities": len(self._memory_entities),
                "relationships": len(self._memory_relationships),
                "documents": len(self._memory_doc_entities),
                "mode": "memory",
            }

        try:
            with self._driver.session(database=self.database) as session:
                entity_count = session.run(
                    "MATCH (e:Entity) RETURN count(e) as c"
                ).single()["c"]
                rel_count = session.run(
                    "MATCH ()-[r]->() RETURN count(r) as c"
                ).single()["c"]
                doc_count = session.run(
                    "MATCH (d:Document) RETURN count(d) as c"
                ).single()["c"]

                return {
                    "entities": entity_count,
                    "relationships": rel_count,
                    "documents": doc_count,
                    "mode": "neo4j",
                }
        except Exception as e:
            return {"error": str(e)}


class GraphBuilder:
    """
    图谱构建器

    从文档中提取实体和关系，构建知识图谱
    """

    def __init__(self, neo4j_client: Neo4jClient):
        self.neo4j = neo4j_client

    def extract_entities(self, text: str) -> List[Entity]:
        """
        从文本中提取实体

        简化实现，实际应使用 NER 模型
        """
        import re
        import hashlib

        entities = []

        # 模式匹配提取实体
        patterns = [
            (r"[\u4e00-\u9fa5]{2,10}(?:公司|集团|企业)", "company"),
            (r"[\u4e00-\u9fa5]{2,8}(?:标准|规范|规定|办法|指南)", "standard"),
            (r"HJ\d+(?:\.\d+)?(?:-\d+)?", "standard_code"),
            (r"GB[\/T]?\d+(?:\.\d+)?(?:-\d+)?", "standard_code"),
            (r"(?:人工费|材料费|机械费|企业管理费|利润|规费|税金)", "cost_concept"),
            (r"(?:分部分项工程|措施项目|其他项目)", "project_concept"),
        ]

        for pattern, entity_type in patterns:
            matches = re.finditer(pattern, text)
            for match in matches:
                name = match.group()
                entity_id = hashlib.md5(f"{entity_type}:{name}".encode()).hexdigest()[
                    :16
                ]

                entity = Entity(id=entity_id, name=name, entity_type=entity_type)
                entities.append(entity)

        # 去重
        seen = set()
        unique = []
        for e in entities:
            if e.id not in seen:
                seen.add(e.id)
                unique.append(e)

        return unique

    def extract_relationships(
        self, entities: List[Entity], text: str
    ) -> List[Relationship]:
        """
        从文本中提取实体间关系

        简化实现，实际应使用关系抽取模型
        """
        relationships = []

        # 简单的共现关系
        if len(entities) >= 2:
            for i, e1 in enumerate(entities):
                for e2 in entities[i + 1 :]:
                    rel = Relationship(
                        source=e1.id,
                        target=e2.id,
                        rel_type="RELATED",
                        properties={"context": text[:100]},
                    )
                    relationships.append(rel)

        return relationships

    def build_from_document(self, doc_id: str, chunks: List[Dict[str, Any]]) -> bool:
        """
        从文档构建图谱

        Args:
            doc_id: 文档 ID
            chunks: 文档片段列表

        Returns:
            是否成功
        """
        all_entities = []
        all_relationships = []
        chunk_entity_map = {}  # chunk_id -> entity_ids

        for chunk in chunks:
            content = chunk.get("content", "")
            chunk_id = chunk.get("id", f"{doc_id}_{hash(content)}")

            # 提取实体
            entities = self.extract_entities(content)
            all_entities.extend(entities)
            chunk_entity_map[chunk_id] = [e.id for e in entities]

            # 提取关系
            relationships = self.extract_relationships(entities, content)
            all_relationships.extend(relationships)

        # 去重实体
        seen = set()
        unique_entities = []
        for e in all_entities:
            if e.id not in seen:
                seen.add(e.id)
                unique_entities.append(e)

        # 存储到图谱
        print(f"创建 {len(unique_entities)} 个实体...")
        self.neo4j.create_entities(unique_entities)

        print(f"创建 {len(all_relationships)} 个关系...")
        self.neo4j.create_relationships(all_relationships)

        # 链接文档和实体
        print("链接文档和实体...")
        for chunk_id, entity_ids in chunk_entity_map.items():
            self.neo4j.link_document_entities(doc_id, entity_ids, [chunk_id])

        return True


if __name__ == "__main__":
    # 测试代码
    print("=" * 60)
    print("知识图谱测试")
    print("=" * 60)

    # 创建客户端
    neo4j = Neo4jClient()
    builder = GraphBuilder(neo4j)

    # 测试数据
    test_chunks = [
        {
            "id": "chunk_1",
            "content": "深圳市建设工程计价费率标准规定了企业管理费的计算方法",
        },
        {
            "id": "chunk_2",
            "content": "根据 HJ2023 标准，企业管理费包括管理人员工资和办公费",
        },
        {
            "id": "chunk_3",
            "content": "分部分项工程费由人工费、材料费、机械费组成",
        },
    ]

    # 构建图谱
    print("\n1. 从文档构建图谱...")
    builder.build_from_document("sz_flbz_2023", test_chunks)

    # 实体搜索
    print("\n2. 搜索实体...")
    entities = neo4j.search_entities("费", top_k=10)
    print(f"找到 {len(entities)} 个实体:")
    for e in entities:
        print(f"  - {e.name} ({e.entity_type})")

    # 实体扩展
    print("\n3. 实体扩展...")
    docs = neo4j.expand_entities(["企业管理费"], depth=2, top_k=5)
    print(f"找到 {len(docs)} 个相关文档")

    # 统计
    print("\n4. 图谱统计...")
    stats = neo4j.get_stats()
    print(f"实体数: {stats.get('entities', 0)}")
    print(f"关系数: {stats.get('relationships', 0)}")
    print(f"文档数: {stats.get('documents', 0)}")

    neo4j.close()
