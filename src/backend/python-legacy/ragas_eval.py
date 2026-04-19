#!/usr/bin/env python3
"""
Ragas - RAG 语义质量评估
文档: https://docs.ragas.io

使用:
1. 安装: pip install ragas
2. 运行: python ragas_eval.py
"""

import sys
from pathlib import Path
from typing import List, Dict, Any

try:
    from ragas import evaluate
    from ragas.metrics import (
        context_relevancy,
        faithfulness,
        answer_relevance,
        answer_correctness,
        context_precision,
    )
except ImportError:
    print("请安装: pip install ragas")
    sys.exit(1)

# 评估指标配置
METRICS = [
    context_relevancy,
    faithfulness,
    answer_relevance,
    answer_correctness,
    context_precision,
]

# 测试数据 (实际项目请替换为你的真实数据)
TEST_CASES = [
    {
        "question": "如何配置 Qdrant 的索引参数？",
        "ground_truth": "在 Qdrant 中配置索引需要在 collection 创建时设置 hnsw 配置，包括 m、ef_construct 等参数",
        "answer": "Qdrant 索引配置通过 collection 配置完成，使用 hnsw 算法，需要设置 m（连接数）、ef_construct（构建时搜索）等参数",
        "contexts": [
            "Qdrant 是一个向量数据库，支持 HNSW 索引算法",
            "索引配置包括 m 参数控制每层的连接数，ef_construct 控制构建时的搜索范围",
            "可以通过 create_collection 接口指定索引参数"
        ]
    },
    {
        "question": "LangChain 和 LangGraph 的区别是什么？",
        "ground_truth": "LangChain 是 LLM 应用框架，提供组件；LangGraph 是 LangChain 的状态图编排器，专注于 Agent 和工作流",
        "answer": "LangChain 是通用 LLM 应用框架，LangGraph 是其中的状态图编排工具，专门用于构建 Agent 和复杂工作流",
        "contexts": [
            "LangChain 提供 LLM、Vector Store、Memory 等组件",
            "LangGraph 是基于状态图的 Agent 编排器",
            "LangGraph 属于 LangChain 生态中的一部分"
        ]
    }
]


def prepare_dataset(test_cases: List[Dict[str, Any]]) -> "Dataset":
    """
    准备评估数据集
    """
    from datasets import Dataset

    questions = [tc["question"] for tc in test_cases]
    ground_truths = [tc["ground_truth"] for tc in test_cases]
    answers = [tc["answer"] for tc in test_cases]
    contexts = [tc["contexts"] for tc in test_cases]

    return Dataset.from_dict({
        "question": questions,
        "ground_truth": ground_truths,
        "answer": answers,
        "contexts": contexts,
    })


def run_evaluation():
    """
    运行完整的 RAG 评估
    """
    print("=" * 60)
    print("RAG 语义质量评估 - Ragas")
    print("=" * 60)

    # 准备数据集
    print("\n1. 准备评估数据...")
    dataset = prepare_dataset(TEST_CASES)
    print(f"   测试用例数: {len(dataset)}")

    # 运行评估
    print("\n2. 运行评估...")
    result = evaluate(
        dataset=dataset,
        metrics=METRICS,
    )

    # 输出结果
    print("\n3. 评估结果:")
    print("-" * 60)
    print(result)

    # 详细分析
    df = result.to_pandas()
    print("\n4. 详细记录:")
    print("-" * 60)
    print(df)

    # 保存报告
    report_path = Path(__file__).parent / "ragas-report.html"
    df.to_html(report_path)
    print(f"\n报告已保存: {report_path}")

    return result


def analyze_result(result):
    """
    分析评估结果，给出架构改进建议
    """
    print("\n" + "=" * 60)
    print("架构合理性分析")
    print("=" * 60)

    scores = {
        "context_relevancy": result.get("context_relevancy", 0),
        "faithfulness": result.get("faithfulness", 0),
        "answer_relevance": result.get("answer_relevance", 0),
    }

    print(f"\n检索相关性 (Context Relevance): {scores['context_relevancy']:.2f}")
    print(f"事实一致性 (Faithfulness): {scores['faithfulness']:.2f}")
    print(f"答案相关性 (Answer Relevance): {scores['answer_relevance']:.2f}")

    print("\n建议:")

    if scores["context_relevancy"] < 0.6:
        print("  ⚠️  检索策略需要优化，考虑调整嵌入模型或 Rerank")

    if scores["faithfulness"] < 0.7:
        print("  ⚠️  Prompt 需要约束 LLM 更多依据检索结果回答")

    if scores["answer_relevance"] < 0.7:
        print("  ⚠️  Answer 生成 Prompt 需要优化，更贴近用户问题")

    if all(score > 0.75 for score in scores.values()):
        print("  ✅  RAG 架构总体良好！")


if __name__ == "__main__":
    try:
        result = run_evaluation()
        analyze_result(result)
    except KeyboardInterrupt:
        print("\n评估被取消")
        sys.exit(0)
    except Exception as e:
        print(f"\n评估出错: {e}")
        sys.exit(1)
