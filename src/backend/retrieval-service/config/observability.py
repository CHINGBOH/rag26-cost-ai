"""
决策可观测性层 - 记录所有关键决策点和参数使用

目标：
1. 记录每次关键决策（tool 选择、followup 过滤、学习触发等）
2. 关联使用的参数和阈值
3. 支持事后审计和问题追溯
4. 生成可视化决策链

核心原则：
- 每个决策必须有 decision_id（可追溯）
- 记录输入、输出、使用的参数、理由
- 支持结构化查询（按类型、时间、参数）
- 性能优先：异步写入，批量flush

示例用法：
    ```python
    from config.observability import Decision, DecisionLogger
    
    # 记录决策
    decision = Decision(
        decision_type="followup_filter",
        context={"question": "...", "coverage": 0.45},
        params_used={
            "followup_coverage_threshold_high": 0.65,
            "followup_coverage_threshold_med": 0.50
        },
        outcome="rejected",
        reason="coverage 0.45 below med threshold 0.50"
    )
    
    DecisionLogger.log(decision)
    
    # 或者使用装饰器
    @observe_decision("followup_filter")
    def filter_followup(question: str, coverage: float):
        threshold = param("followup_coverage_threshold_high")
        if coverage < threshold:
            return {"accepted": False, "reason": "below threshold"}
        return {"accepted": True}
    ```
"""

from typing import Any, Dict, List, Optional, Callable
from datetime import datetime
from enum import Enum
import logging
import json
import uuid
from functools import wraps
from collections import defaultdict
import asyncio
from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================================
# 决策类型枚举
# ============================================================================

class DecisionType(str, Enum):
    """决策类型"""
    
    # Followup 相关
    FOLLOWUP_FILTER = "followup_filter"           # 追问过滤
    FOLLOWUP_COVERAGE = "followup_coverage"       # 覆盖检测
    FOLLOWUP_TIER = "followup_tier"               # 分层
    
    # Learning 相关
    LEARNING_TRIGGER = "learning_trigger"         # 学习触发
    LEARNING_RETEST = "learning_retest"           # 重测调度
    LEARNING_GAP_CLASSIFICATION = "learning_gap"  # 知识缺口分类
    
    # Tool 相关
    TOOL_SELECTION = "tool_selection"             # 工具选择
    TOOL_TIMEOUT = "tool_timeout"                 # 工具超时
    
    # Contract 相关
    CONTRACT_ITERATION = "contract_iteration"     # 合约迭代
    CONTRACT_CONVERGENCE = "contract_convergence" # 收敛判断
    
    # Evaluation 相关
    EVALUATION_SCORE = "evaluation_score"         # 评分计算
    EVALUATION_QUALITY = "evaluation_quality"     # 质量判断
    
    # Retrieval 相关
    RETRIEVAL_STRATEGY = "retrieval_strategy"     # 检索策略
    RETRIEVAL_RERANK = "retrieval_rerank"         # 重排序
    
    # Agent 相关
    AGENT_ITERATION = "agent_iteration"           # Agent 迭代
    AGENT_FINAL = "agent_final"                   # 最终决策


# ============================================================================
# 决策记录模型
# ============================================================================

class Decision:
    """
    单个决策记录
    
    Attributes:
        decision_id: 唯一标识
        decision_type: 决策类型
        timestamp: 时间戳
        context: 决策上下文（输入）
        params_used: 使用的参数（{param_name: value}）
        outcome: 决策结果
        reason: 决策理由
        metadata: 额外元数据（可选）
    """
    
    def __init__(
        self,
        decision_type: DecisionType,
        context: Dict[str, Any],
        params_used: Dict[str, Any],
        outcome: Any,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None,
        decision_id: Optional[str] = None,
        parent_id: Optional[str] = None
    ):
        self.decision_id = decision_id or str(uuid.uuid4())
        self.decision_type = decision_type
        self.timestamp = datetime.now()
        self.context = context
        self.params_used = params_used
        self.outcome = outcome
        self.reason = reason
        self.metadata = metadata or {}
        self.parent_id = parent_id  # 支持决策链
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "decision_id": self.decision_id,
            "decision_type": self.decision_type.value if isinstance(self.decision_type, DecisionType) else self.decision_type,
            "timestamp": self.timestamp.isoformat(),
            "context": self.context,
            "params_used": self.params_used,
            "outcome": self.outcome,
            "reason": self.reason,
            "metadata": self.metadata,
            "parent_id": self.parent_id
        }
    
    def to_json(self) -> str:
        """转换为 JSON"""
        return json.dumps(self.to_dict(), ensure_ascii=False)


