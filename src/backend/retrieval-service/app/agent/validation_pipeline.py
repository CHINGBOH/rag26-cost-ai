import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from app.agent.adapters.base import DomainAdapter, ValidationResult

logger = logging.getLogger(__name__)

_ERRORS_MD_PATH = Path(os.getenv("ERRORS_MD_PATH", "ERRORS.md"))


@dataclass
class ValidationReport:
    passed: bool
    hallucination_type: Optional[str] = None
    evidence: List[dict] = field(default_factory=list)
    correction_attempts: int = 0


class ValidationPipeline:
    """Three-step validation pipeline: static → runtime → factual.

    On failure, attempts up to 3 auto-corrections via a correction_fn.
    Unresolved errors are persisted to ERRORS.md.
    """

    def __init__(
        self,
        adapter: DomainAdapter,
        correction_fn: Optional[Callable[[str, ValidationResult], str]] = None,
    ):
        self.adapter = adapter
        # correction_fn(chunk, error) -> corrected_chunk
        self._correction_fn = correction_fn

    # ── public entry point ─────────────────────────────────────────────────────

    def run(self, chunk: str, sandbox=None, kb=None) -> ValidationReport:
        return self._run_from_step(chunk, "static", sandbox=sandbox, kb=kb, attempt=1)

    # ── internal helpers ───────────────────────────────────────────────────────

    def _run_from_step(
        self,
        chunk: str,
        step: str,
        sandbox,
        kb,
        attempt: int,
    ) -> ValidationReport:
        if step == "static":
            result = self.adapter.validate_static(chunk)
            if not result.passed:
                return self._correction_loop(
                    chunk, result, step="static", sandbox=sandbox, kb=kb, attempt=attempt
                )
            step = "runtime"

        if step == "runtime":
            if sandbox is not None:
                result = self.adapter.validate_runtime(chunk, sandbox)
                if not result.passed:
                    return self._correction_loop(
                        chunk, result, step="runtime", sandbox=sandbox, kb=kb, attempt=attempt
                    )
            step = "factual"

        # step == "factual"
        result = self.adapter.validate_factual(chunk, kb)
        if not result.passed:
            return self._correction_loop(
                chunk, result, step="factual", sandbox=sandbox, kb=kb, attempt=attempt
            )

        return ValidationReport(passed=True, correction_attempts=attempt - 1)

    def _correction_loop(
        self,
        chunk: str,
        error: ValidationResult,
        step: str,
        sandbox,
        kb,
        attempt: int,
    ) -> ValidationReport:
        if attempt > 3:
            self._record_hallucination(chunk, error)
            return ValidationReport(
                passed=False,
                hallucination_type=error.error_type,
                correction_attempts=3,
            )

        corrected = self._request_correction(chunk, error)
        if corrected == chunk:
            # No change produced — avoid infinite retry with identical input.
            self._record_hallucination(chunk, error)
            return ValidationReport(
                passed=False,
                hallucination_type=error.error_type,
                correction_attempts=attempt,
            )

        logger.info(
            "[validation_pipeline] correction attempt %d/3 for %s",
            attempt,
            error.error_type,
        )
        return self._run_from_step(corrected, step, sandbox=sandbox, kb=kb, attempt=attempt + 1)

    def _request_correction(self, chunk: str, error: ValidationResult) -> str:
        if self._correction_fn is None:
            return chunk
        try:
            return self._correction_fn(chunk, error)
        except Exception:
            logger.exception("[validation_pipeline] correction_fn raised")
            return chunk

    def _record_hallucination(self, chunk: str, error: ValidationResult) -> None:
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        domain = self.adapter.domain_id
        entry = (
            f"\n## [{timestamp}] {domain} — {error.error_type}\n"
            f"- **Location**: {error.error_location or 'unknown'}\n"
            f"- **Detail**: {error.error_detail}\n"
            f"- **Chunk** (first 300 chars): {chunk[:300]!r}\n"
        )
        try:
            with open(_ERRORS_MD_PATH, "a", encoding="utf-8") as fh:
                fh.write(entry)
            logger.warning(
                "[validation_pipeline] hallucination recorded to %s: %s",
                _ERRORS_MD_PATH,
                error.error_type,
            )
        except OSError as exc:
            logger.error("[validation_pipeline] failed to write ERRORS.md: %s", exc)
