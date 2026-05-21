"""
#169: Working Memory — MEMORY.md + USER.md 双文件记忆

参考 Hermes `tools/memory_tool.py` 的精确实现。
提供轻量跨会话工作记忆，独立于 Qdrant 向量库。

双文件语义：
- MEMORY.md (上限 2,200 字符): agent 的操作知识、实体列表、环境约定
- USER.md   (上限 1,375 字符): 用户画像、偏好、专业背景
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

MemoryTarget = Literal["memory", "user"]

# 路径
MEMORY_ROOT = Path("~/.agent/memory").expanduser()
MEMORY_MD_PATH = MEMORY_ROOT / "MEMORY.md"
USER_MD_PATH = MEMORY_ROOT / "USER.md"

# 容量上限（字节数）
MEMORY_MD_MAX_CHARS = 2_200
USER_MD_MAX_CHARS = 1_375

# 条目分隔符
ENTRY_SEPARATOR = "\n§\n"

# 注入扫描器 - 与 error_blacklist 保持一致
_INJECTION_PATTERNS = [
    (r"ignore\s+(?:\w+\s+)*(?:previous|all|above|prior)\s+(?:\w+\s+)*instructions", "prompt_injection"),
    (r"system\s+prompt\s+override", "sys_override"),
]


class MemoryStore:
    """双文件工作记忆存储。"""

    def __init__(self):
        self._memory_entries: list[str] = []
        self._user_entries: list[str] = []
        self._snapshot: str = ""
        self._loaded = False

    # ── 加载 ────────────────────────────────────────────────────────────

    def load_from_disk(self):
        """从磁盘加载两个文件，构建初始条目列表。"""
        MEMORY_ROOT.mkdir(parents=True, exist_ok=True)
        self._memory_entries = self._read_file(MEMORY_MD_PATH)
        self._user_entries = self._read_file(USER_MD_PATH)
        self._snapshot = self._build_snapshot()
        self._loaded = True
        logger.info(
            "memory_store.loaded memory=%d user=%d chars=%d",
            len(self._memory_entries), len(self._user_entries),
            len(self._snapshot),
        )

    @staticmethod
    def _read_file(path: Path) -> list[str]:
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8")
        return [e.strip() for e in text.split(ENTRY_SEPARATOR) if e.strip()]

    # ── 保存 ────────────────────────────────────────────────────────────

    def save_to_disk(self, target: MemoryTarget):
        """原子写入到目标文件。"""
        path = MEMORY_MD_PATH if target == "memory" else USER_MD_PATH
        entries = self._memory_entries if target == "memory" else self._user_entries

        path.parent.mkdir(parents=True, exist_ok=True)
        content = ENTRY_SEPARATOR.join(entries)
        if content:
            content += "\n"

        # 原子写入
        fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, str(path))
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    # ── CRUD ────────────────────────────────────────────────────────────

    def _injection_scan(self, content: str) -> str | None:
        """返回错误字符串如果检测到注入攻击，否则 None。"""
        for pattern, threat_id in _INJECTION_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                return f"Blocked: pattern '{threat_id}'"
        invisible = {"\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"}
        if any(c in content for c in invisible):
            return "Blocked: invisible Unicode characters detected"
        return None

    def _check_capacity(self, target: MemoryTarget, new_entry: str) -> str | None:
        """检查添加后是否超过容量上限。"""
        entries = self._memory_entries if target == "memory" else self._user_entries
        max_chars = MEMORY_MD_MAX_CHARS if target == "memory" else USER_MD_MAX_CHARS

        current = sum(len(e) for e in entries) + len(ENTRY_SEPARATOR) * max(len(entries) - 1, 0)
        if current + len(new_entry) + len(ENTRY_SEPARATOR) > max_chars:
            return (
                f"Capacity exceeded: {target}={current + len(new_entry)}"
                f" > max={max_chars}"
            )
        return None

    def _get_entries(self, target: MemoryTarget) -> list[str]:
        return self._memory_entries if target == "memory" else self._user_entries

    def _set_entries(self, target: MemoryTarget, entries: list[str]):
        if target == "memory":
            self._memory_entries = entries
        else:
            self._user_entries = entries

    def add(self, target: MemoryTarget, content: str) -> dict[str, Any]:
        """添加新条目。

        1. 注入扫描
        2. 容量检查
        3. 去重（子字符串匹配）
        4. 追加 + 存储
        """
        content = content.strip()
        if not content:
            return {"ok": False, "error": "Empty content"}

        scan_error = self._injection_scan(content)
        if scan_error:
            return {"ok": False, "error": scan_error}

        cap_error = self._check_capacity(target, content)
        if cap_error:
            return {"ok": False, "error": cap_error}

        entries = self._get_entries(target)
        # 去重：检查是否已有高度相似条目
        for existing in entries:
            if content[:40] in existing or existing[:40] in content:
                return {"ok": False, "error": "Duplicate entry detected"}

        entries.append(content)
        self._set_entries(target, entries)
        self.save_to_disk(target)

        logger.info(
            "memory_store.add target=%s chars=%d total=%d",
            target, len(content), len(entries),
        )
        return {"ok": True, "count": len(entries)}

    def replace(self, target: MemoryTarget, old_text: str, new_content: str) -> dict[str, Any]:
        """替换已有条目（子字符串匹配）。"""
        entries = self._get_entries(target)
        for i, entry in enumerate(entries):
            if old_text in entry:
                scan_error = self._injection_scan(new_content)
                if scan_error:
                    return {"ok": False, "error": scan_error}
                entries[i] = new_content.strip()
                self._set_entries(target, entries)
                self.save_to_disk(target)
                return {"ok": True, "replaced_index": i}
        return {"ok": False, "error": f"No entry containing '{old_text[:40]}'"}

    def remove(self, target: MemoryTarget, old_text: str) -> dict[str, Any]:
        """删除匹配条目（子字符串匹配）。"""
        entries = self._get_entries(target)
        for i, entry in enumerate(entries):
            if old_text in entry:
                removed = entries.pop(i)
                self._set_entries(target, entries)
                self.save_to_disk(target)
                return {"ok": True, "removed": removed[:80]}
        return {"ok": False, "error": f"No entry containing '{old_text[:40]}'"}

    # ── 快照 ────────────────────────────────────────────────────────────

    def _build_snapshot(self) -> str:
        """构建注入 CONTEXT 层的快照文本。"""
        parts: list[str] = []

        if self._memory_entries:
            parts.append(f"MEMORY ({len(self._memory_entries)} entries, {sum(len(e) for e in self._memory_entries)} chars):")
            for e in self._memory_entries:
                parts.append(f"  - {e[:200]}")

        if self._user_entries:
            parts.append(f"USER PROFILE ({len(self._user_entries)} entries, {sum(len(e) for e in self._user_entries)} chars):")
            for e in self._user_entries:
                parts.append(f"  - {e[:200]}")

        return "\n".join(parts) if parts else ""

    def get_snapshot(self) -> str:
        """返回会话开始时的冻结快照（注入 CONTEXT 层）。

        不会随当前会话中的 memory 操作而变化——保证预取缓存稳定性。
        """
        if not self._loaded:
            self.load_from_disk()
        return self._snapshot

    def get_current(self, target: MemoryTarget) -> str:
        """返回当前内容（Background Review 写入后立即可读）。"""
        entries = self._get_entries(target)
        return ENTRY_SEPARATOR.join(entries) if entries else ""

    def has_items(self) -> bool:
        return bool(self._memory_entries or self._user_entries)


# ── 跨会话搜索 (SQLite FTS5) ────────────────────────────────────────────────

MEMORY_DB_PATH = MEMORY_ROOT / "memory.db"


class SessionSearch:
    """基于 SQLite FTS5 的跨会话搜索引擎。"""

    def __init__(self):
        self._db_path = MEMORY_DB_PATH
        self._ensure_db()

    def _ensure_db(self):
        import sqlite3
        MEMORY_ROOT.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(
                session_id, query, answer, content
            )
        """)
        conn.commit()
        conn.close()

    def index_session(self, session_id: str, query: str, answer: str):
        """索引一次对话到 FTS5。"""
        import sqlite3
        conn = sqlite3.connect(str(self._db_path))
        conn.execute(
            "INSERT INTO sessions_fts(session_id, query, answer, content) VALUES(?,?,?,?)",
            (session_id, query, answer, f"{query} {answer[:500]}")
        )
        conn.commit()
        conn.close()

    def search(self, query_text: str, limit: int = 5) -> list[dict[str, Any]]:
        """FTS5 全文搜索历史对话。"""
        import sqlite3
        conn = sqlite3.connect(str(self._db_path))
        try:
            cursor = conn.execute(
                "SELECT session_id, query, snippet(sessions_fts, 2, '<b>', '</b>', '...', 40) "
                "FROM sessions_fts WHERE sessions_fts MATCH ? ORDER BY rank LIMIT ?",
                (query_text, limit)
            )
            results = [
                {"session_id": row[0], "query": row[1], "snippet": row[2]}
                for row in cursor.fetchall()
            ]
        except sqlite3.OperationalError:
            results = []
        conn.close()
        return results


# ── Singleton ───────────────────────────────────────────────────────────────

_memory_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryStore()
        _memory_store.load_from_disk()
    return _memory_store
