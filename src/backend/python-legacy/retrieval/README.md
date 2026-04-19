# 召回精排架构

## 模块说明

本目录实现了四库联动的召回精排架构，支持多路召回 + Cross-Encoder 精排 + 分数融合。

## 核心组件

### 1. multi_stage_retriever.py
多阶段召回器，整合所有召回和精排逻辑。

```python
from multi_stage_retriever import MultiStageRetriever

retriever = MultiStageRetriever(
    vector_retriever=...,
    keyword_retriever=...,
    graph_retriever=...,
    reranker=...,
    fusion_scorer=...
)

result = retriever.retrieve("查询文本", top_k=10)
```

### 2. vector_store.py
向量存储，基于 Qdrant 实现余弦相似度检索。

```python
from vector_store import QdrantClient, EmbeddingService

qdrant = QdrantClient(host="localhost", port=6333)
embedding = EmbeddingService(model_name="BAAI/bge-m3")
```

### 3. keyword_store.py
关键词存储，基于 Elasticsearch 实现 BM25 检索。

```python
from keyword_store import ElasticsearchClient

es = ElasticsearchClient(hosts=["http://localhost:9200"])
```

### 4. graph_store.py
知识图谱存储，基于 Neo4j 实现实体扩展检索。

```python
from graph_store import Neo4jClient, GraphBuilder

neo4j = Neo4jClient(uri="bolt://localhost:7687")
builder = GraphBuilder(neo4j)
```

### 5. context_enhancer.py
上下文增强，为检索结果添加上下文信息。

```python
from context_enhancer import ContextEnhancer, ContextStrategy

enhancer = ContextEnhancer()
result = enhancer.enhance(
    doc_id="...",
    chunk_id="...",
    content="...",
    strategy=ContextStrategy.SURROUNDING
)
```

### 6. rag_pipeline.py
端到端 RAG Pipeline，整合所有组件。

```python
from rag_pipeline import RAGPipeline

pipeline = RAGPipeline()
pipeline.index_document("doc_id", chunks)
response = pipeline.query("查询文本", top_k=10)
```

## 架构流程

```
用户查询
    │
    ▼
┌─────────────────┐
│ 1. 查询理解      │ ◄── 意图分类、生成嵌入
└────────┬────────┘
         │
    ┌────┴────┬────────┐
    │         │        │
    ▼         ▼        ▼
┌────────┐ ┌────────┐ ┌────────┐
│向量召回 │ │关键词召回│ │图谱召回 │
│top-30  │ │top-20  │ │top-10  │
│(余弦)  │ │(BM25)  │ │(实体扩展)│
└────┬───┘ └────┬───┘ └────┬───┘
     │          │          │
     └────┬─────┴──────────┘
          │
          ▼
┌─────────────────┐
│ 2. 候选池合并    │ ◄── 去重、粗排
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 3. 精排 (Rerank) │ ◄── Cross-Encoder
│                 │     BAAI/bge-reranker-large
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 4. 分数融合      │ ◄── 加权融合
│                 │     0.4精排 + 0.3向量 + 0.2关键词 + 0.05图谱 + 0.05时间
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 5. 上下文增强    │ ◄── 前后段落、实体链接
└────────┬────────┘
         │
         ▼
    返回 top-10
```

## 分数融合公式

```python
final_score = (
    0.4 × sigmoid(rerank_score) +      # 精排分数
    0.3 × (vector_score + 1) / 2 +     # 向量相似度
    0.2 × min(bm25_score / 10, 1.0) +  # 关键词分数
    0.05 × graph_score +               # 图谱关联度
    0.05 × time_decay(date)            # 时间衰减
)
```

## 配置说明

### 环境变量

```bash
# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=6333

# Elasticsearch
ES_HOSTS=http://localhost:9200

# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
```

### 模型配置

```python
# Embedding 模型
EMBEDDING_MODEL=BAAI/bge-m3  # 或 BAAI/bge-large-zh

# Rerank 模型
RERANK_MODEL=BAAI/bge-reranker-large
```

## 使用示例

### 基本检索

```python
from rag_pipeline import RAGPipeline

pipeline = RAGPipeline()

# 索引文档
chunks = [
    {"content": "...", "doc_id": "doc1", "page": 1},
    # ...
]
pipeline.index_document("doc1", chunks)

# 查询
response = pipeline.query("企业管理费怎么计算", top_k=5)

for doc in response.documents:
    print(f"{doc.final_score:.4f}: {doc.content}")
```

### 自定义权重

```python
from multi_stage_retriever import FusionScorer

fusion_scorer = FusionScorer(
    rerank_weight=0.5,    # 提高精排权重
    vector_weight=0.3,
    keyword_weight=0.15,
    graph_weight=0.05,
    time_weight=0.0       # 忽略时间
)

retriever = MultiStageRetriever(fusion_scorer=fusion_scorer)
```

### 上下文增强策略

```python
from context_enhancer import ContextStrategy

response = pipeline.query(
    "查询文本",
    context_strategy=ContextStrategy.FULL  # 全部增强
)
```

## 性能优化

### 1. 批量处理

```python
# 批量索引
pipeline.index_document(doc_id, chunks, batch_size=64)

# 批量检索（并行）
results = retriever.retrieve_batch(queries, top_k=10)
```

### 2. 缓存

```python
# 嵌入缓存
embedding.encode.cache_clear()

# 查询缓存
retriever.retrieve = functools.lru_cache(maxsize=1000)(retriever.retrieve)
```

### 3. 近似检索

```python
# HNSW 索引（Qdrant 默认使用）
qdrant = QdrantClient(
    hnsw_ef=128,  # 搜索时探索因子
    hnsw_m=16     # 每个节点的最大连接数
)
```

## 测试

```bash
# 运行测试
python rag_pipeline.py

# 单独测试各模块
python multi_stage_retriever.py
python vector_store.py
python keyword_store.py
python graph_store.py
python context_enhancer.py
```
