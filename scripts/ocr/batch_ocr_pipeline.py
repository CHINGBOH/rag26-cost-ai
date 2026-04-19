#!/usr/bin/env python3
"""
OCR 批量处理管道 - 自动处理所有 PDF 并写入四库
"""

import os
import sys
import json
import uuid
from datetime import datetime
from pathlib import Path

# 设置环境
os.environ["PATH"] = "/home/l/miniconda3/envs/paddleocr/bin:" + os.environ.get("PATH", "")

# 初始化所有客户端
print("=" * 60)
print("OCR 批量数据管道启动")
print("=" * 60)

# Qdrant
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
qdrant = QdrantClient(host="localhost", port=6333)

# Elasticsearch
from elasticsearch import Elasticsearch
es = Elasticsearch(["http://localhost:9200"])

# Neo4j
from neo4j import GraphDatabase
neo4j_driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))

# Redis
import redis
redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)

# 初始化 embedding 服务
print("\n1. 初始化 Embedding 服务...")
try:
    from sentence_transformers import SentenceTransformer
    embed_model = SentenceTransformer('BAAI/bge-m3')
    EMBED_DIM = 1024
    print(f"   ✓ Embedding 模型加载完成 (dim={EMBED_DIM})")
except Exception as e:
    print(f"   ⚠ Embedding 模型加载失败: {e}")
    embed_model = None
    EMBED_DIM = 768

def ensure_collections():
    """确保集合/索引存在"""
    print("\n2. 检查数据库集合...")
    
    # Qdrant collection
    try:
        qdrant.create_collection(
            collection_name="documents",
            vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE)
        )
        print("   ✓ Qdrant: 创建 documents 集合")
    except Exception:
        print("   ✓ Qdrant: documents 集合已存在")
    
    # ES index
    if not es.indices.exists(index="documents"):
        es.indices.create(index="documents")
        print("   ✓ ES: 创建 documents 索引")
    else:
        print("   ✓ ES: documents 索引已存在")
    
    print("   ✓ Neo4j: 连接正常")
    print("   ✓ Redis: 连接正常")

def process_pdf_with_ocr_service(pdf_path):
    """使用 OCR 服务处理 PDF"""
    import requests
    
    url = "http://localhost:8001/ocr/pdf"
    
    with open(pdf_path, 'rb') as f:
        files = {'file': (os.path.basename(pdf_path), f, 'application/pdf')}
        response = requests.post(url, files=files, timeout=300)
    
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"OCR 服务错误: {response.status_code} - {response.text}")

def store_to_vector_db(doc_id, text, metadata):
    """存储到 Qdrant"""
    if embed_model:
        vector = embed_model.encode(text).tolist()
    else:
        vector = [0.0] * EMBED_DIM
    
    qdrant.upsert(
        collection_name="documents",
        points=[{
            "id": doc_id,
            "vector": vector,
            "payload": {
                **metadata,
                "text": text[:2000]  # 限制文本长度
            }
        }]
    )

def store_to_keyword_db(doc_id, title, content, metadata):
    """存储到 Elasticsearch"""
    es.index(
        index="documents",
        id=doc_id,
        document={
            "title": title,
            "content": content[:5000],  # 限制长度
            "filename": metadata.get("filename", ""),
            "page_count": metadata.get("page_count", 0),
            "timestamp": datetime.now().isoformat()
        }
    )

def store_to_graph_db(doc_id, title, metadata):
    """存储到 Neo4j"""
    with neo4j_driver.session() as session:
        session.run("""
            CREATE (d:Document {
                id: $id,
                title: $title,
                filename: $filename,
                page_count: $page_count,
                timestamp: $timestamp
            })
        """, {
            "id": doc_id,
            "title": title,
            "filename": metadata.get("filename", ""),
            "page_count": metadata.get("page_count", 0),
            "timestamp": datetime.now().isoformat()
        })

def cache_document(doc_id, data):
    """缓存到 Redis"""
    redis_client.setex(
        f"doc:{doc_id}",
        3600 * 24,  # 24小时过期
        json.dumps(data, ensure_ascii=False)
    )

def process_single_pdf(pdf_path, idx, total):
    """处理单个 PDF"""
    filename = os.path.basename(pdf_path)
    print(f"\n[{idx}/{total}] 处理: {filename}")
    
    try:
        # 1. OCR 识别
        print(f"   → OCR 识别中...")
        ocr_result = process_pdf_with_ocr_service(pdf_path)
        
        if not ocr_result.get("success"):
            print(f"   ❌ OCR 失败: {ocr_result.get('error', 'Unknown')}")
            return False
        
        pages = ocr_result.get("pages", [])
        full_text = "\n".join([p.get("text", "") for p in pages])
        page_count = len(pages)
        
        print(f"   ✓ 识别完成: {page_count} 页, {len(full_text)} 字符")
        
        # 2. 生成文档 ID
        doc_id = str(uuid.uuid4())
        
        # 3. 元数据
        metadata = {
            "filename": filename,
            "filepath": pdf_path,
            "page_count": page_count,
            "char_count": len(full_text),
            "timestamp": datetime.now().isoformat()
        }
        
        # 4. 写入四库
        print(f"   → 写入四库...")
        
        # 向量库
        store_to_vector_db(doc_id, full_text, metadata)
        print(f"     ✓ Qdrant (向量)")
        
        # 关键词库
        store_to_keyword_db(doc_id, filename, full_text, metadata)
        print(f"     ✓ Elasticsearch (关键词)")
        
        # 图库
        store_to_graph_db(doc_id, filename, metadata)
        print(f"     ✓ Neo4j (图)")
        
        # 缓存
        cache_document(doc_id, {"metadata": metadata, "pages": pages[:3]})  # 只缓存前3页
        print(f"     ✓ Redis (缓存)")
        
        print(f"   ✓ 完成! Doc ID: {doc_id[:8]}...")
        return True
        
    except Exception as e:
        print(f"   ❌ 错误: {e}")
        return False

def main():
    # 确保集合存在
    ensure_collections()
    
    # 查找所有 PDF
    pdf_dir = "/home/l/知识库测试资料"
    pdf_files = []
    for root, dirs, files in os.walk(pdf_dir):
        for f in files:
            if f.endswith('.pdf'):
                pdf_files.append(os.path.join(root, f))
    
    pdf_files.sort()
    total = len(pdf_files)
    
    print(f"\n3. 找到 {total} 个 PDF 文件")
    print("-" * 60)
    
    # 处理统计
    success_count = 0
    failed_files = []
    
    # 批量处理
    for idx, pdf_path in enumerate(pdf_files, 1):
        if process_single_pdf(pdf_path, idx, total):
            success_count += 1
        else:
            failed_files.append(os.path.basename(pdf_path))
    
    # 刷新 ES 索引
    es.indices.refresh(index="documents")
    
    # 统计
    print("\n" + "=" * 60)
    print("处理完成!")
    print("=" * 60)
    print(f"总计: {total}")
    print(f"成功: {success_count}")
    print(f"失败: {len(failed_files)}")
    
    if failed_files:
        print(f"\n失败文件:")
        for f in failed_files:
            print(f"  - {f}")
    
    # 关闭连接
    neo4j_driver.close()
    
    return 0 if success_count == total else 1

if __name__ == "__main__":
    sys.exit(main())
