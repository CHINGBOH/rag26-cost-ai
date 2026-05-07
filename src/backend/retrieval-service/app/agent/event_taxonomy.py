"""
Canonical interaction outcome taxonomy for Phase 6.
"""

from __future__ import annotations

from dataclasses import dataclass

OUTCOME_FAMILY_VALUES = {
    "answered",
    "refused",
    "failed",
    "cancelled",
    "non_task",
}

QUALITY_VALUES = {"good", "weak", "failure", "non_task"}
NON_TASK_QUERY_TYPES = {"chitchat", "irrelevant"}

REFUSAL_MARKERS = [
    "无法直接回答",
    "无法回答",
    "无法提供",
    "无法分析",
    "不足以回答",
    "未提供",
    "无相关数据",
    "未包含",
    "无法直接计算",
    "无法给出",
    "无法确认",
    "现有依据不足",
    "现有检索结果不足",
    "暂时无法给出可靠结论",
]


@dataclass(frozen=True)
class RunOutcome:
    outcome_family: str
    outcome_code: str
    quality: str
    learning_eligible: bool
    status: str = "completed"
    refused: bool = False
    early_exit: bool = False
