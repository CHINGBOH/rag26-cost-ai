#!/usr/bin/env python3
"""
全流程系统测试
"""

import sys
import json
import requests
from datetime import datetime

sys.path.insert(0, "/home/l/rag-dashboard/src/backend/python-legacy")

from domain_models.document import (
    Document,
    DocumentChunk,
    DocumentMetadata,
    DocumentType,
    ChunkType,
)
from infrastructure.adapters.unified import UnifiedStore
from retrieval.unified_pipeline import UnifiedRetrievalPipeline
from domain_models.retrieval import RetrievalRequest, RetrievalConfig


def test_health():
    """测试健康检查"""
    print("\n[1] 健康检查")
    try:
        response = requests.get("http://localhost:8000/health", timeout=5)
        data = response.json()
        print(f"  状态: {data.get('status')}")
        for service, status in data.get("services", {}).items():
            icon = "✅" if status == "healthy" else "❌"
            print(f"    {icon} {service}: {status}")
        return data.get("status") in ["ok", "degraded"]
    except Exception as e:
        print(f"  ❌ 健康检查失败: {e}")
        return False


def test_document_indexing():
    """测试文档索引"""
    print("\n[2] 文档索引测试")
    try:
        store = UnifiedStore()

        # 创建测试文档
        doc = Document(
            metadata=DocumentMetadata(
                doc_id="test_doc_001",
                title="测试文档",
                source="test",
                doc_type=DocumentType.TEXT,
                total_pages=1,
            ),
            chunks=[
                DocumentChunk(
                    chunk_id="chunk_001",
                    doc_id="test_doc_001",
                    content="这是一个测试文档，用于验证四库联动功能。",
                    chunk_type=ChunkType.TEXT,
                    page_number=1,
                    embedding=[0.1] * 768,
                    keywords=["测试", "文档", "四库"],
                ),
                DocumentChunk(
                    chunk_id="chunk_002",
                    doc_id="test_doc_001",
                    content="企业管理费的计算公式是 E = (A + C × 0.1) × a",
                    chunk_type=ChunkType.TEXT,
                    page_number=1,
                    embedding=[0.2] * 768,
                    keywords=["企业管理费", "计算公式"],
                ),
            ],
        )

        result = store.index_document(doc)
        print(f"  ✅ 文档索引完成")
        print(f"    - 文档ID: {result['doc_id']}")
        print(f"    - 块数量: {result['chunks_indexed']}")
        if result.get("errors"):
            print(f"    - 警告: {len(result['errors'])} 个错误")

        return True
    except Exception as e:
        print(f"  ❌ 文档索引失败: {e}")
        return False


def test_search():
    """测试检索功能"""
    print("\n[3] 检索功能测试")
    try:
        response = requests.post(
            "http://localhost:8000/api/search",
            json={"query": "企业管理费", "top_k": 5, "mode": "hybrid"},
            timeout=10,
        )

        data = response.json()
        if data.get("status") == "success":
            results = data["data"]["results"]
            print(f"  ✅ 检索完成")
            print(f"    - 找到 {len(results)} 个结果")
            print(f"    - 延迟: {data['data']['latency_ms']:.2f}ms")

            for i, r in enumerate(results[:3]):
                print(f"    [{i + 1}] {r['content'][:50]}... (score: {r['score']:.4f})")

            return True
        else:
            print(f"  ⚠️ 检索返回错误: {data.get('message')}")
            return False
    except Exception as e:
        print(f"  ❌ 检索失败: {e}")
        return False


def test_stats():
    """测试统计接口"""
    print("\n[4] 统计接口测试")
    try:
        response = requests.get("http://localhost:8000/api/stats", timeout=5)
        data = response.json()

        if data.get("status") == "success":
            stats = data["data"]
            print(f"  ✅ 统计信息")
            print(f"    - 总请求数: {stats.get('total_requests', 0)}")
            print(f"    - 平均延迟: {stats.get('average_latency_ms', 0):.2f}ms")
            return True
        return False
    except Exception as e:
        print(f"  ❌ 统计接口失败: {e}")
        return False


def test_ocr_service():
    """测试 OCR 服务"""
    print("\n[5] OCR 服务测试")
    try:
        response = requests.get("http://localhost:8001/health", timeout=5)
        data = response.json()

        if data.get("status") == "ok":
            print(f"  ✅ OCR 服务正常")
            print(f"    - PaddleOCR: {data.get('paddle_available')}")
            print(f"    - OCR 初始化: {data.get('ocr_initialized')}")
            return True
        return False
    except Exception as e:
        print(f"  ❌ OCR 服务检查失败: {e}")
        return False


def main():
    print("=" * 60)
    print("RAG Dashboard 全流程系统测试")
    print("=" * 60)

    results = []

    # 运行所有测试
    results.append(("健康检查", test_health()))
    results.append(("文档索引", test_document_indexing()))
    results.append(("检索功能", test_search()))
    results.append(("统计接口", test_stats()))
    results.append(("OCR 服务", test_ocr_service()))

    # 汇总
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        icon = "✅" if result else "❌"
        print(f"  {icon} {name}")

    print(f"\n总计: {passed}/{total} 项通过")

    if passed == total:
        print("\n🎉 所有测试通过！系统运行正常。")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 项测试失败，请检查日志。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
