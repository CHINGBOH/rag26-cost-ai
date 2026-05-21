"""
#165: 三层 Prompt 体系（STABLE / CONTEXT / VOLATILE）

参考 Hermes `agent/prompt_builder.py` 的分层设计：
- STABLE:  缓存友好的不变层（系统身份、格式规则、核心指令）
- CONTEXT: 会话状态层（记忆、技能、之前的对话知识）
- VOLATILE: 每轮变化层（用户问题、当前检索结果）

优势：
1. Anthropic prompt prefix caching — STABLE 层不变 → 输入 token 节省 ~75%
2. 分层组装 — 每层独立维护，注入时机不同
3. 缓存安全 — STABLE 层 byte-identical，不随会话状态漂移
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── Layer builders ──────────────────────────────────────────────────────────

def build_stable_layer() -> str:
    """STABLE 层：永远不变，缓存友好的系统身份 + 格式规则。

    Rules:
    - 禁止在这里放用户偏好、会话状态、动态内容
    - 任何改动都必须经过仔细 review（会 invalidate 所有会话的 prefix cache）
    - 字节序必须确定：无 dict 遍历、无随机、无时间戳
    """
    return """你是工程造价知识库问答助手。根据提供的检索结果回答用户问题。

格式要求（强制）：
- 禁止使用 Markdown 格式符号，包括 # ## ### * ** ` ``` | --- 等
- 用中文标点和换行组织结构，不用横线、星号、井号
- 回答结构：先说结论，再给论据，最后标来源
- 禁止写任何分段小标题，包括但不限于：核心结论、总结、简要分析、适用范围、适用边界、公式推导、关键信息、计量方式、数据来源、补充说明
- 你只需输出连续的段落文本，不要用任何标题行分割内容
- 来源用【chunk_id】标注在数值之后，例如：建筑工程推荐费率为3.68%【fr_7】

内容规则：
1. 严格基于检索结果，不编造数值
2. 数值必须来自原文，引用标注紧跟数值
3. 检索结果不足时直接说明找不到，不猜测
4. 对比类问题必须给出"一致"或"不一致"的明确结论

回答示例（注意无 Markdown）：
用户：总包管理服务费费率是多少？
助手：总包管理服务费费率参考范围为1.5%至3.5%，推荐使用2.5%【page_4】。计算基数为分包工程含税建安工程造价【doc_p6】。

