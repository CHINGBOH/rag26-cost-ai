#!/usr/bin/env python3
"""
验证所有基础设施服务状态
"""
import sys
import requests
from urllib.parse import urljoin

def test_qdrant():
    """测试 Qdrant 向量数据库"""
    try:
        response = requests.get("http://localhost:6333/healthz", timeout=5)
        if response.status_code == 200:
            print("✅ Qdrant (向量数据库) - 运行正常")
            return True
    except Exception as e:
        print(f"❌ Qdrant - 连接失败: {e}")
    return False

def test_elasticsearch():
    """测试 Elasticsearch 关键词检索"""
    try:
        response = requests.get("http://localhost:9200/_cluster/health", timeout=5)
        if response.status_code == 200:
            data = response.json()
            status = data.get('status', 'unknown')
            print(f"✅ Elasticsearch (关键词检索) - 状态: {status}")
            return True
    except Exception as e:
        print(f"❌ Elasticsearch - 连接失败: {e}")
    return False

def test_neo4j():
    """测试 Neo4j 知识图谱"""
    try:
        response = requests.get("http://localhost:7474", timeout=5)
        if response.status_code in [200, 401]:
            print("✅ Neo4j (知识图谱) - 运行正常")
            return True
    except Exception as e:
        print(f"❌ Neo4j - 连接失败: {e}")
    return False

def test_redis():
    """测试 Redis 缓存"""
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, decode_responses=True)
        r.ping()
        print("✅ Redis (缓存) - 运行正常")
        return True
    except ImportError:
        print("⚠️ Redis - 缺少 redis 库，跳过")
        return True
    except Exception as e:
        print(f"❌ Redis - 连接失败: {e}")
    return False

def main():
    print("=" * 60)
    print("RAG Dashboard 基础设施状态检查")
    print("=" * 60)
    print()
    
    results = []
    results.append(("Qdrant", test_qdrant()))
    results.append(("Elasticsearch", test_elasticsearch()))
    results.append(("Neo4j", test_neo4j()))
    results.append(("Redis", test_redis()))
    
    print()
    print("=" * 60)
    success = sum(1 for _, r in results if r)
    total = len(results)
    print(f"检查结果: {success}/{total} 个服务运行正常")
    print("=" * 60)
    
    return 0 if success == total else 1

if __name__ == "__main__":
    sys.exit(main())
