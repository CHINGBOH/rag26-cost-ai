"""
Tests for Issue #118: Quality-based Convergence Policy

Validates that:
1. Convergence policy correctly judges when to stop iterating
2. Hard target (target_score) convergence works
3. Soft convergence (delta threshold) works  
4. Max iterations forced stop works
5. Iteration history tracking works
"""

import pytest
from config.convergence_policy import (
    ConvergencePolicy,
    IterationRecord,
    create_iteration_record_from_state,
    get_default_convergence_policy,
)


@pytest.fixture
def policy():
    """Create policy with default settings"""
    return ConvergencePolicy(
        target_score=0.75,
        min_iterations=1,
        max_iterations=5,
        score_delta_threshold=0.05,
        enable_soft_convergence=True,
    )


def test_target_reached_convergence(policy):
    """达到目标分数应该收敛"""
    history = [
        IterationRecord(0, eval_score=0.50, semantic_score=0.45, passed=False, contract_passed=True, feedback="低分"),
        IterationRecord(1, eval_score=0.65, semantic_score=0.60, passed=False, contract_passed=True, feedback="中分"),
        IterationRecord(2, eval_score=0.80, semantic_score=0.75, passed=True, contract_passed=True, feedback="高分"),
    ]
    
    converged, reason, metadata = policy.is_converged(history)
    
    assert converged is True
    assert reason == "target_reached"
    assert metadata["latest_score"] == 0.80
    assert metadata["iterations"] == 3


def test_delta_convergence(policy):
    """增量小于阈值应该软收敛"""
    history = [
        IterationRecord(0, eval_score=0.60, semantic_score=0.55, passed=False, contract_passed=True, feedback=""),
        IterationRecord(1, eval_score=0.63, semantic_score=0.58, passed=False, contract_passed=True, feedback=""),  # delta=0.03 < 0.05
    ]
    
    converged, reason, metadata = policy.is_converged(history)
    
    assert converged is True
    assert reason == "delta_converged"
    assert metadata["delta"] < 0.05


def test_max_iterations_forced_stop(policy):
    """达到max_iterations应该强制停止"""
    history = [
        IterationRecord(i, eval_score=0.40 + i*0.05, semantic_score=0.35 + i*0.05, passed=False, contract_passed=True, feedback="")
        for i in range(5)  # 5次迭代
    ]
    
    converged, reason, metadata = policy.is_converged(history)
    
    assert converged is True
    assert reason == "max_iterations_forced"
    assert metadata["iterations"] == 5
    assert metadata["latest_score"] < policy.target_score  # 未达目标但强制停止


def test_below_min_iterations(policy):
    """未达最少迭代次数不应收敛"""
    history = [
        IterationRecord(0, eval_score=0.90, semantic_score=0.85, passed=True, contract_passed=True, feedback=""),
    ]
    
    # Set min_iterations to 2
    policy.min_iterations = 2
    
    converged, reason, metadata = policy.is_converged(history)
    
    assert converged is False
    assert reason == "below_min_iterations"


def test_continue_iteration(policy):
    """正常迭代中应该继续"""
    history = [
        IterationRecord(0, eval_score=0.50, semantic_score=0.45, passed=False, contract_passed=True, feedback=""),
        IterationRecord(1, eval_score=0.60, semantic_score=0.55, passed=False, contract_passed=True, feedback=""),  # delta=0.10 > 0.05
    ]
    
    converged, reason, metadata = policy.is_converged(history)
    
    assert converged is False
    assert reason == "continue"
    assert metadata["score_gap"] > 0  # 还未达目标


def test_soft_convergence_disabled(policy):
    """禁用软收敛时应该不触发delta收敛"""
    policy.enable_soft_convergence = False
    
    history = [
        IterationRecord(0, eval_score=0.60, semantic_score=0.55, passed=False, contract_passed=True, feedback=""),
        IterationRecord(1, eval_score=0.62, semantic_score=0.57, passed=False, contract_passed=True, feedback=""),  # delta=0.02 < 0.05
    ]
    
    converged, reason, metadata = policy.is_converged(history)
    
    # 软收敛禁用，应该continue而不是delta_converged
    assert converged is False
    assert reason == "continue"


