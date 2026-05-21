"""
Unit tests for CodeExecutionPipeline (#176).

Covers:
  - Host-side AST pre-validation (should NOT start Docker)
  - PostScanner pattern recognition
  - Full pipeline integration (mocked executor)
  - ARITHMETIC_ONLY fast-path is tested on the TS side
"""
from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

from infrastructure._ast_safety_rules import FORBIDDEN_NAMES, FORBIDDEN_NODES
from infrastructure.code_pipeline import (
    CodeExecutionPipeline,
    ExecutionOutcome,
    ExecutionPolicy,
    ExecutionRequest,
    get_pipeline,
)
from infrastructure.scanners.log_patterns import scan_outcome
from infrastructure.validators.python_validators import (
    PythonAstSafetyValidator,
    PythonSyntaxValidator,
    run_python_validators,
)


# ── Pre-Validator tests ───────────────────────────────────────────────────────

class TestPythonSyntaxValidator(unittest.TestCase):
    def test_valid_code_passes(self):
        result = PythonSyntaxValidator().validate("result = 1 + 2")
        self.assertTrue(result.passed)
        self.assertEqual(result.level, "ok")

    def test_syntax_error_blocked(self):
        result = PythonSyntaxValidator().validate("def bad(:")
        self.assertFalse(result.passed)
        self.assertEqual(result.level, "block")
        self.assertIn("语法错误", result.errors[0].message)


class TestPythonAstSafetyValidator(unittest.TestCase):
    def _check_blocked(self, code: str):
        r = PythonAstSafetyValidator().validate(code)
        self.assertFalse(r.passed, f"Expected block for: {code!r}")
        self.assertEqual(r.level, "block")

    def test_import_blocked(self):
        self._check_blocked("import os")

    def test_from_import_blocked(self):
        self._check_blocked("from os import path")

    def test_exec_blocked(self):
        self._check_blocked("exec('print(1)')")

    def test_eval_blocked(self):
        self._check_blocked("eval('1+1')")

    def test_open_blocked(self):
        self._check_blocked("open('/etc/passwd')")

    def test_dunder_attr_blocked(self):
        self._check_blocked("x = obj.__class__")

    def test_safe_arithmetic_passes(self):
        code = "result = Decimal('5000000') * Decimal('0.035')"
        r = PythonAstSafetyValidator().validate(code)
        self.assertTrue(r.passed)

    def test_multiline_safe_passes(self):
        code = "items = [1, 2, 3]\nresult = sum(items)"
        r = PythonAstSafetyValidator().validate(code)
        self.assertTrue(r.passed)


class TestRunPythonValidators(unittest.TestCase):
    def test_import_os_blocked_quickly(self):
        """import os must be blocked host-side; Docker must NOT be started."""
        with patch("subprocess.run") as mock_run:
            t0 = time.monotonic()
            result = run_python_validators("import os")
            elapsed_ms = (time.monotonic() - t0) * 1000

        self.assertFalse(result.passed)
        self.assertEqual(result.level, "block")
        mock_run.assert_not_called()  # Docker not started
        self.assertLess(elapsed_ms, 500, f"Pre-validation took {elapsed_ms:.0f}ms, expected <500ms")

    def test_valid_code_passes_chain(self):
        result = run_python_validators("x = 1 + 2\nresult = x * 3")
        self.assertTrue(result.passed)
        self.assertIn("PythonSyntaxValidator", result.validator_chain)
        self.assertIn("PythonAstSafetyValidator", result.validator_chain)


# ── PostScanner tests ─────────────────────────────────────────────────────────

class TestScanOutcome(unittest.TestCase):
    def test_clean_success(self):
        r = scan_outcome(stdout="result=42", stderr="", exit_code=0)
        self.assertEqual(r.verdict, "clean")
        self.assertTrue(r.short_circuit_success)

    def test_oom_exit_137(self):
        r = scan_outcome(stdout="", stderr="", exit_code=137)
        self.assertEqual(r.verdict, "hard_fail")
        self.assertEqual(r.inferred_failure_kind, "oom")

    def test_oom_memory_error_in_stderr(self):
        r = scan_outcome(stdout="", stderr="MemoryError: unable to allocate", exit_code=1)
        self.assertEqual(r.verdict, "hard_fail")
        self.assertEqual(r.inferred_failure_kind, "oom")

    def test_segfault_exit_139(self):
        r = scan_outcome(stdout="", stderr="", exit_code=139)
        self.assertEqual(r.verdict, "hard_fail")
        self.assertEqual(r.inferred_failure_kind, "segfault")

    def test_network_attempt(self):
        r = scan_outcome(stdout="", stderr="socket.gaierror: [Errno -3] Name resolution failed", exit_code=1)
        self.assertEqual(r.verdict, "hard_fail")
        self.assertEqual(r.inferred_failure_kind, "network_attempt")

    def test_recursion_error(self):
        r = scan_outcome(stdout="", stderr="RecursionError: maximum recursion depth exceeded", exit_code=1)
        self.assertEqual(r.verdict, "hard_fail")
        self.assertEqual(r.inferred_failure_kind, "stack_overflow")

    def test_assertion_error_soft_fail(self):
        r = scan_outcome(stdout="AssertionError: expected 5 got 6", stderr="", exit_code=1)
        self.assertEqual(r.verdict, "soft_fail")
        self.assertEqual(r.inferred_failure_kind, "test_failure")

    def test_secret_exfil_aws_key(self):
        r = scan_outcome(stdout="AKIAIOSFODNN7EXAMPLE123", stderr="", exit_code=0)
        self.assertEqual(r.verdict, "hard_fail")
        self.assertEqual(r.inferred_failure_kind, "secret_exfil")

    def test_implicit_traceback_with_exit_0(self):
        stdout = "Traceback (most recent call last):\n  File test.py\nValueError: bad"
        r = scan_outcome(stdout=stdout, stderr="", exit_code=0)
        self.assertEqual(r.verdict, "soft_fail")

    def test_tail_excerpt_populated(self):
        r = scan_outcome(stdout="some output", stderr="some error", exit_code=1)
        self.assertTrue(len(r.tail_excerpt) > 0)


