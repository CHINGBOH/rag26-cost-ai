#!/usr/bin/env python3
"""
测试IK中文分词器
"""

from elasticsearch import Elasticsearch
import json

es = Elasticsearch(["http://localhost:9200"])

# 测试文本
test_texts = [
    "人工智能是计算机科学的一个分支",
    "自然语言处理是人工智能的重要领域",
    "深度学习模型需要大量数据进行训练",
    "北京欢迎你，这是一个测试句子",
]

print("=== 测试IK中文分词器 ===")

# 检查索引是否存在，如果不存在则创建
if not es.indices.exists(index="test_ik"):
    print("创建测试索引...")
    es.indices.create(
        index="test_ik",
        body={
            "mappings": {
                "properties": {
                    "content": {
                        "type": "text",
                        "analyzer": "ik_max_word",
                        "search_analyzer": "ik_smart",
                    }
                }
            }
        },
    )
    print("测试索引创建成功")

# 测试标准分析器
print("\n1. 标准分析器分词结果:")
for text in test_texts:
    tokens = es.indices.analyze(body={"text": text, "analyzer": "standard"})
    token_list = [token["token"] for token in tokens["tokens"]]
    print(f"   '{text}' → {token_list}")

# 测试IK分析器
print("\n2. IK分析器分词结果 (ik_max_word):")
for text in test_texts:
    tokens = es.indices.analyze(body={"text": text, "analyzer": "ik_max_word"})
    token_list = [token["token"] for token in tokens["tokens"]]
    print(f"   '{text}' → {token_list}")

# 测试IK智能分词
print("\n3. IK分析器分词结果 (ik_smart):")
for text in test_texts:
    tokens = es.indices.analyze(body={"text": text, "analyzer": "ik_smart"})
    token_list = [token["token"] for token in tokens["tokens"]]
    print(f"   '{text}' → {token_list}")

# 测试索引和搜索
print("\n4. 索引和搜索测试...")
# 索引一些文档
docs = [
    {"id": 1, "content": "人工智能是未来科技发展的方向"},
    {"id": 2, "content": "机器学习需要大量数据进行模型训练"},
    {"id": 3, "content": "深度学习在图像识别领域有广泛应用"},
]

for doc in docs:
    es.index(index="test_ik", id=doc["id"], body={"content": doc["content"]})

es.indices.refresh(index="test_ik")

# 搜索测试
search_queries = ["人工智能", "机器 学习", "深度学习 图像"]

for query in search_queries:
    result = es.search(index="test_ik", body={"query": {"match": {"content": query}}})
    print(f"  搜索 '{query}': 找到 {result['hits']['total']['value']} 个结果")

# 清理测试索引
es.indices.delete(index="test_ik", ignore=[404])
print("\n测试完成，清理测试索引")

print("\n=== 验证RAG系统索引映射 ===")
# 检查documents索引映射
if es.indices.exists(index="documents"):
    mapping = es.indices.get_mapping(index="documents")
    print("当前documents索引映射:")
    print(json.dumps(mapping, indent=2, ensure_ascii=False))
else:
    print("documents索引不存在（正常，将在系统启动时创建）")

print("\n=== 测试完成 ===")
