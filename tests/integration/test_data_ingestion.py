#!/usr/bin/env python3
"""
测试数据接入 - 向四库写入测试数据
"""
import sys
import uuid
from datetime import datetime

def test_qdrant_ingestion():
    """测试 Qdrant 向量写入"""
    try:
        from qdrant_client import QdrantClient
        
        client = QdrantClient(host="localhost", port=6333)
        
        # 创建集合（如果不存在）
        from qdrant_client.models import Distance, VectorParams
        
        collection_name = "test_documents"
        try:
            client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=768, distance=Distance.COSINE)
            )
            print(f"  创建集合: {collection_name}")
        except Exception:
            print(f"  集合已存在: {collection_name}")
        
        # 插入测试向量
        test_id = str(uuid.uuid4())
        client.upsert(
            collection_name=collection_name,
            points=[{
                "id": test_id,
                "vector": [0.1] * 768,  # 测试向量
                "payload": {
                    "text": "测试文档内容",
                    "source": "test",
                    "timestamp": datetime.now().isoformat()
                }
            }]
        )
        
        # 搜索测试 (新版 API)
        from qdrant_client.models import SearchRequest
        results = client.search(
            collection_name=collection_name,
            query_vector=[0.1] * 768,
            limit=1
        )
        
        if results:
            print(f"✅ Qdrant - 向量写入/检索成功 (ID: {test_id[:8]}...)")
            return True
    except Exception as e:
        print(f"❌ Qdrant - 测试失败: {e}")
    return False

def test_elasticsearch_ingestion():
    """测试 ES 文档写入"""
    try:
        from elasticsearch import Elasticsearch
        
        es = Elasticsearch(["http://localhost:9200"])
        
        # 创建索引（如果不存在）
        index_name = "test_documents"
        if not es.indices.exists(index=index_name):
            es.indices.create(index=index_name)
            print(f"  创建索引: {index_name}")
        
        # 插入文档
        doc_id = str(uuid.uuid4())
        es.index(
            index=index_name,
            id=doc_id,
            document={
                "title": "测试文档",
                "content": "这是一篇测试文档内容",
                "keywords": ["测试", "文档"],
                "timestamp": datetime.now().isoformat()
            }
        )
        
        # 刷新索引
        es.indices.refresh(index=index_name)
        
        # 搜索测试
        results = es.search(index=index_name, query={"match": {"content": "测试"}})
        
        if results["hits"]["total"]["value"] > 0:
            print(f"✅ Elasticsearch - 文档写入/检索成功 (ID: {doc_id[:8]}...)")
            return True
    except Exception as e:
        print(f"❌ Elasticsearch - 测试失败: {e}")
    return False

def test_neo4j_ingestion():
    """测试 Neo4j 图数据写入"""
    try:
        from neo4j import GraphDatabase
        
        driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
        
        with driver.session() as session:
            # 创建测试节点
            doc_id = str(uuid.uuid4())
            session.run("""
                CREATE (d:Document {id: $id, title: $title, content: $content, timestamp: $timestamp})
                RETURN d
            """, {
                "id": doc_id,
                "title": "测试文档",
                "content": "图数据库测试内容",
                "timestamp": datetime.now().isoformat()
            })
            
            # 查询测试
            result = session.run("MATCH (d:Document {id: $id}) RETURN d.title", {"id": doc_id})
            record = result.single()
            
            if record:
                print(f"✅ Neo4j - 图数据写入/查询成功 (ID: {doc_id[:8]}...)")
                return True
        
        driver.close()
    except Exception as e:
        print(f"❌ Neo4j - 测试失败: {e}")
    return False

def test_redis_cache():
    """测试 Redis 缓存"""
    try:
        import redis
        
        r = redis.Redis(host='localhost', port=6379, decode_responses=True)
        
        # 写入测试
        test_key = f"test:{uuid.uuid4()}"
        r.set(test_key, "测试数据", ex=3600)
        
        # 读取测试
        value = r.get(test_key)
        
        if value == "测试数据":
            print(f"✅ Redis - 缓存读写成功 (Key: {test_key[:8]}...)")
            return True
    except Exception as e:
        print(f"❌ Redis - 测试失败: {e}")
    return False

def main():
    print("=" * 60)
    print("数据接入测试 - 四库写入验证")
    print("=" * 60)
    print()
    
    results = []
    
    print("1. Qdrant (向量数据库)")
    results.append(("Qdrant", test_qdrant_ingestion()))
    print()
    
    print("2. Elasticsearch (关键词检索)")
    results.append(("Elasticsearch", test_elasticsearch_ingestion()))
    print()
    
    print("3. Neo4j (知识图谱)")
    results.append(("Neo4j", test_neo4j_ingestion()))
    print()
    
    print("4. Redis (缓存)")
    results.append(("Redis", test_redis_cache()))
    print()
    
    print("=" * 60)
    success = sum(1 for _, r in results if r)
    total = len(results)
    print(f"测试结果: {success}/{total} 个数据库写入正常")
    print("=" * 60)
    
    return 0 if success == total else 1

if __name__ == "__main__":
    sys.exit(main())
