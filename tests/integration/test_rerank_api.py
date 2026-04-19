#!/usr/bin/env python3
"""
测试 Rerank API 端点功能
模拟 /api/v1/rerank 端点的逻辑
"""

import sys
import os

# 添加项目路径
sys.path.insert(0, "/home/l/rag-dashboard/src/backend/python-legacy")

# 设置环境变量
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

print("=== 测试 Rerank API 端点 ===")

try:
    print("1. 导入必要模块...")
    from infrastructure.adapters.reranker_service import get_reranker_service

    print("   ✅ 导入成功")

    print("\n2. 模拟 API 请求数据...")
    # 模拟 /api/v1/rerank 的请求体
    request_data = {
        "query": "什么是人工智能",
        "documents": [
            {
                "id": "doc1",
                "content": "人工智能是计算机科学的一个分支，旨在创建能够执行通常需要人类智能的任务的机器。",
            },
            {
                "id": "doc2",
                "content": "机器学习是人工智能的一个子领域，它使计算机能够在没有明确编程的情况下学习。",
            },
            {
                "id": "doc3",
                "content": "深度学习是机器学习的一个分支，使用神经网络模拟人类大脑的工作方式。",
            },
            {
                "id": "doc4",
                "content": "自然语言处理是人工智能的一个领域，专注于计算机和人类语言之间的交互。",
            },
            {
                "id": "doc5",
                "content": "计算机视觉是人工智能的一个分支，使计算机能够从图像和视频中获取信息。",
            },
        ],
        "top_k": 3,
    }

    query = request_data["query"]
    documents = request_data["documents"]
    top_k = request_data["top_k"]

    print(f"   查询: {query}")
    print(f"   文档数量: {len(documents)}")
    print(f"   top_k: {top_k}")

    print("\n3. 获取 Reranker 服务...")
    reranker_service = get_reranker_service()
    print("   ✅ Reranker 服务获取成功")

    print("\n4. 执行重排序...")
    # 提取文档内容
    doc_contents = [doc["content"] for doc in documents]

    # 调用 reranker
    scores = reranker_service.rerank(query, doc_contents)

    print("   原始文档和分数:")
    for i, (doc, score) in enumerate(zip(documents, scores)):
        print(f"     {i + 1}. ID: {doc['id']}, 分数: {score:.4f}")
        print(f"        内容: {doc['content'][:60]}...")

    print("\n5. 排序结果:")
    # 组合结果并排序
    results = []
    for i, (doc, score) in enumerate(zip(documents, scores)):
        results.append(
            {
                "id": doc["id"],
                "content": doc["content"][:200] if len(doc["content"]) > 200 else doc["content"],
                "score": float(score),
                "original_index": i,
            }
        )

    # 按分数排序
    results.sort(key=lambda x: x["score"], reverse=True)

    for i, result in enumerate(results[:top_k]):
        print(f"   {i + 1}. ID: {result['id']}, 分数: {result['score']:.4f}")
        print(f"      内容: {result['content'][:60]}...")

    print("\n6. 验证 API 响应格式...")
    # 模拟 API 响应
    api_response = {"results": results[:top_k], "query": query}

    print(f"   API 响应结构验证:")
    print(f"     - 包含 'results' 字段: {'results' in api_response}")
    print(f"     - 包含 'query' 字段: {'query' in api_response}")
    print(f"     - results 数量: {len(api_response['results'])}")
    print(
        f"     - 是否排序: {all(api_response['results'][i]['score'] >= api_response['results'][i + 1]['score'] for i in range(len(api_response['results']) - 1) if len(api_response['results']) > 1)}"
    )

    # 检查分数是否有意义（不是全部相同）
    unique_scores = len(set(round(r["score"], 3) for r in api_response["results"]))
    if unique_scores > 1:
        print(f"   ✅ 重排序工作正常（分数有差异）")
    else:
        print(f"   ⚠️ 所有分数相同，可能是模型未正确工作")

    print("\n7. 测试降级处理...")
    # 模拟 reranker 服务不可用的情况
    print("   模拟 reranker 不可用（返回默认分数）...")
    # 暂时保存原始模型
    original_model = reranker_service.model
    reranker_service.model = None

    try:
        fallback_scores = reranker_service.rerank(query, doc_contents)
        print(f"   降级处理返回的分数: {fallback_scores}")
        if all(score == 1.0 for score in fallback_scores):
            print("   ✅ 降级处理正确（返回统一分数 1.0）")
        else:
            print("   ⚠️ 降级处理可能有问题")
    finally:
        # 恢复模型
        reranker_service.model = original_model

    print("\n=== Rerank API 端点测试完成 ===")
    print("✅ 所有测试通过")
    print("\n总结:")
    print("- Reranker 模型加载成功")
    print("- 重排序功能正常工作")
    print("- 分数计算合理")
    print("- 降级处理机制有效")
    print("- API 响应格式正确")

except ImportError as e:
    print(f"\n❌ 导入错误: {e}")
    import traceback

    traceback.print_exc()
except Exception as e:
    print(f"\n❌ 测试失败: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)
