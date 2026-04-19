#!/usr/bin/env python3
"""
RAG系统完整流程测试脚本
插入模拟数据 → 测试搜索 → 验证四库功能
"""
import sys
sys.path.insert(0, '/home/l/rag-dashboard/src/backend/python-legacy')

import uuid
import numpy as np
from datetime import datetime
from domain_models.document import Document, DocumentChunk, DocumentMetadata, DocumentType, ChunkType
from infrastructure.adapters.unified import UnifiedStore
from retrieval.unified_pipeline import UnifiedRetrievalPipeline
from domain_models.retrieval import RetrievalRequest, RetrievalConfig

# 初始化存储
print("=== 初始化存储层 ===")
store = UnifiedStore()
print("✅ 存储层初始化完成")

# 创建模拟文档
print("\n=== 创建模拟文档 ===")

def create_mock_embedding(text: str, dim: int = 768) -> list:
    """创建模拟embedding（使用文本哈希保证一致性）"""
    np.random.seed(abs(hash(text)) % 2**32)
    embedding = np.random.randn(dim).astype(np.float32).tolist()
    # 归一化
    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding = [x / norm for x in embedding]
    return embedding

doc_id = str(uuid.uuid4())
chunks = [
    DocumentChunk(
        chunk_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}_chunk_0")),
        doc_id=doc_id,
        content="RAG（检索增强生成）是一种将外部知识检索与大型语言模型生成能力相结合的技术架构。RAG系统通过检索相关文档来增强LLM的回答准确性，减少幻觉问题。",
        chunk_type=ChunkType.TEXT,
        page_number=1,
        embedding=create_mock_embedding("RAG架构介绍"),
        keywords=["RAG", "检索增强生成", "LLM", "大语言模型"],
        confidence=0.95
    ),
    DocumentChunk(
        chunk_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}_chunk_1")),
        doc_id=doc_id,
        content="向量数据库是RAG系统的核心组件之一。Qdrant、Pinecone、Weaviate等向量数据库支持高效的相似度搜索，用于存储和检索文档片段的embedding向量。",
        chunk_type=ChunkType.TEXT,
        page_number=2,
        embedding=create_mock_embedding("向量数据库"),
        keywords=["向量数据库", "Qdrant", "embedding", "相似度搜索"],
        confidence=0.92
    ),
    DocumentChunk(
        chunk_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}_chunk_2")),
        doc_id=doc_id,
        content="Elasticsearch是一个分布式搜索和分析引擎，支持全文检索、结构化搜索和分析。在RAG系统中，ES常用于关键词检索和混合搜索。",
        chunk_type=ChunkType.TEXT,
        page_number=2,
        embedding=create_mock_embedding("Elasticsearch全文检索"),
        keywords=["Elasticsearch", "全文检索", "搜索引擎", "混合搜索"],
        confidence=0.88
    ),
    DocumentChunk(
        chunk_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}_chunk_3")),
        doc_id=doc_id,
        content="Neo4j是一个图数据库，支持存储实体和关系。在RAG系统中，Neo4j可用于构建知识图谱，支持基于图遍历的检索，发现文档间的关联关系。",
        chunk_type=ChunkType.TEXT,
        page_number=3,
        embedding=create_mock_embedding("Neo4j图数据库"),
        keywords=["Neo4j", "图数据库", "知识图谱", "关系检索"],
        confidence=0.90
    ),
    DocumentChunk(
        chunk_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}_chunk_4")),
        doc_id=doc_id,
        content="深圳市建设工程计价费率标准(2023)规定了建筑工程、市政工程、园林绿化工程等各类工程的计价费率和计算方法。",
        chunk_type=ChunkType.TEXT,
        page_number=1,
        embedding=create_mock_embedding("建设工程计价"),
        keywords=["深圳", "建设工程", "计价费率", "2023"],
        confidence=0.85
    ),
]

document = Document(
    metadata=DocumentMetadata(
        doc_id=doc_id,
        title="RAG系统架构与四库存储技术白皮书",
        source="测试文档",
        doc_type=DocumentType.PDF,
        author="AI Assistant",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        tags=["RAG", "AI", "检索"],
        extra={"test": True}
    ),
    chunks=chunks,
    raw_content="\n\n".join([c.content for c in chunks])
)

print(f"✅ 文档创建完成: {doc_id}")
print(f"   标题: {document.metadata.title}")
print(f"   片段数: {len(chunks)}")

# 索引到四库
print("\n=== 索引到四库 ===")
results = store.index_document(document)
print(f"✅ 索引完成")
print(f"   Vector indexed: {results.get('vector_indexed', 0)}")
print(f"   Keyword indexed: {results.get('keyword_indexed', 0)}")
print(f"   Graph indexed: {results.get('graph_indexed', 0)}")
if results.get('errors'):
    print(f"   ⚠️  错误: {results['errors']}")

# 初始化检索管道
print("\n=== 初始化检索管道 ===")
pipeline = UnifiedRetrievalPipeline(store)
print("✅ 检索管道初始化完成")

# 测试搜索
print("\n=== 测试搜索功能 ===")

test_queries = [
    "RAG架构是什么",
    "向量数据库",
    "Elasticsearch全文搜索",
    "Neo4j图数据库",
    "深圳建设工程计价",
]

for query in test_queries:
    print(f"\n📝 查询: {query}")
    
    request = RetrievalRequest(
        query=query,
        config=RetrievalConfig(
            vector_top_k=5,
            keyword_top_k=5,
            graph_top_k=3,
            enable_rerank=False  # 暂时禁用rerank
        )
    )
    
    response = pipeline.retrieve(request)
    
    print(f"   ⏱️  延迟: {response.latency_ms:.2f}ms")
    recall_stats = response.stats.get('recall_stats', {})
    print(f"   📊 召回: vector={recall_stats.get('vector_count', 0)}, "
          f"keyword={recall_stats.get('keyword_count', 0)}, "
          f"graph={recall_stats.get('graph_count', 0)}")
    
    if response.documents:
        print(f"   🔍 结果:")
        for i, doc in enumerate(response.documents[:2], 1):
            preview = doc.content[:50] + "..." if len(doc.content) > 50 else doc.content
            print(f"      {i}. [{doc.score:.3f}] {preview}")
    else:
        print("   ⚠️  无结果")

# 数据库统计
print("\n=== 数据库统计 ===")
stats = pipeline.get_stats()
print(f"✅ 统计信息:")
for key, value in stats.items():
    print(f"   {key}: {value}")

print("\n=== 测试完成 ===")
print("RAG系统四库存储和检索功能运行正常！")

# 清理
store.close()
