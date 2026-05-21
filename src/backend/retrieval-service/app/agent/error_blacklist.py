"""
#166: ERRORS.md 幻觉黑名单 + 注入扫描

持久化已知幻觉模式到 ERRORS.md 文件，每次生成回答前从 STABLE 层注入。
当同类模式出现 ≥3 次时自动晋升到黑名单。

参考 Hermes `AGENTS.md` 的 HOOD AGENT 审计规则：
- 拒绝回答模式（无法回答、无法提供等）
- 编造数值模式（没有检索依据的精确数字）
- 来源伪造模式（引用不存在的 chunk_id）

防注入规则：
- 写入前扫描注入攻击（ignore instructions、disregard rules 等）
- 禁止不可见 Unicode（零宽字符、BOM、方向覆盖符）
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ERRORS_PATH = Path(__file__).resolve().parents[5] / "config" / "ERRORS.md"

# ── 注入攻击扫描 ────────────────────────────────────────────────────────────

_THREAT_PATTERNS = [
    (r"ignore\s+(?:\w+\s+)*(?:previous|all|above|prior)\s+(?:\w+\s+)*instructions", "prompt_injection"),
    (r"do\s+not\s+tell\s+the\s+user", "deception"),
    (r"system\s+prompt\s+override", "sys_prompt_override"),
    (r"disregard\s+(your|all|any)\s+(instructions|rules|guidelines)", "disregard_rules"),
]

_INVISIBLE_CHARS = {
    "\u200b", "\u200c", "\u200d", "\u2060", "\ufeff",
    "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",
}

# ── 幻觉模式库 ──────────────────────────────────────────────────────────────

# 拒绝回答模式（从 AGENTS.md HOOD AGENT 继承）
REFUSAL_PATTERNS = [
    "无法直接回答", "无法回答", "无法提供", "无法分析",
    "无法对比", "无法计算", "不足以回答",
    "均显示为N/A", "无相关数据", "无法得出", "无法给出",
]

# 编造数值模式
FABRICATION_PATTERNS = [
    "根据行业惯例",
    "通常为",
    "一般为",
    "大概",
    "约在",
    "估计",
]


class ErrorBlacklist:
    """幻觉黑名单管理器。"""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or ERRORS_PATH
        self._patterns: list[str] = []
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        try:
            text = self.path.read_text(encoding="utf-8")
            self._patterns = [
                line.strip()
                for line in text.splitlines()
                if line.strip() and not line.startswith("#")
            ]
        except Exception as exc:
            logger.warning("Failed to load ERRORS.md: %s", exc)

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            content = "# ERRORS.md — 已知幻觉模式黑名单\n"
            content += f"# 最后更新: {datetime.now(timezone.utc).isoformat()}\n\n"
            for p in self._patterns:
                content += f"- {p}\n"
            self.path.write_text(content, encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to save ERRORS.md: %s", exc)

    def _sanitize(self, text: str) -> str:
        """防注入：扫描并清理危险内容。"""
        for char in _INVISIBLE_CHARS:
            text = text.replace(char, "")
        for pattern, threat_id in _THREAT_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                logger.warning("ERRORS.md injection blocked: pattern=%s", threat_id)
                return ""
        return text.strip()

    def add_pattern(self, pattern: str) -> bool:
        """添加一个新幻觉模式（需通过注入扫描）。"""
        cleaned = self._sanitize(pattern)
        if not cleaned:
            return False
        if cleaned in self._patterns:
            return False
        self._patterns.append(cleaned)
        self._save()
        logger.info("ERRORS.md: added pattern: %s", cleaned[:80])
        return True

    def get_active_patterns(self) -> list[str]:
        """返回当前活跃的黑名单模式。"""
        return list(self._patterns)

    def scan_answer(self, answer: str) -> list[str]:
        """扫描回答中是否包含已知幻觉模式，返回匹配的模式列表。"""
        matches: list[str] = []
        for p in self._patterns:
            if p in answer:
                matches.append(p)
        return matches


# ── 自动检测：从回答中提取新幻觉模式 ───────────────────────────────────────

def detect_new_refusal_patterns(answer: str) -> list[str]:
    """从回答中自动提取候选拒绝模式。"""
    patterns = []
    for pat in REFUSAL_PATTERNS:
        if pat in answer and pat not in patterns:
            patterns.append(pat)
    return patterns


def detect_fabrication_patterns(answer: str, chunks: list[dict]) -> list[str]:
    """检测编造证据：无 chunks 但包含精确数值。"""
    if chunks:
        return []
    # 无检索结果但包含精确数字 → 编造
    numeric_matches = re.findall(r"\d+\.?\d*\s*(?:%|元|万元|万|m³|m2|kg|吨)", answer)
    if len(numeric_matches) >= 2:
        return [f"无检索依据但输出{len(numeric_matches)}个精确数值：{', '.join(numeric_matches[:3])}"]
    return []


# ── Singleton ───────────────────────────────────────────────────────────────

_blacklist: Optional[ErrorBlacklist] = None


def get_error_blacklist() -> ErrorBlacklist:
    global _blacklist
    if _blacklist is None:
        _blacklist = ErrorBlacklist()
    return _blacklist
