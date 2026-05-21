"""
CodeExecutionPipeline — unified pre/post guardian for all code execution tools.

Three-phase execution with short-circuit semantics:
  Phase A: pre_validate  — host-side, no Docker startup
  Phase B: sandbox_exec  — language-specific executor (Docker for Python)
  Phase C: post_scan     — pattern-based log analysis regardless of outcome

Consumed by:
  - app/agent/tools.py:python_eval  (Phase 1)
  - #167 Tool Guardrails via audit_id stored in event_ledger
  - #166 ERRORS.md via LogAnalysisResult.inferred_failure_kind
  - #172 BeautyOS Adapter registers TsServerValidator / ReactPatternScanner
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from infrastructure.scanners.log_patterns import LogAnalysisResult, scan_outcome
from infrastructure.validators.python_validators import (
    PreValidationResult,
    run_python_validators,
)

logger = logging.getLogger(__name__)


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class ExecutionPolicy:
    enable_lsp: bool = False            # opt-in: requires pylsp installed
    arithmetic_only: bool = False       # ARITHMETIC_ONLY fast-path (calculator)
    language: str = "python"


@dataclass
class ExecutionRequest:
    code: str
    language: str = "python"
    adapter: str = "python_eval"
    context: Dict[str, Any] = field(default_factory=dict)
    policy: ExecutionPolicy = field(default_factory=ExecutionPolicy)


@dataclass
class ExecutionOutcome:
    status: str                         # "success" | "error" | "timeout" | "oom" | "crash"
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    wall_time_ms: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionResult:
    ok: bool
    phase: str                          # "pre_validate" | "sandbox" | "post_scan" | "done"
    validation: Optional[PreValidationResult] = None
    outcome: Optional[ExecutionOutcome] = None
    analysis: Optional[LogAnalysisResult] = None
    user_message: str = ""
    audit_id: str = field(default_factory=lambda: str(uuid.uuid4()))


# ── Executor protocol ────────────────────────────────────────────────────────

class Executor:
    """Base class for language executors."""

    def run(self, req: ExecutionRequest) -> ExecutionOutcome:
        raise NotImplementedError


class PythonDockerExecutor(Executor):
    """Wraps infrastructure.sandbox.execute_python; returns raw (untruncated) output."""

    def run(self, req: ExecutionRequest) -> ExecutionOutcome:
        from infrastructure.sandbox import execute_python  # lazy import avoids circular deps

        t0 = time.monotonic()
        raw = execute_python(req.code)
        wall_ms = (time.monotonic() - t0) * 1000

        status = raw.get("status", "error")
        stdout = raw.get("output", "") or ""
        stderr = raw.get("traceback", "") or ""
        if status == "success":
            result_line = raw.get("result", "")
            if result_line:
                stdout = f"{stdout}\nresult={result_line}" if stdout.strip() else f"result={result_line}"

        exit_code = 0 if status == "success" else 1

        return ExecutionOutcome(
            status=status,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            wall_time_ms=wall_ms,
            raw=raw,
        )


# ── Registry ─────────────────────────────────────────────────────────────────

class CodeExecutionPipeline:
    """
    Singleton-style pipeline SDK.  Call get_pipeline() rather than
    instantiating directly so that registered validators/scanners persist.
    """

    def __init__(self) -> None:
        self._executors: Dict[str, Executor] = {}
        self._extra_validators: Dict[str, List[Callable]] = {}
        self._extra_scanners: Dict[str, List[Callable]] = {}

        # Register default Python executor
        self.register_executor("python", PythonDockerExecutor())

    # ── Registration API (for #172 BeautyOS Adapter) ──────────────────────────

    def register_executor(self, language: str, executor: Executor) -> None:
        self._executors[language] = executor

    def register_validator(self, language: str, validator: Callable) -> None:
        self._extra_validators.setdefault(language, []).append(validator)

    def register_scanner(self, language: str, scanner: Callable) -> None:
        self._extra_scanners.setdefault(language, []).append(scanner)

    # ── Main execute ──────────────────────────────────────────────────────────

    def execute(self, req: ExecutionRequest) -> ExecutionResult:
        audit_id = str(uuid.uuid4())

        # ── Phase A: Pre-Validate (host-side, no Docker) ──────────────────────
        validation = self._pre_validate(req)
        if not validation.passed and validation.level == "block":
            msg = validation.errors[0].message if validation.errors else "代码被安全检查拦截"
            logger.info("[pipeline] pre_validate blocked audit=%s msg=%s", audit_id, msg)
            _write_ledger_safe(audit_id, req, validation=validation, outcome=None, analysis=None)
            return ExecutionResult(
                ok=False,
                phase="pre_validate",
                validation=validation,
                audit_id=audit_id,
                user_message=f"[代码执行失败: {msg}]",
            )

        # ── Phase B: Sandbox Execute ──────────────────────────────────────────
        executor = self._executors.get(req.language)
        if executor is None:
            msg = f"不支持的语言: {req.language}"
            return ExecutionResult(
                ok=False, phase="sandbox",
                validation=validation, audit_id=audit_id,
                user_message=f"[代码执行失败: {msg}]",
            )

        outcome = executor.run(req)
        logger.info("[pipeline] sandbox status=%s wall_ms=%.1f audit=%s",
                    outcome.status, outcome.wall_time_ms, audit_id)

        # ── Phase C: Post-Scan (always runs) ──────────────────────────────────
        analysis = scan_outcome(
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            exit_code=outcome.exit_code,
        )

        # Run any extra scanners registered by adapters (e.g. #172 BeautyOS)
        for scanner in self._extra_scanners.get(req.language, []):
            try:
                scanner(req, outcome, analysis)
            except Exception as exc:
                logger.warning("[pipeline] extra scanner error: %s", exc)

        ok = (outcome.status == "success") and (analysis.verdict == "clean")
        try:
            _write_ledger_safe(audit_id, req, validation=validation, outcome=outcome, analysis=analysis)
        except Exception as exc:
            logger.debug("[pipeline] ledger write error: %s", exc)

        user_message = _build_user_message(outcome, analysis)
        return ExecutionResult(
            ok=ok,
            phase="done",
            validation=validation,
            outcome=outcome,
            analysis=analysis,
            audit_id=audit_id,
            user_message=user_message,
        )

    # ── Internals ─────────────────────────────────────────────────────────────

    def _pre_validate(self, req: ExecutionRequest) -> PreValidationResult:
        if req.language == "python":
            result = run_python_validators(req.code)
        else:
            from dataclasses import replace as dc_replace
            result = PreValidationResult(passed=True, validator_chain=["passthrough"])

        # Run extra validators registered by adapters
        for validator in self._extra_validators.get(req.language, []):
            try:
                extra = validator(req.code)
                if not extra.passed and extra.level == "block":
                    return extra
                result.warnings.extend(extra.warnings)
                result.validator_chain.extend(extra.validator_chain)
            except Exception as exc:
                logger.warning("[pipeline] extra validator error: %s", exc)

        return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_user_message(outcome: ExecutionOutcome, analysis: LogAnalysisResult) -> str:
    raw = outcome.raw
    if outcome.status == "success" and analysis.verdict == "clean":
        result_text = raw.get("result", "")
        printed = (raw.get("output", "") or "").strip()
        if printed:
            return f"计算结果: {result_text}\n输出:\n{printed}"
        return f"计算结果: {result_text}"
    else:
        error = raw.get("error", "") or ""
        if analysis.inferred_failure_kind:
            return f"[代码执行失败: {error}] (inferred: {analysis.inferred_failure_kind})"
        return f"[代码执行失败: {error}]" if error else f"[代码执行失败，verdict={analysis.verdict}]"


def _write_ledger_safe(
    audit_id: str,
    req: ExecutionRequest,
    *,
    validation: Optional[PreValidationResult],
    outcome: Optional[ExecutionOutcome],
    analysis: Optional[LogAnalysisResult],
) -> None:
    """Best-effort write to event_ledger; never raises."""
    try:
        from app.agent.event_ledger import record_tool_execution
        record_tool_execution(
            audit_id=audit_id,
            adapter=req.adapter,
            language=req.language,
            validation_level=validation.level if validation else "unknown",
            verdict=analysis.verdict if analysis else "unknown",
            inferred_failure_kind=analysis.inferred_failure_kind if analysis else None,
            wall_time_ms=outcome.wall_time_ms if outcome else 0.0,
        )
    except Exception as exc:
        logger.debug("[pipeline] ledger write skipped: %s", exc)


# ── Singleton ─────────────────────────────────────────────────────────────────

_pipeline: Optional[CodeExecutionPipeline] = None


def get_pipeline() -> CodeExecutionPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = CodeExecutionPipeline()
    return _pipeline
