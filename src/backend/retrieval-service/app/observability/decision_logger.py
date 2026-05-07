"""
Decision Logger for RAG System

Purpose: 记录系统关键决策点，提供可追溯性和可观测性
Author: AI Agent
Date: 2026-05-07
"""

import logging
from enum import Enum
from typing import Dict, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class DecisionType(str, Enum):
    """决策类型枚举"""
    # Task 2 新增
    FOLLOWUP_FILTERING = "followup_filtering"  # Followup 过滤决策
    TOOL_SELECTION = "tool_selection"          # 工具选择决策
    RETRIEVAL_STRATEGY = "retrieval_strategy"  # 检索策略决策
    EVALUATION_SCORE = "evaluation_score"      # 评分决策
    LEARNING_TRIGGER = "learning_trigger"      # Learning 触发决策
    
    # 原有类型（可能存在）
    CONTRACT_CONVERGENCE = "contract_convergence"  # Contract 收敛决策
    QUERY_REWRITE = "query_rewrite"                # 查询重写决策
    DATABASE_SELECTION = "database_selection"      # 数据库选择决策

def log_decision(
    decision_type: DecisionType,
    rationale: str,
    metadata: Optional[Dict[str, Any]] = None,
    outcome: Optional[str] = None
):
    """
    记录关键决策
    
    Args:
        decision_type: 决策类型
        rationale: 决策理由
        metadata: 额外元数据
        outcome: 决策结果
    """
    try:
        decision_log = {
            "decision_type": decision_type.value,
            "rationale": rationale,
            "metadata": metadata or {},
            "outcome": outcome,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # 结构化日志输出
        logger.info(
            f"[Decision] {decision_type.value}: {rationale}",
            extra={"decision": decision_log}
        )
        
        # Prometheus metrics (如果已导入)
        try:
            from app.observability.prometheus_metrics import record_decision_log
            record_decision_log(decision_type.value)
        except ImportError:
            pass  # Prometheus metrics 未初始化
    
    except Exception as e:
        logger.error(f"Failed to log decision: {e}")

logger.info("✅ DecisionLogger initialized")
