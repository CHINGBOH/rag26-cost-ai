"""
#171: SKILL.md 过程记忆系统

每个 skill 是一个目录，核心是 SKILL.md 文件（YAML frontmatter + Markdown body）。
Agent 可以在运行时创建、修改、调用 skill。支持分类、缓存、归档。

参考 Hermes `skill_manage` 和 `skill_view` 工具实现。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

SKILLS_ROOT = Path("~/.agent/skills").expanduser()
SKILLS_CACHE_MAX = 8


# ── Skill Meta ─────────────────────────────────────────────────────────────

@dataclass
class SkillMeta:
    name: str
    description: str = ""
    domain: str = "general"
    platforms: list[str] = field(default_factory=lambda: ["linux"])
    created_by: str = "agent"
    created_at: str = ""
    last_used_at: str = ""
    use_count: int = 0
    archived: bool = False
    _skill_dir: Path | None = None

    @property
    def skill_dir(self) -> Path | None:
        return self._skill_dir

    @property
    def is_agent_created(self) -> bool:
        return self.created_by == "agent"


# ── Skill Manager ──────────────────────────────────────────────────────────

class SkillManager:
    """SKILL.md 生命周期管理器。"""

    def __init__(self, root: Path | None = None):
        self._root = root or SKILLS_ROOT
        self._index: dict[str, dict[str, SkillMeta]] = {}  # domain_id -> {name: meta}
        self._mtime_cache: dict[str, float] = {}

    # ── 扫描 ─────────────────────────────────────────────────────────

    def scan(self, domain_id: str) -> dict[str, SkillMeta]:
        """扫描 domain 下的所有 skill 目录，返回索引。

        结果被 LRU 缓存（基于目录 mtime 的增量刷新）。
        """
        domain_dir = self._root / domain_id
        if not domain_dir.exists():
            return {}

        # 增量缓存
        current_mtime = self._dir_mtime(domain_dir)
        if domain_id in self._index and self._mtime_cache.get(domain_id) == current_mtime:
            return self._index[domain_id]

        index: dict[str, SkillMeta] = {}
        self._scan_dir(domain_dir, index, domain_id)
        self._index[domain_id] = index
        self._mtime_cache[domain_id] = current_mtime

        logger.info(
            "skills.scanned domain=%s found=%d",
            domain_id, len(index),
        )
        return index

    def _scan_dir(self, directory: Path, index: dict[str, SkillMeta], domain_id: str):
        for item in sorted(directory.iterdir()):
            if item.name.startswith(".") or item.name == ".archive":
                continue
            if not item.is_dir():
                continue

            skill_md = item / "SKILL.md"
            if skill_md.exists():
                meta = self._parse_skill_md(skill_md, domain_id)
                if meta:
                    meta._skill_dir = item
                    meta.archived = ".archive" in str(item)
                    index[meta.name] = meta

        # 也扫描 .archive 目录
        archive_dir = directory / ".archive"
        if archive_dir.exists():
            for item in sorted(archive_dir.iterdir()):
                if item.name.startswith(".") or not item.is_dir():
                    continue
                skill_md = item / "SKILL.md"
                if skill_md.exists():
                    meta = self._parse_skill_md(skill_md, domain_id)
                    if meta:
                        meta._skill_dir = item
                        meta.archived = True
                        index[f"archived/{meta.name}"] = meta

    @staticmethod
    def _parse_skill_md(path: Path, domain_id: str) -> SkillMeta | None:
        """解析 SKILL.md 的 YAML frontmatter。"""
        try:
            text = path.read_text(encoding="utf-8")
            # 提取 --- frontmatter ---
            match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
            if not match:
                return None

            fm = yaml.safe_load(match.group(1)) or {}
            name = (fm.get("name") or path.parent.name or "").lower().replace(" ", "-")

            return SkillMeta(
                name=name,
                description=str(fm.get("description", "")),
                domain=fm.get("domain", domain_id),
                platforms=fm.get("platforms", ["linux"]),
                created_by=fm.get("created_by", "agent"),
                created_at=str(fm.get("created_at", "")),
                last_used_at=str(fm.get("last_used_at", "")),
                use_count=int(fm.get("use_count", 0)),
            )
        except Exception as exc:
            logger.debug("skills.parse_failed path=%s error=%s", path, exc)
            return None

    @staticmethod
    def _dir_mtime(directory: Path) -> float:
        """目录的聚合 mtime（用于增量缓存判断）。"""
        max_mtime = 0.0
        for item in directory.rglob("*.md"):
            try:
                mtime = item.stat().st_mtime
                if mtime > max_mtime:
                    max_mtime = mtime
            except OSError:
                pass
        return max_mtime

    # ── 读取 ─────────────────────────────────────────────────────────

    @lru_cache(maxsize=SKILLS_CACHE_MAX)
    def load_content(self, skill_name: str, domain_id: str, file_path: str | None = None) -> str:
        """加载 SKILL.md 完整内容，LRU 缓存。"""
        meta = self.scan(domain_id).get(skill_name)
        if not meta or not meta.skill_dir:
            return ""

        target = meta.skill_dir / (file_path or "SKILL.md")
        if not target.exists():
            return ""
        return target.read_text(encoding="utf-8")

    # ── 写入 ─────────────────────────────────────────────────────────

    def create(
        self,
        *,
        domain_id: str,
        name: str,
        description: str,
        content: str,
        category: str = "",
    ) -> dict[str, Any]:
        """创建新 skill 目录 + SKILL.md。"""
        normalized = name.lower().replace(" ", "-").replace("_", "-")
        skill_dir = self._root / domain_id / (category or "") / normalized
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_md_path = skill_dir / "SKILL.md"

        now = datetime.now(timezone.utc).isoformat()
        frontmatter = yaml.dump({
            "name": normalized,
            "description": description,
            "domain": domain_id,
            "platforms": ["linux"],
            "created_by": "agent",
            "created_at": now,
            "last_used_at": now,
            "use_count": 0,
        }, allow_unicode=True, default_flow_style=False).strip()

        full_content = f"---\n{frontmatter}\n---\n\n{content}"
        skill_md_path.write_text(full_content, encoding="utf-8")

        # 刷新索引
        self._mtime_cache.pop(domain_id, None)

        logger.info("skills.created name=%s domain=%s", normalized, domain_id)
        return {"ok": True, "name": normalized, "path": str(skill_md_path)}

    def patch(
        self,
        *,
        domain_id: str,
        name: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> dict[str, Any]:
        """Patch 已有 SKILL.md 内容（find-and-replace）。"""
        meta = self.scan(domain_id).get(name)
        if not meta or not meta.skill_dir:
            return {"ok": False, "error": f"Skill '{name}' not found"}

        skill_md = meta.skill_dir / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")

        if old_string not in text:
            return {"ok": False, "error": "old_string not found in SKILL.md"}

        if replace_all:
            text = text.replace(old_string, new_string)
        else:
            text = text.replace(old_string, new_string, 1)

        skill_md.write_text(text, encoding="utf-8")
        self._bump_use(name, domain_id)
        self.load_content.cache_clear()

        logger.info("skills.patched name=%s domain=%s", name, domain_id)
        return {"ok": True, "name": name}

    def delete(self, domain_id: str, name: str) -> dict[str, Any]:
        """归档 skill（移到 .archive）。"""
        meta = self.scan(domain_id).get(name)
        if not meta or not meta.skill_dir:
            return {"ok": False, "error": f"Skill '{name}' not found"}

        archive_dir = self._root / domain_id / ".archive"
        archive_dir.mkdir(parents=True, exist_ok=True)

        import shutil
        target = archive_dir / meta.skill_dir.name
        if target.exists():
            import uuid
            target = archive_dir / f"{meta.skill_dir.name}-{uuid.uuid4().hex[:6]}"

        shutil.move(str(meta.skill_dir), str(target))
        self._mtime_cache.pop(domain_id, None)

        logger.info("skills.archived name=%s domain=%s", name, domain_id)
        return {"ok": True, "archived": str(target)}

    # ── 索引构建 ─────────────────────────────────────────────────────

    def build_skills_index(self, domain_id: str) -> str:
        """构建注入 STABLE 层的 skills 索引块。"""
        index = self.scan(domain_id)
        active = {k: v for k, v in index.items() if not v.archived}
        if not active:
            return ""

        lines = [
            "## Skills (mandatory)",
            "Before replying, scan the skills below. "
            "If a skill matches or is even partially relevant to your task, "
            "you MUST load it with skill_view(name) and follow its instructions.",
            "",
            "<available_skills>",
        ]
        for name, meta in sorted(active.items()):
            desc = meta.description[:100] if meta.description else "(no description)"
            lines.append(f"  - {name}: {desc}")

        lines.append("</available_skills>")
        return "\n".join(lines)

    def bump_use(self, skill_name: str, domain_id: str):
        """更新 last_used_at 和 use_count。"""
        self._bump_use(skill_name, domain_id)

    def _bump_use(self, skill_name: str, domain_id: str):
        meta = self.scan(domain_id).get(skill_name)
        if not meta or not meta.skill_dir:
            return
        skill_md = meta.skill_dir / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")
        now = datetime.now(timezone.utc).isoformat()
        text = re.sub(
            r"last_used_at:.*", f"last_used_at: {now}", text, count=1
        )
        text = re.sub(
            r"use_count:\s*(\d+)",
            lambda m: f"use_count: {int(m.group(1)) + 1}",
            text, count=1,
        )
        skill_md.write_text(text, encoding="utf-8")


# ── Singleton ───────────────────────────────────────────────────────────────

_skill_manager: SkillManager | None = None


def get_skill_manager() -> SkillManager:
    global _skill_manager
    if _skill_manager is None:
        _skill_manager = SkillManager()
    return _skill_manager