用户：2023版与2025版利润率是否一致？
助手：两版利润率范围一致，均为3%～7%，推荐费率均为5%【chunk_x】【chunk_y】。"""


def build_context_layer(
    *,
    memory_entries: Optional[list[dict[str, Any]]] = None,
    skill_names: Optional[list[str]] = None,
    has_knowledge_gaps: bool = False,
) -> str:
    """CONTEXT 层：会话级上下文，随 memory/skills 变化。

    每次 memory 写入或 skill 切换时重建。
    """
    parts: list[str] = []

    # 记忆片段（来自 MEMORY.md / USER.md）
    if memory_entries:
        mem_text = "\n".join(
            f"- {e.get('content', '')}" for e in memory_entries[:5]
        )
        if mem_text.strip():
            parts.append(f"当前记忆：\n{mem_text}")

    # 加载的技能
    if skill_names:
        parts.append(f"已加载技能：{', '.join(skill_names[:8])}")

    # 知识缺口警告
    if has_knowledge_gaps:
        parts.append(
            "注意：系统检测到知识缺口。如果检索结果包含缺口相关信息，"
            "请在回答后标注是否可以填补该缺口。"
        )

    return "\n\n".join(parts) if parts else ""


def build_volatile_layer(
    *,
    query: str,
    chunks: Optional[list[dict[str, Any]]] = None,
    query_type: str = "semantic",
    error_patterns: Optional[list[str]] = None,
) -> str:
    """VOLATILE 层：每轮变化，包含用户问题和当前检索结果。

    这层永远放在最末尾，确保 STABLE + CONTEXT 的缓存前缀不受影响。
    """
    parts: list[str] = [f"用户问题：{query}"]

    # 检索结果
    if chunks:
        chunk_texts = []
        for i, c in enumerate(chunks[:10]):
            content = str(c.get("content") or c.get("text") or "")
            source = c.get("doc_filename") or c.get("source") or ""
            score = c.get("score") or c.get("_distance") or ""
            chunk_id = c.get("chunk_id") or f"chunk_{i}"
            chunk_texts.append(
                f"[{chunk_id}] (来源: {source}, 相关度: {score})\n{content}"
            )
        if chunk_texts:
            parts.append(f"检索结果（共{len(chunks)}条，展示前{len(chunk_texts)}条）：\n" + "\n---\n".join(chunk_texts))
    else:
        parts.append("检索结果：暂无相关依据。如果无法回答，请明确说明而不是编造内容。")

    # 幻觉黑名单注入
    if error_patterns:
        patterns_text = "\n".join(f"- {p}" for p in error_patterns[:5])
        parts.append(f"已知幻觉模式（禁止生成以下内容）：\n{patterns_text}")

    return "\n\n".join(parts)


# ── Builder ─────────────────────────────────────────────────────────────────

class ThreeLayerPromptBuilder:
    """三层 Prompt 组装器。

    使用方式：
        builder = ThreeLayerPromptBuilder()
        messages = builder.build(query="...", chunks=[...])
        # messages = [{"role": "system", "content": stable},
        #             {"role": "system", "content": context},
        #             {"role": "user", "content": volatile}]
    """

    def __init__(self):
        self._stable_cache: Optional[str] = None
        self._context_cache: Optional[str] = None
        self._context_hash: Optional[str] = None

    def _get_stable(self) -> str:
        if self._stable_cache is None:
            self._stable_cache = build_stable_layer()
        return self._stable_cache

    def _get_context(
        self,
        *,
        memory_entries: Optional[list] = None,
        skill_names: Optional[list] = None,
        has_knowledge_gaps: bool = False,
    ) -> str:
        # Hash the inputs to detect context changes
        import hashlib, json
        ctx_hash_input = json.dumps(
            {
                "memory": memory_entries or [],
                "skills": skill_names or [],
                "gaps": has_knowledge_gaps,
            },
            sort_keys=True,
            default=str,
        )
        new_hash = hashlib.md5(ctx_hash_input.encode()).hexdigest()

        if self._context_hash != new_hash or self._context_cache is None:
            self._context_cache = build_context_layer(
                memory_entries=memory_entries,
                skill_names=skill_names,
                has_knowledge_gaps=has_knowledge_gaps,
            )
            self._context_hash = new_hash

        return self._context_cache

    def build(
        self,
        *,
        query: str,
        chunks: Optional[list[dict[str, Any]]] = None,
        query_type: str = "semantic",
        memory_entries: Optional[list[dict[str, Any]]] = None,
        skill_names: Optional[list[str]] = None,
        has_knowledge_gaps: bool = False,
        error_patterns: Optional[list[str]] = None,
    ) -> list[dict[str, str]]:
        """组装完整的三层 messages 列表。"""
        messages: list[dict[str, str]] = []

        stable = self._get_stable()
        if stable.strip():
            messages.append({"role": "system", "content": stable})

        context = self._get_context(
            memory_entries=memory_entries,
            skill_names=skill_names,
            has_knowledge_gaps=has_knowledge_gaps,
        )
        if context.strip():
            messages.append({"role": "system", "content": context})

        volatile = build_volatile_layer(
            query=query,
            chunks=chunks,
            query_type=query_type,
            error_patterns=error_patterns,
        )
        messages.append({"role": "user", "content": volatile})

        return messages

    def invalidate_context(self):
        """强制下次 build 时重建 CONTEXT 层。"""
        self._context_cache = None
        self._context_hash = None

    def invalidate_stable(self):
        """强制重建 STABLE 层（慎用 — invalidate 所有 cache）。"""
        self._stable_cache = None


# ── Singleton ───────────────────────────────────────────────────────────────

_prompt_builder: Optional[ThreeLayerPromptBuilder] = None


def get_prompt_builder() -> ThreeLayerPromptBuilder:
    global _prompt_builder
    if _prompt_builder is None:
        _prompt_builder = ThreeLayerPromptBuilder()
    return _prompt_builder