# ============================================================================
# 决策日志器
# ============================================================================

class DecisionLogger:
    """
    决策日志器
    
    职责：
    1. 记录决策到内存缓冲区
    2. 异步批量写入文件
    3. 支持查询和过滤
    4. 定期清理旧记录
    """
    
    # 内存缓冲区
    _buffer: List[Decision] = []
    _max_buffer_size = 100
    
    # 写入队列
    _write_queue: asyncio.Queue = None
    _writer_task: asyncio.Task = None
    
    # 日志文件路径
    _log_dir = Path("logs/decisions")
    _current_log_file: Optional[Path] = None
    
    # 统计
    _stats = {
        "total_logged": 0,
        "by_type": defaultdict(int),
        "by_outcome": defaultdict(int)
    }
    
    @classmethod
    def initialize(cls, log_dir: str = "logs/decisions", max_buffer_size: int = 100):
        """
        初始化决策日志器
        
        Args:
            log_dir: 日志目录
            max_buffer_size: 最大缓冲区大小
        """
        cls._log_dir = Path(log_dir)
        cls._log_dir.mkdir(parents=True, exist_ok=True)
        cls._max_buffer_size = max_buffer_size
        
        # 创建今天的日志文件
        today = datetime.now().strftime("%Y-%m-%d")
        cls._current_log_file = cls._log_dir / f"decisions_{today}.jsonl"
        
        logger.info(f"[DecisionLogger] Initialized. Log file: {cls._current_log_file}")
    
    @classmethod
    def log(cls, decision: Decision) -> None:
        """
        记录一个决策
        
        Args:
            decision: 决策对象
        """
        # 添加到缓冲区
        cls._buffer.append(decision)
        
        # 更新统计
        cls._stats["total_logged"] += 1
        cls._stats["by_type"][decision.decision_type.value if isinstance(decision.decision_type, DecisionType) else decision.decision_type] += 1
        
        # 如果缓冲区满了，立即flush
        if len(cls._buffer) >= cls._max_buffer_size:
            cls.flush()
        
        logger.debug(
            f"[DecisionLogger] Logged decision: {decision.decision_type.value if isinstance(decision.decision_type, DecisionType) else decision.decision_type} "
            f"-> {decision.outcome}"
        )
    
    @classmethod
    def flush(cls) -> None:
        """
        将缓冲区写入文件
        """
        if not cls._buffer:
            return
        
        if cls._current_log_file is None:
            cls.initialize()
        
        # 写入文件
        try:
            with open(cls._current_log_file, "a", encoding="utf-8") as f:
                for decision in cls._buffer:
                    f.write(decision.to_json() + "\n")
            
            logger.debug(f"[DecisionLogger] Flushed {len(cls._buffer)} decisions to {cls._current_log_file}")
            cls._buffer.clear()
        
        except Exception as e:
            logger.error(f"[DecisionLogger] Failed to flush decisions: {e}")
    
    @classmethod
    def query(
        cls,
        decision_type: Optional[DecisionType] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        param_name: Optional[str] = None,
        limit: int = 100
    ) -> List[Decision]:
        """
        查询决策记录
        
        Args:
            decision_type: 按决策类型过滤
            start_time: 开始时间
            end_time: 结束时间
            param_name: 按使用的参数名过滤
            limit: 最多返回 N 条
        
        Returns:
            符合条件的决策列表
        """
        results = []
        
        # 从内存缓冲区查询
        for decision in cls._buffer:
            if decision_type and decision.decision_type != decision_type:
                continue
            if start_time and decision.timestamp < start_time:
                continue
            if end_time and decision.timestamp > end_time:
                continue
            if param_name and param_name not in decision.params_used:
                continue
            
            results.append(decision)
            
            if len(results) >= limit:
                break
        
        return results
    
    @classmethod
    def get_stats(cls) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_logged": cls._stats["total_logged"],
            "buffer_size": len(cls._buffer),
            "by_type": dict(cls._stats["by_type"]),
            "by_outcome": dict(cls._stats["by_outcome"]),
            "log_file": str(cls._current_log_file) if cls._current_log_file else None
        }
    
    @classmethod
    def clear_buffer(cls) -> None:
        """清空缓冲区（测试用）"""
        cls._buffer.clear()
        logger.warning("[DecisionLogger] Buffer cleared")


