"""
#167: Tool Guardrails 注入 LangGraph tool_node

防死循环机制，从 Hermes `tool_guardrails.py` 移植：
1. 工具调用去重缓存（同一参数不重复调）
2. 错误退避（连续失败 → 暂停该工具）
3. 空结果检测（3次空结果 → 强制跳转到 synthesize）
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from typing import Any, Optional

logger = logging.getLogger(__name__)

MAX_EMPTY_RESULTS = 3       # 连续空结果上限
MAX_CONSECUTIVE_ERRORS = 3  # 连续错误上限
MAX_SAME_CALLS = 2          # 同一参数重复调用上限


class ToolGuardrails:
    """工具调用安全护栏。每个 LangGraph session 创建一个实例。"""

    def __init__(self):
        # tool_name → list of (args_hash, result_hash)
        self._call_history: dict[str, list[tuple[str, str]]] = defaultdict(list)
        # tool_name → consecutive empty result count
        self._empty_streak: dict[str, int] = defaultdict(int)
        # tool_name → consecutive error count
        self._error_streak: dict[str, int] = defaultdict(int)
        # 本轮空结果总数（跨工具）
        self._total_empty_rounds = 0

    @staticmethod
    def _hash_args(args: dict[str, Any]) -> str:
        """参数哈希（去重用）。"""
        normalized = json.dumps(args, sort_keys=True, default=str)
        return hashlib.md5(normalized.encode()).hexdigest()[:12]

    @staticmethod
    def _is_empty_result(result: dict[str, Any] | str) -> bool:
        """检测工具返回是否为空。"""
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (json.JSONDecodeError, TypeError):
                return not result.strip()
        if isinstance(result, dict):
            chunks = result.get("chunks") or result.get("results") or result.get("data") or []
            return len(chunks) == 0
        return True

    @staticmethod
    def _is_error_result(result: dict[str, Any] | str) -> bool:
        """检测工具返回是否为错误。"""
        text = str(result).lower()
        error_markers = ["error", "exception", "failed", "timeout", "traceback"]
        return any(m in text for m in error_markers)

    def check_before_call(self, tool_name: str, args: dict[str, Any]) -> Optional[str]:
        """工具调用前检查。返回 None 表示允许，返回字符串表示阻止原因。"""
        # 检查：该工具是否被临时封禁（连续错误太多）
        if self._error_streak[tool_name] >= MAX_CONSECUTIVE_ERRORS:
            return f"Tool '{tool_name}' blocked after {self._error_streak[tool_name]} consecutive errors"

        # 检查：空结果是否过多（全局）
        if self._total_empty_rounds >= MAX_EMPTY_RESULTS:
            return f"Too many empty results ({self._total_empty_rounds}), force synthesize"

        # 检查：是否重复调用相同参数
        args_hash = self._hash_args(args)
        recent_calls = [h for h, _ in self._call_history[tool_name][-MAX_SAME_CALLS:]]
        if recent_calls.count(args_hash) >= MAX_SAME_CALLS:
            return f"Tool '{tool_name}' called with same args {MAX_SAME_CALLS}x — blocked to prevent loop"

        return None

    def record_result(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any] | str,
    ):
        """记录工具调用结果。"""
        args_hash = self._hash_args(args)
        result_hash = self._hash_args({"result": str(result)[:100]})
        self._call_history[tool_name].append((args_hash, result_hash))

        # 清理旧记录（只保留最近 20 条）
        if len(self._call_history[tool_name]) > 20:
            self._call_history[tool_name] = self._call_history[tool_name][-20:]

        # 更新 streak 计数器
        if self._is_empty_result(result):
            self._empty_streak[tool_name] += 1
            self._total_empty_rounds += 1
        else:
            self._empty_streak[tool_name] = 0

        if self._is_error_result(result):
            self._error_streak[tool_name] += 1
        else:
            self._error_streak[tool_name] = 0

    def should_force_synthesize(self) -> bool:
        """是否应该强制跳转到 synthesize_node。"""
        return self._total_empty_rounds >= MAX_EMPTY_RESULTS

    def get_stats(self) -> dict[str, Any]:
        """获取护栏统计信息。"""
        return {
            "total_calls": sum(len(h) for h in self._call_history.values()),
            "empty_streaks": dict(self._empty_streak),
            "error_streaks": dict(self._error_streak),
            "total_empty_rounds": self._total_empty_rounds,
            "unique_tools": len(self._call_history),
        }

    def reset(self):
        """重置所有计数器（新对话开始时调用）。"""
        self._call_history.clear()
        self._empty_streak.clear()
        self._error_streak.clear()
        self._total_empty_rounds = 0


# ── 集成到 tool_node ────────────────────────────────────────────────────────

def wrap_tool_node_with_guardrails(tool_node_func, guardrails: ToolGuardrails):
    """给 tool_node 加护栏包装器。

    实际集成点：在 graph.py 的 tool_node() 函数中，
    调用前用 guardrails.check_before_call() 检查，
    调用后用 guardrails.record_result() 记录。
    这里提供便捷的辅助方法。
    """
    return tool_node_func  # 直通，实际拦截在 graph.py 中完成


# ── Singleton ───────────────────────────────────────────────────────────────

_guardrails: Optional[ToolGuardrails] = None


def get_tool_guardrails() -> ToolGuardrails:
    global _guardrails
    if _guardrails is None:
        _guardrails = ToolGuardrails()
    return _guardrails


def reset_tool_guardrails():
    global _guardrails
    if _guardrails:
        _guardrails.reset()
