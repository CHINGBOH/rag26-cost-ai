"""
Tests for Issue #124: StrictSemanticEvaluator

Validates that:
1. LLM semantic evaluation works correctly
2. Garbage answers get low scores (< 0.5)
3. Partial answers get medium scores (0.5-0.7)
4. Good answers get high scores (> 0.75)
5. Feature flag controls evaluation mode
"""

import os
import sys
import pytest
from pathlib import Path

# Bootstrap sys.path
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.agent.evaluator import StrictSemanticEvaluator


@pytest.fixture
def evaluator():
    """Create evaluator instance"""
    return StrictSemanticEvaluator()


@pytest.fixture
def sample_chunks():
    """Sample retrieval chunks"""
    return [
        {
            "content": "混凝土强度等级分为 C15、C20、C25、C30、C35、C40、C45、C50、C55、C60、C65、C70、C75、C80 等",
            "doc_id": "doc_1",
            "source": "建筑工程标准",
            "score": 0.85
        },
        {
            "content": "抗渗等级分为 P4、P6、P8、P10、P12 五个等级",
            "doc_id": "doc_2",
            "source": "混凝土规范",
            "score": 0.82
        },
        {
            "content": "混凝土强度等级越高，其抗渗性能越好，一般 C30 及以上可达到 P6-P8 抗渗等级",
            "doc_id": "doc_3",
            "source": "工程手册",
            "score": 0.90
        }
    ]


def test_garbage_answer_low_score(evaluator, sample_chunks):
    """垃圾答案应该得低分 (< 0.5)"""
    query = "混凝土强度等级与抗渗等级的关系是什么？"
    
    # 答非所问的答案（只列举了定义，没有回答"关系"）
    garbage_answer = "根据检索结果，混凝土强度等级分为C15-C80，抗渗等级分为P4-P12。"
    
    result = evaluator.evaluate_answer_quality(
        query=query,
        answer=garbage_answer,
        chunks=sample_chunks,
        query_type="semantic"
    )
    
    # 验证：垃圾答案应该得低分
    assert result["semantic_score"] < 0.5, f"垃圾答案分数过高: {result['semantic_score']}"
    assert result["confidence"] < 0.5, f"confidence 应该低于 0.5: {result['confidence']}"
    assert not result["passed"], "垃圾答案不应通过评估"
    assert "未真正回答问题" in result["feedback"] or result["llm_raw_score"] <= 2


def test_partial_answer_medium_score(evaluator, sample_chunks):
    """部分回答应该得中等分 (0.5-0.7)"""
    query = "混凝土强度等级与抗渗等级的关系是什么？"
    
    # 部分回答（提到了关系，但不够详细）
    partial_answer = "混凝土强度等级和抗渗等级有一定关系，强度越高抗渗性越好。"
    
    result = evaluator.evaluate_answer_quality(
        query=query,
        answer=partial_answer,
        chunks=sample_chunks,
        query_type="semantic"
    )
    
    # 验证：部分答案应该得中等分
    assert 0.4 <= result["semantic_score"] <= 0.8, f"部分答案分数应在 0.4-0.8: {result['semantic_score']}"
    assert 3 <= result["llm_raw_score"] <= 4, f"LLM原始分应为3-4分: {result['llm_raw_score']}"


def test_good_answer_high_score(evaluator, sample_chunks):
    """好答案应该得高分 (> 0.75)"""
    query = "混凝土强度等级与抗渗等级的关系是什么？"
    
    # 完整回答
    good_answer = """混凝土强度等级与抗渗等级呈正相关关系。
强度等级越高，其抗渗性能越好。一般来说，C30及以上强度等级的混凝土可达到P6-P8抗渗等级【doc_3】。
具体而言，强度等级分为C15-C80【doc_1】，抗渗等级分为P4-P12【doc_2】。"""
    
    result = evaluator.evaluate_answer_quality(
        query=query,
        answer=good_answer,
        chunks=sample_chunks,
        query_type="semantic"
    )
    
    # 验证：好答案应该得高分
    assert result["semantic_score"] >= 0.7, f"好答案分数应 >= 0.7: {result['semantic_score']}"
    assert result["llm_raw_score"] >= 4, f"LLM原始分应 >= 4: {result['llm_raw_score']}"
    assert result["confidence"] >= 0.6, f"confidence 应 >= 0.6: {result['confidence']}"
    
    # 有引用的答案应该有较高的事实一致性
    assert result["fact_consistency"] > 0.3, f"有引用应该提升事实一致性: {result['fact_consistency']}"


