"""
四库工具 - LangChain/LlamaIndex Agent Tools
=======================================

初步实现，供Agent调用。
"""

import os
import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

# 先不实际连接数据库，提供框架接口
# 实际使用时会连接真实的四库

@dataclass
class ToolResult:
    success: bool
    content: str
    metadata: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class VectorSearchTool:
    """语义检索工具 (Qdrant)"""
    
    name = "vector_search"
    description = """
    语义相似度检索，适合'什么意思'、'概念是什么'类问题。
    通过向量相似度找到语义相关的文档。
    """
    
    def __init__(self, qdrant_client=None):
        self.qdrant_client = qdrant_client
    
    def execute(self, query: str, top_k: int = 10) -> ToolResult:
        """执行语义检索"""
        # 初步框架，实际会连接Qdrant
        mock_results = [
            {
                "chunk_id": "mock_doc_001_chunk_001",
                "doc_id": "mock_doc_001",
                "page_number": 5,
                "source_db": "qdrant",
                "content": "赶工措施费是指为了加快工程进度而额外支出的费用...",
                "score": 0.92
            }
        ]
        
        return ToolResult(
            success=True,
            content=json.dumps(mock_results, ensure_ascii=False, indent=2),
            metadata={
                "count": len(mock_results),
                "source": "qdrant",
                "top_k": top_k
            }
        )


class KeywordSearchTool:
    """关键词检索工具 (Elasticsearch)"""
    
    name = "keyword_search"
    description = """
    关键词精确匹配，适合查找特定术语、数字或明确的关键词。
    通过BM25打分找到关键词相关文档。
    """
    
    def __init__(self, es_client=None):
        self.es_client = es_client
    
    def execute(self, query: str, top_k: int = 10) -> ToolResult:
        """执行关键词检索"""
        mock_results = [
            {
                "chunk_id": "mock_doc_001_chunk_010",
                "doc_id": "mock_doc_001",
                "page_number": 12,
                "source_db": "elasticsearch",
                "content": "深圳市建设工程计价费率标准...赶工措施费系数为0.8...",
                "score": 15.2
            }
        ]
        
        return ToolResult(
            success=True,
            content=json.dumps(mock_results, ensure_ascii=False, indent=2),
            metadata={
                "count": len(mock_results),
                "source": "elasticsearch",
                "top_k": top_k
            }
        )


class KnowledgeGraphSearchTool:
    """知识图谱检索工具 (Neo4j)"""
    
    name = "knowledge_graph_search"
    description = """
    知识图谱关系查询，适合查找实体间的关联关系。
    通过图遍历找到相关实体和文档。
    """
    
    def __init__(self, neo4j_driver=None):
        self.neo4j_driver = neo4j_driver
    
    def execute(self, entities: List[str], top_k: int = 10) -> ToolResult:
        """执行知识图谱检索"""
        mock_results = [
            {
                "chunk_id": "mock_doc_001_chunk_005",
                "doc_id": "mock_doc_001",
                "page_number": 8,
                "source_db": "neo4j",
                "content": "赶工措施费属于费率标准范畴...",
                "entities": ["赶工措施费", "费率标准"],
                "relation_count": 3
            }
        ]
        
        return ToolResult(
            success=True,
            content=json.dumps(mock_results, ensure_ascii=False, indent=2),
            metadata={
                "count": len(mock_results),
                "source": "neo4j",
                "top_k": top_k,
                "queried_entities": entities
            }
        )


class StructuredQueryTool:
    """结构化查询工具 (PostgreSQL)"""
    
    name = "structured_query"
    description = """
    结构化SQL查询，适合查找数值、费率、标准等精确条件的数据。
    可以通过SQL条件精确筛选数据。
    """
    
    def __init__(self, pg_pool=None):
        self.pg_pool = pg_pool
    
    def execute(
        self,
        chunk_ids: Optional[List[str]] = None,
        conditions: Optional[List[Dict[str, Any]]] = None,
        top_k: int = 10
    ) -> ToolResult:
        """执行结构化查询"""
        mock_results = [
            {
                "chunk_id": "mock_doc_001_chunk_012",
                "doc_id": "mock_doc_001",
                "page_number": 15,
                "source_db": "postgresql",
                "content": "深圳市房建工程赶工措施费费率表...费率: 0.8...",
                "metadata": {
                    "region": "深圳",
                    "project_type": "房建工程",
                    "fee_rate": 0.8
                }
            }
        ]
        
        return ToolResult(
            success=True,
            content=json.dumps(mock_results, ensure_ascii=False, indent=2),
            metadata={
                "count": len(mock_results),
                "source": "postgresql",
                "top_k": top_k,
                "used_chunk_ids": chunk_ids,
                "used_conditions": conditions
            }
        )


class CalculatorTool:
    """计算器工具"""
    
    name = "calculator"
    description = """
    执行数学计算，支持加减乘除和简单公式。
    适用于费率计算、数值汇总等场景。
    """
    
    def execute(self, expression: str) -> ToolResult:
        """执行计算"""
        try:
            # 简单计算器，实际可以更复杂
            result = eval(expression)
            
            steps = [
                f"解析表达式: {expression}",
                "执行计算",
                f"结果: {result}"
            ]
            
            return ToolResult(
                success=True,
                content=f"计算结果: {result}",
                metadata={
                    "expression": expression,
                    "result": result,
                    "steps": steps
                }
            )
        except Exception as e:
            return ToolResult(
                success=False,
                content="计算失败",
                error=str(e)
            )


# 工具集合
class FourDatabaseTools:
    """四库工具集合"""
    
    def __init__(
        self,
        qdrant_client=None,
        es_client=None,
        neo4j_driver=None,
        pg_pool=None
    ):
        self.vector = VectorSearchTool(qdrant_client)
        self.keyword = KeywordSearchTool(es_client)
        self.graph = KnowledgeGraphSearchTool(neo4j_driver)
        self.structured = StructuredQueryTool(pg_pool)
        self.calculator = CalculatorTool()
    
    def get_all_tools(self) -> List:
        """获取所有工具列表（供LangChain/LlamaIndex使用）"""
        return [
            self.vector,
            self.keyword,
            self.graph,
            self.structured,
            self.calculator
        ]


# 便捷函数
def create_four_db_tools(
    qdrant_client=None,
    es_client=None,
    neo4j_driver=None,
    pg_pool=None
) -> FourDatabaseTools:
    """创建四库工具集合"""
    return FourDatabaseTools(
        qdrant_client=qdrant_client,
        es_client=es_client,
        neo4j_driver=neo4j_driver,
        pg_pool=pg_pool
    )
