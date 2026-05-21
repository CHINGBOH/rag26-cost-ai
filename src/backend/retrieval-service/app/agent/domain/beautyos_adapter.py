"""
#172: BeautyOS Domain Adapter — LSP + Log Tail 验证器

实现 DomainAdapter 接口的第二个 Adapter：BeautyOSAdapter。
核心差异：BeautyOS 是代码仓库场景，需要 LSP 验证 + 执行日志检查。

验证流水线：
  write_code → pyright LSP check → fix errors → run tests → tail logs → verify
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """代码 + 逻辑双重验证结果。"""
    passed: bool = False
    lsp_errors: list[dict[str, Any]] = field(default_factory=list)
    lsp_warnings: list[dict[str, Any]] = field(default_factory=list)
    run_exit_code: int | None = None
    run_stdout: str = ""
    run_stderr: str = ""
    log_errors: list[str] = field(default_factory=list)
    log_warnings: list[str] = field(default_factory=list)
    duration_ms: float = 0

    def summary(self) -> str:
        parts = []
        if self.lsp_errors:
            parts.append(f"LSP: {len(self.lsp_errors)} errors")
        if self.log_errors:
            parts.append(f"Log: {len(self.log_errors)} errors")
        if self.passed:
            parts.append("VALIDATION PASSED")
        else:
            parts.append("VALIDATION FAILED")
        return " | ".join(parts) if parts else "no results"


class BeautyOSAdapter:
    """BeautyOS 代码仓库场景的适配器。

    实现 DomainAdapter 接口：
    - validate(): LSP 类型检查 + 执行 + 日志验证
    - extract_entities(): 从代码中提取函数、类、类型
    - get_context(): 返回当前代码库上下文
    """

    def __init__(self, repo_path: str | Path | None = None):
        self.repo_path = Path(repo_path) if repo_path else None
        self._lsp_available = self._check_lsp()

    @staticmethod
    def _check_lsp() -> bool:
        """检查 LSP 工具是否可用。"""
        try:
            result = subprocess.run(
                ["pyright", "--version"],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    # ── DomainAdapter: validate ───────────────────────────────────────

    async def validate(
        self,
        *,
        file_path: str | None = None,
        code: str = "",
        test_command: str = "",
        watch_error_patterns: list[str] | None = None,
    ) -> ValidationResult:
        """完整验证流水线：LSP → 执行 → 日志检查。

        1. 如果提供了 code，写入临时文件
        2. 运行 pyright LSP 类型检查
        3. 如果有 test_command，执行并 tail 日志
        4. 扫描日志中的错误模式
        """
        import time as _time
        t0 = _time.monotonic()
        result = ValidationResult()

        watch_patterns = watch_error_patterns or [
            "ERROR", "FAIL", "Traceback", "Error:", "TypeError",
            "AttributeError", "NameError", "AssertionError",
        ]

        target = Path(file_path) if file_path else None

        # 写入临时代码
        if code and not target:
            fd, tmp_path = tempfile.mkstemp(suffix=".py", prefix="beautyos_")
            with os.fdopen(fd, "w") as f:
                f.write(code)
            target = Path(tmp_path)

        if not target or not target.exists():
            result.passed = False
            result.duration_ms = (_time.monotonic() - t0) * 1000
            return result

        # ── Step 1: LSP 类型检查 ──
        if self._lsp_available:
            await self._run_lsp_check(target, result)

        # 如果有 LSP 错误，提前返回
        if result.lsp_errors and not result.lsp_warnings:
            result.passed = False
            result.duration_ms = (_time.monotonic() - t0) * 1000
            return result

        # ── Step 2: 执行 + 日志验证 ──
        if test_command:
            await self._run_and_tail_logs(test_command, watch_patterns, result)

        result.passed = (
            len(result.lsp_errors) == 0
            and len(result.log_errors) == 0
            and result.run_exit_code == 0
        )
        result.duration_ms = (_time.monotonic() - t0) * 1000

        logger.info(
            "beautyos.validate %s lsp=%d/%d log=%d/%d exit=%s time=%.0fms",
            "PASS" if result.passed else "FAIL",
            len(result.lsp_errors), len(result.lsp_warnings),
            len(result.log_errors), len(result.log_warnings),
            result.run_exit_code, result.duration_ms,
        )

        return result

    async def _run_lsp_check(self, target: Path, result: ValidationResult):
        """运行 pyright LSP 检查，将结果填入 result。"""
        try:
            proc = subprocess.run(
                ["pyright", str(target), "--outputjson"],
                capture_output=True, text=True,
                timeout=30,
                cwd=str(target.parent) if target.parent else None,
            )
            output = proc.stdout.strip()
            if output:
                data = json.loads(output)
                diagnostics = data.get("generalDiagnostics", [])
                for d in diagnostics:
                    entry = {
                        "file": d.get("file", str(target)),
                        "line": d["range"]["start"]["line"] + 1,
                        "message": d.get("message", ""),
                        "severity": d.get("severity", "error"),
                        "rule": d.get("rule", ""),
                    }
                    if d.get("severity") == "error":
                        result.lsp_errors.append(entry)
                    else:
                        result.lsp_warnings.append(entry)
        except subprocess.TimeoutExpired:
            result.lsp_errors.append({
                "file": str(target), "line": 0,
                "message": "LSP check timed out (30s)",
                "severity": "error",
            })
        except json.JSONDecodeError:
            pass  # pyright output not JSON — ignore
        except FileNotFoundError:
            self._lsp_available = False

    async def _run_and_tail_logs(
        self,
        command: str,
        patterns: list[str],
        result: ValidationResult,
    ):
        """执行命令并 tail 日志，扫描错误模式。"""
        import tempfile

        # 写日志到临时文件
        fd, log_path = tempfile.mkstemp(suffix=".log", prefix="beautyos_run_")
        os.close(fd)

        try:
            # 重定向到日志文件
            wrapped = f"{command} > {log_path} 2>&1"

            proc = subprocess.run(
                wrapped, shell=True,
                capture_output=True, text=True,
                timeout=60,
            )
            result.run_exit_code = proc.returncode
            result.run_stdout = proc.stdout[:2000]
            result.run_stderr = proc.stderr[:500]

            # 读日志并扫描错误模式
            if os.path.exists(log_path):
                log_content = Path(log_path).read_text(encoding="utf-8", errors="replace")
                for line in log_content.splitlines():
                    for pat in patterns:
                        if pat.lower() in line.lower():
                            if pat in ("ERROR", "FAIL", "Error:", "Traceback"):
                                result.log_errors.append(line[:300])
                            else:
                                result.log_warnings.append(line[:300])
                            break

                # 只保留前 20 条
                result.log_errors = result.log_errors[:20]
                result.log_warnings = result.log_warnings[:20]

        except subprocess.TimeoutExpired:
            result.run_exit_code = -1
            result.log_errors.append("Command timed out (60s)")
        finally:
            if os.path.exists(log_path):
                try:
                    os.unlink(log_path)
                except OSError:
                    pass

    # ── DomainAdapter: extract_entities ────────────────────────────────

    async def extract_entities(self, code: str) -> list[dict[str, Any]]:
        """从代码中提取函数、类、类型定义。"""
        import ast

        entities: list[dict[str, Any]] = []
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    entities.append({
                        "type": "function",
                        "name": node.name,
                        "lineno": node.lineno,
                        "args": [a.arg for a in node.args.args],
                    })
                elif isinstance(node, ast.ClassDef):
                    entities.append({
                        "type": "class",
                        "name": node.name,
                        "lineno": node.lineno,
                    })
        except SyntaxError as exc:
            entities.append({
                "type": "syntax_error",
                "message": str(exc),
                "lineno": exc.lineno or 0,
            })
        return entities

    # ── DomainAdapter: get_context ─────────────────────────────────────

    def get_context(self) -> dict[str, Any]:
        """返回当前代码库上下文。"""
        ctx: dict[str, Any] = {
            "lsp_available": self._lsp_available,
        }
        if self.repo_path and self.repo_path.exists():
            ctx["repo_path"] = str(self.repo_path)
            ctx["files"] = len(list(self.repo_path.rglob("*.py")))
        return ctx


# ── Singleton ───────────────────────────────────────────────────────────────

_beautyos_adapter: BeautyOSAdapter | None = None


def get_beautyos_adapter(repo_path: str | None = None) -> BeautyOSAdapter:
    global _beautyos_adapter
    if _beautyos_adapter is None:
        _beautyos_adapter = BeautyOSAdapter(repo_path=repo_path)
    return _beautyos_adapter
