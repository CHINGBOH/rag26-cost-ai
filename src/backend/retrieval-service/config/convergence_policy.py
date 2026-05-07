"""
Issue #118: Convergence Policy - 真实质量目标收敛策略

解决Contract伪收敛问题：
- 原问题：只检查contract violations，没有真实质量目标
- 新策略：基于evaluation score判断收敛
- 支持硬目标（达到target_score）和软收敛（增量<threshold）
"""

import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class IterationRecord:
    """单次迭代记录"""
    iteration: int
    eval_score: float           # evaluation.confidence
    semantic_score: float       # evaluation.semantic_score (if available)
    passed: bool                # evaluation.passed
    contract_passed: bool       # contract verification passed
    feedback: str               # evaluation.feedback
    timestamp: Optional[str] = None


class ConvergencePolicy:
    """
    真实质量收敛策略
    
    收敛条件（优先级从高到低）：
    1. 硬目标达成：eval_score >= target_score（如0.75）
    2. 软收敛：连续2轮增量 < score_delta_threshold（如0.05）
    3. 强制停止：达到max_iterations上限
    
    与原有contract verification互补：
    - Contract：检查结构正确性（有chunks、有答案等）
    - Quality：检查语义质量（答案是否真正回答问题）
    """
    
    def __init__(
        self,
        target_score: float = 0.75,
        min_iterations: int = 1,
        max_iterations: int = 5,
        score_delta_threshold: float = 0.05,
        enable_soft_convergence: bool = True,
    ):
        """
        Args:
            target_score: 硬目标分数（达到即收敛）
            min_iterations: 最少迭代次数
            max_iterations: 最多迭代次数
            score_delta_threshold: 软收敛阈值（连续2轮增量<此值视为收敛）
            enable_soft_convergence: 是否启用软收敛
        """
        self.target_score = target_score
        self.min_iterations = min_iterations
        self.max_iterations = max_iterations
        self.score_delta_threshold = score_delta_threshold
        self.enable_soft_convergence = enable_soft_convergence
        
        logger.info(
            f"[ConvergencePolicy] initialized: "
            f"target={target_score}, min={min_iterations}, max={max_iterations}, "
            f"delta_threshold={score_delta_threshold}, soft_enabled={enable_soft_convergence}"
        )
    
    def is_converged(
        self,
        history: List[IterationRecord]
    ) -> Tuple[bool, str, Dict[str, any]]:
        """
        判断是否收敛
        
        Returns:
            (converged, reason, metadata)
            
        Reasons:
            - "target_reached": 达到目标分数
            - "delta_converged": 软收敛（增量小）
            - "max_iterations_forced": 超上限强制停止
            - "below_min_iterations": 未达最少迭代次数
            - "continue": 继续迭代
        """
        if not history:
            return False, "no_history", {}
        
        current_iter = len(history)
        latest = history[-1]
        latest_score = latest.eval_score
        
        # 1. 未达最少迭代次数
        if current_iter < self.min_iterations:
            return False, "below_min_iterations", {
                "current_iter": current_iter,
                "min_required": self.min_iterations
            }
        
        # 2. 硬目标：达到target_score
        if latest_score >= self.target_score:
            logger.info(
                f"[ConvergencePolicy] ✅ Target reached: "
                f"score={latest_score:.3f} >= target={self.target_score}"
            )
            return True, "target_reached", {
                "latest_score": latest_score,
                "target_score": self.target_score,
                "iterations": current_iter
            }
        
        # 3. 软收敛：连续2轮增量<threshold
        if self.enable_soft_convergence and current_iter >= 2:
            prev_score = history[-2].eval_score
            delta = abs(latest_score - prev_score)
            
            if delta < self.score_delta_threshold:
                logger.info(
                    f"[ConvergencePolicy] ✅ Delta converged: "
                    f"delta={delta:.3f} < threshold={self.score_delta_threshold}, "
                    f"score={latest_score:.3f}"
                )
                return True, "delta_converged", {
                    "latest_score": latest_score,
                    "prev_score": prev_score,
                    "delta": delta,
                    "threshold": self.score_delta_threshold,
                    "iterations": current_iter
                }
        
        # 4. 超上限强制停止
        if current_iter >= self.max_iterations:
            logger.warning(
                f"[ConvergencePolicy] ⚠️ Forced stop: "
                f"max_iterations={self.max_iterations} reached, "
                f"score={latest_score:.3f} (target={self.target_score})"
            )
            return True, "max_iterations_forced", {
                "latest_score": latest_score,
                "target_score": self.target_score,
                "score_gap": self.target_score - latest_score,
                "iterations": current_iter
            }
        
        # 5. 继续迭代
        logger.info(
            f"[ConvergencePolicy] Continue iteration {current_iter+1}/{self.max_iterations}: "
            f"score={latest_score:.3f} (target={self.target_score})"
        )
        return False, "continue", {
            "latest_score": latest_score,
            "target_score": self.target_score,
            "score_gap": self.target_score - latest_score,
            "current_iter": current_iter,
            "max_iter": self.max_iterations
        }
    
    def should_continue(self, history: List[IterationRecord]) -> bool:
        """简化接口：是否应该继续迭代"""
        converged, reason, _ = self.is_converged(history)
        return not converged
    
    def get_convergence_summary(self, history: List[IterationRecord]) -> Dict[str, any]:
        """获取收敛总结"""
        if not history:
            return {"status": "no_history", "iterations": 0}
        
        converged, reason, metadata = self.is_converged(history)
        
        scores = [rec.eval_score for rec in history]
        semantic_scores = [rec.semantic_score for rec in history if rec.semantic_score is not None]
        
        return {
            "status": reason,
            "converged": converged,
            "iterations": len(history),
            "final_score": history[-1].eval_score,
            "target_score": self.target_score,
            "score_progression": scores,
            "semantic_score_progression": semantic_scores if semantic_scores else None,
            "score_improvement": scores[-1] - scores[0] if len(scores) > 1 else 0.0,
            "metadata": metadata,
        }


