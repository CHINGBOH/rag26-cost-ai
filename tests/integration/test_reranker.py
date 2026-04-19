#!/usr/bin/env python3
"""
测试Reranker服务是否正常工作
"""

import sys

sys.path.insert(0, "/home/l/rag-dashboard/src/backend/python-legacy")

try:
    from infrastructure.adapters.reranker_service import get_reranker_service

    print("测试Reranker服务...")

    # 获取服务实例
    reranker = get_reranker_service()

    # 测试查询和文档
    query = "什么是人工智能"
    documents = [
        "人工智能是计算机科学的一个分支，旨在创建能够执行通常需要人类智能的任务的机器。",
        "机器学习是人工智能的一个子领域，它使计算机能够在没有明确编程的情况下学习。",
        "深度学习是机器学习的一个分支，使用神经网络模拟人类大脑的工作方式。",
    ]

    print(f"查询: {query}")
    print(f"文档数量: {len(documents)}")

    # 执行重排序
    scores = reranker.rerank(query, documents)

    print("\n重排序结果:")
    for i, (doc, score) in enumerate(zip(documents, scores)):
        print(f"{i + 1}. 分数: {score:.4f}, 文档: {doc[:50]}...")

    # 检查模型是否加载
    if reranker.model is None:
        print("\n⚠️ Reranker模型未加载，返回的是默认分数")
    else:
        print("\n✅ Reranker模型已加载并正常工作")

except ImportError as e:
    print(f"导入错误: {e}")
    print("请检查依赖是否安装完整")
except Exception as e:
    print(f"测试失败: {e}")
    import traceback

    traceback.print_exc()