# ── Full Pipeline integration (mocked executor) ───────────────────────────────

class TestCodeExecutionPipeline(unittest.TestCase):
    def _make_pipeline_with_mock(self, mock_outcome: ExecutionOutcome) -> CodeExecutionPipeline:
        pipeline = CodeExecutionPipeline()
        mock_executor = MagicMock()
        mock_executor.run.return_value = mock_outcome
        pipeline.register_executor("python", mock_executor)
        return pipeline

    def test_pre_validate_blocks_import_no_docker(self):
        pipeline = self._make_pipeline_with_mock(ExecutionOutcome(status="success"))
        req = ExecutionRequest(code="import os", language="python", adapter="test")
        with patch("subprocess.run") as mock_run:
            result = pipeline.execute(req)
        self.assertFalse(result.ok)
        self.assertEqual(result.phase, "pre_validate")
        pipeline._executors["python"].run.assert_not_called()
        mock_run.assert_not_called()

    def test_success_path_returns_ok(self):
        outcome = ExecutionOutcome(status="success", stdout="result=42", stderr="", exit_code=0)
        pipeline = self._make_pipeline_with_mock(outcome)
        req = ExecutionRequest(code="result = 42", language="python", adapter="test")
        result = pipeline.execute(req)
        self.assertTrue(result.ok)
        self.assertEqual(result.phase, "done")
        self.assertIsNotNone(result.audit_id)

    def test_oom_outcome_flagged_hard_fail(self):
        outcome = ExecutionOutcome(status="error", stdout="", stderr="", exit_code=137)
        pipeline = self._make_pipeline_with_mock(outcome)
        req = ExecutionRequest(code="while True: pass", language="python", adapter="test")
        result = pipeline.execute(req)
        self.assertFalse(result.ok)
        self.assertEqual(result.analysis.verdict, "hard_fail")
        self.assertEqual(result.analysis.inferred_failure_kind, "oom")

    def test_audit_id_is_uuid(self):
        import uuid
        outcome = ExecutionOutcome(status="success", stdout="", stderr="", exit_code=0)
        pipeline = self._make_pipeline_with_mock(outcome)
        req = ExecutionRequest(code="result = 1", language="python")
        result = pipeline.execute(req)
        self.assertIsNotNone(uuid.UUID(result.audit_id))  # valid UUID, no exception

    def test_get_pipeline_returns_singleton(self):
        p1 = get_pipeline()
        p2 = get_pipeline()
        self.assertIs(p1, p2)

    def test_post_scan_runs_on_error_outcome(self):
        """PostScanner must run even when sandbox returns error status."""
        outcome = ExecutionOutcome(
            status="error", stdout="AssertionError: x != y", stderr="", exit_code=1
        )
        pipeline = self._make_pipeline_with_mock(outcome)
        req = ExecutionRequest(code="assert False", language="python")
        result = pipeline.execute(req)
        self.assertIsNotNone(result.analysis)
        self.assertEqual(result.analysis.verdict, "soft_fail")

    def test_ledger_write_failure_does_not_raise(self):
        """event_ledger unavailable should not crash the pipeline."""
        outcome = ExecutionOutcome(status="success", stdout="result=1", stderr="", exit_code=0)
        pipeline = self._make_pipeline_with_mock(outcome)
        req = ExecutionRequest(code="result = 1", language="python")
        with patch("infrastructure.code_pipeline._write_ledger_safe", side_effect=Exception("db down")):
            result = pipeline.execute(req)  # must not raise
        self.assertTrue(result.ok)


if __name__ == "__main__":
    unittest.main()