# ============================================================================
# 装饰器：自动记录决策
# ============================================================================

def observe_decision(
    decision_type: DecisionType,
    extract_context: Optional[Callable] = None,
    extract_params: Optional[Callable] = None,
    extract_outcome: Optional[Callable] = None
):
    """
    装饰器：自动记录函数的决策过程
    
    Args:
        decision_type: 决策类型
        extract_context: 从函数参数提取上下文（可选）
        extract_params: 从函数内部提取使用的参数（可选）
        extract_outcome: 从返回值提取结果（可选）
    
    示例：
        @observe_decision(
            DecisionType.FOLLOWUP_FILTER,
            extract_context=lambda args, kwargs: {"question": args[0], "coverage": args[1]},
            extract_outcome=lambda result: result["accepted"]
        )
        def filter_followup(question: str, coverage: float):
            threshold = param("followup_coverage_threshold_high")
            if coverage < threshold:
                return {"accepted": False, "reason": "below threshold"}
            return {"accepted": True}
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 提取上下文
            if extract_context:
                context = extract_context(args, kwargs)
            else:
                context = {"args": args, "kwargs": kwargs}
            
            # 执行函数
            result = func(*args, **kwargs)
            
            # 提取参数使用
            if extract_params:
                params_used = extract_params(args, kwargs, result)
            else:
                params_used = {}
            
            # 提取结果
            if extract_outcome:
                outcome = extract_outcome(result)
            else:
                outcome = result
            
            # 提取理由
            if isinstance(result, dict) and "reason" in result:
                reason = result["reason"]
            else:
                reason = f"Function {func.__name__} completed"
            
            # 记录决策
            decision = Decision(
                decision_type=decision_type,
                context=context,
                params_used=params_used,
                outcome=outcome,
                reason=reason
            )
            
            DecisionLogger.log(decision)
            
            return result
        
        return wrapper
    return decorator


# ============================================================================
# 便捷函数
# ============================================================================

def log_decision(
    decision_type: DecisionType,
    context: Optional[Dict[str, Any]] = None,
    params_used: Optional[Dict[str, Any]] = None,
    outcome: Any = None,
    reason: Optional[str] = None,
    **kwargs
) -> str:
    """
    便捷函数：记录一个决策
    
    Returns:
        decision_id
    """
    if context is None:
        context = kwargs.pop("inputs", {})
    if params_used is None:
        params_used = kwargs.pop("params_used", {})
    if outcome is None:
        outcome = kwargs.pop("outputs", None)
    if reason is None:
        reason = kwargs.pop("rationale", "")

    confidence = kwargs.pop("confidence", None)
    if confidence is not None:
        metadata = dict(kwargs.pop("metadata", {}) or {})
        metadata["confidence"] = confidence
        kwargs["metadata"] = metadata

    decision = Decision(
        decision_type=decision_type,
        context=context,
        params_used=params_used,
        outcome=outcome,
        reason=reason or "",
        **kwargs
    )
    
    DecisionLogger.log(decision)
    
    return decision.decision_id


def query_decisions(
    decision_type: Optional[DecisionType] = None,
    **kwargs
) -> List[Dict[str, Any]]:
    """
    便捷函数：查询决策记录
    
    Returns:
        决策列表（字典格式）
    """
    decisions = DecisionLogger.query(decision_type=decision_type, **kwargs)
    return [d.to_dict() for d in decisions]


# ============================================================================
# 初始化
# ============================================================================

# 启动时自动初始化
DecisionLogger.initialize()