def test_should_continue_helper(policy):
    """测试should_continue辅助方法"""
    history_continue = [
        IterationRecord(0, eval_score=0.50, semantic_score=0.45, passed=False, contract_passed=True, feedback=""),
    ]
    
    history_stop = [
        IterationRecord(0, eval_score=0.50, semantic_score=0.45, passed=False, contract_passed=True, feedback=""),
        IterationRecord(1, eval_score=0.80, semantic_score=0.75, passed=True, contract_passed=True, feedback=""),
    ]
    
    assert policy.should_continue(history_continue) is True
    assert policy.should_continue(history_stop) is False


def test_convergence_summary(policy):
    """测试收敛总结"""
    history = [
        IterationRecord(0, eval_score=0.50, semantic_score=0.45, passed=False, contract_passed=True, feedback="低分"),
        IterationRecord(1, eval_score=0.65, semantic_score=0.60, passed=False, contract_passed=True, feedback="中分"),
        IterationRecord(2, eval_score=0.80, semantic_score=0.75, passed=True, contract_passed=True, feedback="高分"),
    ]
    
    summary = policy.get_convergence_summary(history)
    
    assert summary["status"] == "target_reached"
    assert summary["converged"] is True
    assert summary["iterations"] == 3
    assert summary["final_score"] == 0.80
    assert abs(summary["score_improvement"] - 0.30) < 0.001  # 浮点数精度容差
    assert len(summary["score_progression"]) == 3


def test_create_iteration_record_from_state():
    """测试从agent state创建迭代记录"""
    state = {
        "evaluation": {
            "confidence": 0.75,
            "semantic_score": 0.70,
            "passed": True,
            "feedback": "评估通过"
        },
        "contract_results": [
            {"node": "query_analysis", "passed": True, "violations": []},
            {"node": "synthesize", "passed": True, "violations": []},
        ]
    }
    
    record = create_iteration_record_from_state(state, iteration=2)
    
    assert record.iteration == 2
    assert record.eval_score == 0.75
    assert record.semantic_score == 0.70
    assert record.passed is True
    assert record.contract_passed is True
    assert record.feedback == "评估通过"


def test_empty_history():
    """空历史应该返回no_history"""
    policy = ConvergencePolicy()
    history = []
    
    converged, reason, metadata = policy.is_converged(history)
    
    assert converged is False
    assert reason == "no_history"


def test_score_improvement_tracking():
    """测试分数提升追踪"""
    policy = ConvergencePolicy(target_score=0.75)
    
    # Case 1: 持续提升
    improving_history = [
        IterationRecord(i, eval_score=0.40 + i*0.10, semantic_score=None, passed=False, contract_passed=True, feedback="")
        for i in range(4)
    ]
    
    summary = policy.get_convergence_summary(improving_history)
    assert abs(summary["score_improvement"] - 0.30) < 0.001  # 浮点数容差
    
    # Case 2: 下降
    declining_history = [
        IterationRecord(0, eval_score=0.70, semantic_score=None, passed=True, contract_passed=True, feedback=""),
        IterationRecord(1, eval_score=0.60, semantic_score=None, passed=False, contract_passed=True, feedback=""),
    ]
    
    summary = policy.get_convergence_summary(declining_history)
    assert abs(summary["score_improvement"] - (-0.10)) < 0.001  # 浮点数容差


def test_convergence_with_contract_failures():
    """测试contract失败时的收敛行为"""
    policy = ConvergencePolicy(target_score=0.75)
    
    history = [
        IterationRecord(0, eval_score=0.80, semantic_score=0.75, passed=True, contract_passed=False, feedback="contract violation"),
    ]
    
    # 即使eval_score达标，但如果需要也可以基于contract_passed判断
    converged, reason, metadata = policy.is_converged(history)
    
    # 目前逻辑只看eval_score，不看contract_passed
    # （contract收敛由contract_verifier_node单独处理）
    assert converged is True
    assert reason == "target_reached"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
