#!/usr/bin/env python3
"""
简化测试Reranker服务
"""

import sys
import os

# 添加项目路径
sys.path.insert(0, "/home/l/rag-dashboard/src/backend/python-legacy")

# 设置环境变量
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

print("=== 测试Reranker服务 ===")

try:
    print("1. 导入模块...")
    from infrastructure.adapters.reranker_service import get_reranker_service

    print("   ✅ 导入成功")

    print("\n2. 获取Reranker服务实例...")
    reranker = get_reranker_service()
    print("   ✅ 服务实例创建")

    print("\n3. 检查模型是否加载...")
    if reranker.model is None:
        print("   ⚠️ 模型未加载，可能正在加载或失败")
        # 尝试手动加载
        print("   尝试手动加载模型...")
        reranker._load_model()
        if reranker.model is None:
            print("   ❌ 模型加载失败")
        else:
            print("   ✅ 模型加载成功")
    else:
        print("   ✅ 模型已加载")

    print("\n4. 测试重排序功能...")
    query = "什么是人工智能"
    documents = [
        "人工智能是计算机科学的一个分支，旨在创建能够执行通常需要人类智能的任务的机器。",
        "机器学习是人工智能的一个子领域，它使计算机能够在没有明确编程的情况下学习。",
        "深度学习是机器学习的一个分支，使用神经网络模拟人类大脑的工作方式。",
        "自然语言处理是人工智能的一个领域，专注于计算机和人类语言之间的交互。",
    ]

    print(f"   查询: {query}")
    print(f"   文档数量: {len(documents)}")

    scores = reranker.rerank(query, documents)

    print("\n   重排序结果:")
    for i, (doc, score) in enumerate(zip(documents, scores)):
        print(f"   {i + 1}. 分数: {score:.4f} - {doc[:60]}...")

    # 检查分数是否有变化（不是全部1.0）
    unique_scores = len(set(round(s, 3) for s in scores))
    if unique_scores > 1:
        print("\n   ✅ 重排序工作正常（分数有差异）")
    else:
        print(f"\n   ⚠️ 所有分数相同: {scores[0]}，可能是模型未正确工作")

    print("\n=== 测试完成 ===")

except ImportError as e:
    print(f"\n❌ 导入错误: {e}")
    import traceback

    traceback.print_exc()
except Exception as e:
    print(f"\n❌ 测试失败: {e}")
    import traceback

    traceback.print_exc()