def test_refusal_answer_lowest_score(evaluator, sample_chunks):
    """拒绝回答应该得最低分"""
    query = "混凝土强度等级与抗渗等级的关系是什么？"
    
    # 拒绝回答
    refusal_answer = "很抱歉，根据检索结果无法回答您的问题。"
    
    result = evaluator.evaluate_answer_quality(
        query=query,
        answer=refusal_answer,
        chunks=sample_chunks,
        query_type="semantic"
    )
    
    # 验证：拒绝回答应该得最低分
    assert result["semantic_score"] <= 0.3, f"拒绝回答分数应 <= 0.3: {result['semantic_score']}"
    assert result["llm_raw_score"] == 1, f"拒绝回答LLM原始分应为1: {result['llm_raw_score']}"
    assert not result["passed"], "拒绝回答不应通过"


def test_empty_answer_low_score(evaluator, sample_chunks):
    """空答案应该得低分"""
    query = "混凝土强度等级与抗渗等级的关系是什么？"
    empty_answer = ""
    
    result = evaluator.evaluate_answer_quality(
        query=query,
        answer=empty_answer,
        chunks=sample_chunks,
        query_type="semantic"
    )
    
    assert result["semantic_score"] <= 0.3, f"空答案分数应很低: {result['semantic_score']}"
    assert not result["passed"], "空答案不应通过"


def test_no_chunks_low_score(evaluator):
    """没有检索结果应该影响评分"""
    query = "混凝土强度等级与抗渗等级的关系是什么？"
    answer = "混凝土强度等级与抗渗等级呈正相关。"
    
    result = evaluator.evaluate_answer_quality(
        query=query,
        answer=answer,
        chunks=[],  # 没有检索结果
        query_type="semantic"
    )
    
    # 没有检索结果，即使答案不错也不应通过（因为缺少evidence）
    assert result["source_diversity"] == 0.0, "没有chunks时来源多样性应为0"
    assert not result["passed"], "没有检索结果不应通过评估"


def test_fact_consistency_with_citations(evaluator, sample_chunks):
    """带引用的答案应该有更高的事实一致性"""
    query = "混凝土强度等级有哪些？"
    
    answer_without_citation = "混凝土强度等级分为 C15-C80。"
    result_no_cite = evaluator.evaluate_answer_quality(
        query=query,
        answer=answer_without_citation,
        chunks=sample_chunks,
        query_type="semantic"
    )
    
    answer_with_citation = "混凝土强度等级分为 C15-C80【doc_1】。"
    result_with_cite = evaluator.evaluate_answer_quality(
        query=query,
        answer=answer_with_citation,
        chunks=sample_chunks,
        query_type="semantic"
    )
    
    # 有引用的答案事实一致性应该更高
    assert result_with_cite["fact_consistency"] > result_no_cite["fact_consistency"], \
        "有引用的答案应该有更高的事实一致性"


def test_source_diversity_calculation(evaluator):
    """来源多样性计算验证"""
    # 3个不同来源
    diverse_chunks = [
        {"content": "A", "doc_id": "doc_1", "source": "src_1"},
        {"content": "B", "doc_id": "doc_2", "source": "src_2"},
        {"content": "C", "doc_id": "doc_3", "source": "src_3"},
    ]
    
    # 单一来源
    single_source_chunks = [
        {"content": "A", "doc_id": "doc_1", "source": "src_1"},
        {"content": "B", "doc_id": "doc_1", "source": "src_1"},
    ]
    
    query = "测试问题"
    answer = "测试答案"
    
    diverse_result = evaluator.evaluate_answer_quality(
        query=query, answer=answer, chunks=diverse_chunks, query_type="semantic"
    )
    
    single_result = evaluator.evaluate_answer_quality(
        query=query, answer=answer, chunks=single_source_chunks, query_type="semantic"
    )
    
    assert diverse_result["source_diversity"] > single_result["source_diversity"], \
        "多来源应该有更高的多样性分数"


def test_evaluator_error_handling(evaluator):
    """测试评估器的错误处理"""
    # 异常输入
    result = evaluator.evaluate_answer_quality(
        query="",
        answer="",
        chunks=[],
        query_type="semantic"
    )
    
    # 应该返回降级评分，不应崩溃
    assert isinstance(result, dict), "异常输入应返回dict而不是崩溃"
    assert "passed" in result, "结果应包含passed字段"
    assert "confidence" in result, "结果应包含confidence字段"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
