#!/usr/bin/env python3
"""
RAG Dashboard API测试脚本
测试后端服务的健康状态和基本功能
"""

import requests
import json
import sys
import time


def test_health():
    """测试健康检查接口"""
    print("\n" + "=" * 60)
    print("测试1: 健康检查")
    print("=" * 60)

    try:
        response = requests.get("http://localhost:8000/health", timeout=5)
        data = response.json()

        print(f"✅ 状态: {data.get('status', 'unknown')}")
        print(f"✅ 时间戳: {data.get('timestamp')}")

        services = data.get("services", {})
        if services:
            print("\n服务状态:")
            for service, status in services.items():
                icon = "✅" if status == "healthy" else "⚠️"
                print(f"  {icon} {service}: {status}")

        return True
    except Exception as e:
        print(f"❌ 健康检查失败: {e}")
        return False


def test_search():
    """测试搜索接口"""
    print("\n" + "=" * 60)
    print("测试2: 搜索功能")
    print("=" * 60)

    try:
        response = requests.post(
            "http://localhost:8000/api/search",
            json={"query": "企业管理费", "top_k": 3, "mode": "hybrid"},
            timeout=10,
        )
        data = response.json()

        if data.get("status") == "success":
            results = data["data"]["results"]
            print(f"✅ 搜索成功，返回 {len(results)} 条结果")
            print(f"✅ 查询耗时: {data['data'].get('latency_ms', 'N/A')}ms")

            if results:
                print("\n前3条结果:")
                for i, result in enumerate(results[:3], 1):
                    content = result.get("content", "")[:50]
                    print(f"  {i}. [{result.get('score', 0):.3f}] {content}...")
            return True
        else:
            print(f"⚠️ 搜索返回非成功状态: {data.get('message')}")
            return False
    except Exception as e:
        print(f"❌ 搜索失败: {e}")
        return False


def test_decompose():
    """测试查询分解接口"""
    print("\n" + "=" * 60)
    print("测试3: 查询分解")
    print("=" * 60)

    try:
        response = requests.post(
            "http://localhost:8000/api/v1/decompose", json={"query": "如何实现RAG系统"}, timeout=5
        )
        data = response.json()

        if "sub_queries" in data:
            sub_queries = data["sub_queries"]
            print(f"✅ 查询分解成功，生成 {len(sub_queries)} 个子查询")

            print("\n子查询列表:")
            for i, sq in enumerate(sub_queries, 1):
                print(f"  {i}. [{sq.get('targetDB')}] {sq.get('query')}")
            return True
        else:
            print(f"⚠️ 查询分解返回异常")
            return False
    except Exception as e:
        print(f"❌ 查询分解失败: {e}")
        return False


def test_evaluate():
    """测试评估接口"""
    print("\n" + "=" * 60)
    print("测试4: 检索评估")
    print("=" * 60)

    try:
        response = requests.post(
            "http://localhost:8000/api/v1/evaluate",
            json={
                "query": "测试查询",
                "retrieved_chunks": [
                    {"id": "1", "content": "内容1", "source": "doc1", "score": 0.9},
                    {"id": "2", "content": "内容2", "source": "doc2", "score": 0.8},
                ],
                "generated_answer": "这是生成的答案",
                "history_rounds": 0,
            },
            timeout=5,
        )
        data = response.json()

        if "confidence" in data:
            print(f"✅ 评估成功")
            print(f"  - 置信度: {data.get('confidence', 0):.2%}")
            print(f"  - 完整性: {data.get('completeness', 0):.2%}")
            print(f"  - 一致性: {data.get('consistency', 0):.2%}")
            print(f"  - 信息增益: {data.get('information_gain', 0):.2%}")
            return True
        else:
            print(f"⚠️ 评估返回异常")
            return False
    except Exception as e:
        print(f"❌ 评估失败: {e}")
        return False


def test_rerank():
    """测试重排序接口"""
    print("\n" + "=" * 60)
    print("测试5: 重排序")
    print("=" * 60)

    try:
        response = requests.post(
            "http://localhost:8000/api/v1/rerank",
            json={
                "query": "测试查询",
                "documents": [
                    {"id": "1", "content": "文档1内容示例"},
                    {"id": "2", "content": "文档2内容示例"},
                    {"id": "3", "content": "文档3内容示例"},
                ],
                "top_k": 3,
            },
            timeout=5,
        )
        data = response.json()

        if "results" in data:
            results = data["results"]
            print(f"✅ 重排序成功，返回 {len(results)} 条结果")
            return True
        else:
            print(f"⚠️ 重排序返回异常")
            return False
    except Exception as e:
        print(f"❌ 重排序失败: {e}")
        return False


def main():
    print("\n" + "=" * 60)
    print("RAG Dashboard API 测试")
    print("=" * 60)
    print(f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    results = []

    # 执行所有测试
    results.append(("健康检查", test_health()))
    results.append(("搜索功能", test_search()))
    results.append(("查询分解", test_decompose()))
    results.append(("检索评估", test_evaluate()))
    results.append(("重排序", test_rerank()))

    # 汇总结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        icon = "✅" if result else "❌"
        print(f"{icon} {name}")

    print(f"\n总计: {passed}/{total} 通过")

    if passed == total:
        print("\n🎉 所有测试通过！")
        return 0
    else:
        print(f"\n⚠️ {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
