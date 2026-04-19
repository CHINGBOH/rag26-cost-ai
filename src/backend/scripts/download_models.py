#!/usr/bin/env python3
"""下载 Embedding 和 Rerank 模型"""

import os

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"  # 使用国内镜像

print("开始下载模型...")
print("=" * 60)

# 下载 Embedding 模型
print("\n1. 下载 BAAI/bge-m3 (Embedding 模型)...")
print("   约 2GB，请耐心等待...")

try:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("BAAI/bge-m3", cache_folder="/home/l/models")
    print("   ✓ BAAI/bge-m3 下载完成")
    print(f"   模型路径: {model.get_sentence_embedding_dimension()}D")
except Exception as e:
    print(f"   ✗ 下载失败: {e}")

# 下载 Rerank 模型
print("\n2. 下载 BAAI/bge-reranker-large (Rerank 模型)...")
print("   约 1.5GB，请耐心等待...")

try:
    from transformers import AutoTokenizer, AutoModelForSequenceClassification

    tokenizer = AutoTokenizer.from_pretrained(
        "BAAI/bge-reranker-large", cache_dir="/home/l/models"
    )
    model = AutoModelForSequenceClassification.from_pretrained(
        "BAAI/bge-reranker-large", cache_dir="/home/l/models"
    )
    print("   ✓ BAAI/bge-reranker-large 下载完成")
except Exception as e:
    print(f"   ✗ 下载失败: {e}")

print("\n" + "=" * 60)
print("模型下载完成!")
print("=" * 60)
