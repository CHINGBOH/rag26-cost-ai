#!/usr/bin/env python3
"""
下载 Embedding 和 Rerank 模型
"""
import os
import sys

# 添加到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def download_models():
    print("=" * 60)
    print("下载 RAG 模型")
    print("=" * 60)
    
    # 使用conda环境中的paddleocr
    import subprocess
    python_path = "/home/l/miniconda3/envs/paddleocr/bin/python"
    
    # 创建下载脚本
    script = '''
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'  # 使用镜像加速

print("\\n1. 下载 Embedding 模型 (BAAI/bge-m3)...")
try:
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("BAAI/bge-m3", cache_folder="./models")
    print("✓ Embedding 模型下载完成")
except Exception as e:
    print(f"✗ Embedding 模型下载失败: {e}")

print("\\n2. 下载 Rerank 模型 (BAAI/bge-reranker-large)...")
try:
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-reranker-large", cache_dir="./models")
    model = AutoModelForSequenceClassification.from_pretrained("BAAI/bge-reranker-large", cache_dir="./models")
    print("✓ Rerank 模型下载完成")
except Exception as e:
    print(f"✗ Rerank 模型下载失败: {e}")

print("\\n模型下载完成！")
'''
    
    # 写入临时脚本
    with open('/tmp/download_models_script.py', 'w') as f:
        f.write(script)
    
    # 执行
    result = subprocess.run([python_path, '/tmp/download_models_script.py'], 
                          capture_output=False, text=True)
    
    return result.returncode == 0

if __name__ == "__main__":
    download_models()
