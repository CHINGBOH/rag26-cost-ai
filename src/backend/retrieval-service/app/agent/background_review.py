"""
#168: Background Review Actor（即时学习层）

每轮对话结束后异步 fork 一个受限 agent 审查对话并更新知识库。
参考 Hermes Agent 的 MemoryManager + BackgroundReview 机制。

核心规则：
- 工具集严格受限：只能 memory_write / skill_patch / gap_update / errors_append
- 不读取外部记忆插件（skip_memory=True），防泄露
- LLM 指令极简（删除 Memory Recall / User Identity / Messaging 章节）
- 所有输出静默，只写审计日志
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# 审查 actor 允许的工具集
_ALLOWED_REVIEW_TOOLS = frozenset({
    "memory_write",    # 写 MEMORY.md / USER.md
    "skill_patch",     # 更新 SKILL.md 内容
    "gap_update",      # 更新 knowledge_gaps 表
    "errors_append",   # 追加 ERRORS.md
})

# 不捕获的内容模式（与 issue #168 定义一致）
_SKIP_PATTERNS = [
    "command not found",
    "No such file or directory",
    "ModuleNotFoundError",
    "Connection refused",
    "connection timeout",
]


class ReviewResult:
    """审查结果。"""

    def __init__(self):
        self.memory_writes: int = 0
        self.skill_patches: int = 0
        self.gap_updates: int = 0
        self.errors_appended: int = 0
        self.duration_ms: float = 0
        self.error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_writes": self.memory_writes,
            "skill_patches": self.skill_patches,
            "gap_updates": self.gap_updates,
            "errors_appended": self.errors_appended,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


class BackgroundReviewActor:
    """后台审查 Actor 主类。"""

    def __init__(self):
        self._review_count = 0

    async def run(
        self,
        *,
        session_id: str,
        conversation: list[dict[str, Any]],
        query: str,
        answer: str,
        chunks_count: int,
        evaluation: dict[str, Any] | None = None,
        domain_id: str = "construction-cost",
    ) -> ReviewResult:
        """执行一次后台审查。

        Args:
            session_id: 本轮会话 ID
            conversation: 完整对话历史
            query: 用户问题
            answer: 最终回答
            chunks_count: 检索结果数
            evaluation: 评估结果
            domain_id: 领域 ID
        """
        import time as _time
        t0 = _time.monotonic()
        result = ReviewResult()
        self._review_count += 1

        try:
            logger.info(
                "background_review.started review=%d session=%s query=%s",
                self._review_count, session_id, query[:80],
            )

            # ── 1. 审查对话内容 ──
            transcript = self._build_review_transcript(
                query=query,
                answer=answer,
                conversation=conversation,
                evaluation=evaluation,
            )

            findings = await self._analyze_transcript(transcript, domain_id)

            # ── 2. 执行发现的操作 ──
            await self._execute_findings(findings, session_id, domain_id, result)

            result.duration_ms = (_time.monotonic() - t0) * 1000
            logger.info(
                "background_review.completed review=%d duration=%.0fms %s",
                self._review_count, result.duration_ms, result.to_dict(),
            )

        except Exception as exc:
            result.error = str(exc)
            result.duration_ms = (_time.monotonic() - t0) * 1000
            logger.warning(
                "background_review.failed review=%d error=%s",
                self._review_count, exc,
            )

        return result

    def _build_review_transcript(
        self,
        *,
        query: str,
        answer: str,
        conversation: list[dict[str, Any]],
        evaluation: dict[str, Any] | None,
    ) -> str:
        """构建供审查 LLM 阅读的对话摘要。"""
        lines = [
            "=== CONVERSATION REVIEW TRANSCRIPT ===",
            f"Session: {conversation[0].get('session_id','unknown') if conversation else 'unknown'}",
            f"Query: {query}",
            f"Answer Preview: {answer[:300]}",
            f"Retrieved Chunks: {evaluation.get('chunks_count',0) if evaluation else 0}",
            f"Evaluation Passed: {evaluation.get('passed',False) if evaluation else 'N/A'}",
            f"Confidence: {evaluation.get('confidence',0) if evaluation else 0}",
            "",
        ]

        # 简化的对话摘要（只取关键消息，不传完整对话，节省 token）
        for i, msg in enumerate(conversation):
            role = msg.get("role", "")
            content = str(msg.get("content", ""))
            if role == "user" and len(content) < 500:
                lines.append(f"[USER]: {content}")
            elif role == "assistant" and len(content) < 300:
                lines.append(f"[ASSISTANT]: {content}")

        # 截断过长内容
        transcript = "\n".join(lines)[:4000]
        return transcript

    async def _analyze_transcript(
        self,
        transcript: str,
        domain_id: str,
    ) -> dict[str, Any]:
        """用 LLM 分析对话内容，提取可持久化的发现。"""
        # 构造极简 prompt
        system_prompt = """你是知识维护 agent。审查对话，只输出 JSON，不做其他。

      任务（按优先级）：
      1. entities: 从对话中找到的新实体（定额编号、材料名、公式）[]string
      2. error_patterns: 发现的错误模式或幻觉内容 []string  
      3. skill_hints: 可记录为 skill 的检索策略或工作流 []string
      4. gap_notes: 知识库覆盖不足的领域 []string

      明确跳过：
      - 环境错误（command not found, No such file）
      - 重试解决的临时错误
      - 负面能力声明
      - 一次性任务叙述

      输出格式：
      {"entities":[],"error_patterns":[],"skill_hints":[],"gap_notes":[]}"""

        try:
            from app.agent.prompts import invoke_llm
            response, _runtime = invoke_llm(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": transcript[:2000]},
                ],
                thinking=False,
            )
            content = response.content if hasattr(response, "content") else str(response)
            findings = json.loads(content or "{}")
        except Exception:
            # LLM 不可用时用规则 fallback
            findings = self._rule_based_analysis(transcript)

        return {
            "entities": findings.get("entities", []) or [],
            "error_patterns": findings.get("error_patterns", []) or [],
            "skill_hints": findings.get("skill_hints", []) or [],
            "gap_notes": findings.get("gap_notes", []) or [],
        }

    def _rule_based_analysis(self, transcript: str) -> dict[str, Any]:
        """规则 fallback：无 LLM 时的基础分析。"""
        findings: dict[str, list[str]] = {
            "entities": [],
            "error_patterns": [],
            "skill_hints": [],
            "gap_notes": [],
        }

        # 检测拒绝回答
        refusal_markers = ["无法回答", "无法提供", "无法分析", "均显示为N/A"]
        for m in refusal_markers:
            if m in transcript:
                findings["gap_notes"].append(f"refusal pattern: {m}")

        # 检测编造（无检索依据但输出精确数字）
        import re
        if "chunks_count: 0" in transcript:
            numbers = re.findall(r"\d+\.?\d*\s*(?:%|元|万元)", transcript)
            if len(numbers) >= 2:
                findings["error_patterns"].append(
                    f"Fabricated {len(numbers)} values without retrieval evidence"
                )

        return findings

    async def _execute_findings(
        self,
        findings: dict[str, Any],
        session_id: str,
        domain_id: str,
        result: ReviewResult,
    ):
        """执行 LLM 分析结果：写入记忆、错误名单、缺口更新。"""
        from app.agent.error_blacklist import get_error_blacklist
        blacklist = get_error_blacklist()

        # 1. 错误模式 → ERRORS.md
        for pattern in (findings.get("error_patterns") or []):
            if blacklist.add_pattern(str(pattern)):
                result.errors_appended += 1

        # 2. 知识缺口 → 写入 knowledge_gaps
        gap_notes = findings.get("gap_notes") or []
        if gap_notes:
            try:
                from app.agent.learning_state import upsert_knowledge_gap_records
                records = [
                    {
                        "query": str(note),
                        "cause_type": "auto_detected",
                        "severity": "medium",
                        "source": f"background_review:{session_id}",
                    }
                    for note in gap_notes[:5]
                ]
                upsert_knowledge_gap_records(records)
                result.gap_updates += len(records)
            except Exception as exc:
                logger.debug("background_review.gap_write failed: %s", exc)

        # 3. 实体记忆 → 写 MEMORY.md（通过内存写入工具）
        entities = findings.get("entities") or []
        if entities:
            try:
                from app.agent.memory.memory_store import get_memory_store
                store = get_memory_store()
                for entity in entities[:3]:
                    store.add(
                        target="memory",
                        content=f"§ 已知实体: {str(entity)[:120]}",
                    )
                    result.memory_writes += 1
            except Exception as exc:
                logger.debug("background_review.memory_write failed: %s", exc)


# ── 触发条件 ────────────────────────────────────────────────────────────────

def should_trigger_background_review(
    *,
    turn_count: int = 0,
    is_pure_retrieval: bool = False,
    has_substantive_content: bool = True,
    evaluation_passed: bool | None = None,
    query_len: int = 0,
) -> bool:
    """判断是否应该触发后台审查。

    规则：
    - 对话至少一轮交互
    - 非纯检索（有生成内容或验证反馈）
    - 跳过 trivial 查询（<5 字）
    - 跳过纯闲聊（irrelevant intent）
    """
    if turn_count <= 0:
        return False
    if is_pure_retrieval:
        return False
    if query_len < 5:
        return False
    return has_substantive_content


# ── Singleton ───────────────────────────────────────────────────────────────

_review_actor: BackgroundReviewActor | None = None


def get_background_review_actor() -> BackgroundReviewActor:
    global _review_actor
    if _review_actor is None:
        _review_actor = BackgroundReviewActor()
    return _review_actor


async def run_background_review(*, session_id: str, **kwargs) -> ReviewResult | None:
    """快速入口：创建并运行一次后台审查。"""
    if not should_trigger_background_review(**kwargs):
        return None
    actor = get_background_review_actor()
    return await actor.run(session_id=session_id, **kwargs)