def create_iteration_record_from_state(state: dict, iteration: int) -> IterationRecord:
    """从agent state创建迭代记录"""
    evaluation = state.get("evaluation") or {}
    contract_results = state.get("contract_results") or []
    
    return IterationRecord(
        iteration=iteration,
        eval_score=float(evaluation.get("confidence") or 0.0),
        semantic_score=float(evaluation.get("semantic_score") or 0.0) if "semantic_score" in evaluation else None,
        passed=bool(evaluation.get("passed", False)),
        contract_passed=all(cr.get("passed", False) for cr in contract_results),
        feedback=evaluation.get("feedback", ""),
        timestamp=None  # Can be filled with datetime.now(timezone.utc).isoformat()
    )


# 默认策略实例（可通过Feature Flag或环境变量覆盖）
_default_policy = None


def get_default_convergence_policy() -> ConvergencePolicy:
    """获取默认收敛策略"""
    global _default_policy
    
    if _default_policy is None:
        import os
        
        target_score = float(os.getenv("CONVERGENCE_TARGET_SCORE", "0.75"))
        min_iterations = int(os.getenv("CONVERGENCE_MIN_ITERATIONS", "1"))
        max_iterations = int(os.getenv("CONVERGENCE_MAX_ITERATIONS", "5"))
        delta_threshold = float(os.getenv("CONVERGENCE_DELTA_THRESHOLD", "0.05"))
        enable_soft = os.getenv("CONVERGENCE_ENABLE_SOFT", "true").lower() == "true"
        
        _default_policy = ConvergencePolicy(
            target_score=target_score,
            min_iterations=min_iterations,
            max_iterations=max_iterations,
            score_delta_threshold=delta_threshold,
            enable_soft_convergence=enable_soft,
        )
    
    return _default_policy
