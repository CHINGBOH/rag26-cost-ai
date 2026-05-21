"""
Host-side Python pre-validators for CodeExecutionPipeline.

Chain (executed in cost-ascending order):
  1. PythonSyntaxValidator   — ast.parse only, no external deps
  2. PythonAstSafetyValidator — mirrors sandbox_entry.py:check_ast_safety (defence-in-depth)
  3. PythonImportBudgetValidator — extra blanket ban on any remaining import forms
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from infrastructure._ast_safety_rules import FORBIDDEN_NAMES, FORBIDDEN_NODES

logger = logging.getLogger(__name__)


@dataclass
class ValidationError:
    message: str
    level: str = "block"  # "warn" | "block"


@dataclass
class PreValidationResult:
    passed: bool
    level: str = "ok"           # "ok" | "warn" | "block"
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)
    validator_chain: List[str] = field(default_factory=list)


class PythonSyntaxValidator:
    name = "PythonSyntaxValidator"

    def validate(self, code: str) -> PreValidationResult:
        try:
            ast.parse(code)
        except SyntaxError as exc:
            return PreValidationResult(
                passed=False,
                level="block",
                errors=[ValidationError(f"语法错误: {exc}")],
                validator_chain=[self.name],
            )
        return PreValidationResult(passed=True, validator_chain=[self.name])


class PythonAstSafetyValidator:
    """Host-side mirror of sandbox_entry.py:check_ast_safety — same rules, earlier gate."""

    name = "PythonAstSafetyValidator"

    def validate(self, code: str) -> PreValidationResult:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            # Syntax errors are caught upstream; skip here gracefully.
            return PreValidationResult(passed=True, validator_chain=[self.name])

        for node in ast.walk(tree):
            if isinstance(node, FORBIDDEN_NODES):
                return PreValidationResult(
                    passed=False,
                    level="block",
                    errors=[ValidationError("安全限制: 不允许使用 import 语句")],
                    validator_chain=[self.name],
                )

            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in FORBIDDEN_NAMES:
                    return PreValidationResult(
                        passed=False,
                        level="block",
                        errors=[ValidationError(f"安全限制: 不允许调用 {func.id}()")],
                        validator_chain=[self.name],
                    )
                if isinstance(func, ast.Attribute) and func.attr.startswith("__"):
                    return PreValidationResult(
                        passed=False,
                        level="block",
                        errors=[ValidationError(f"安全限制: 不允许访问双下划线属性 __{func.attr}__")],
                        validator_chain=[self.name],
                    )

            if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                return PreValidationResult(
                    passed=False,
                    level="block",
                    errors=[ValidationError(f"安全限制: 不允许访问 __{node.attr}__")],
                    validator_chain=[self.name],
                )

            if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
                return PreValidationResult(
                    passed=False,
                    level="block",
                    errors=[ValidationError(f"安全限制: 不允许使用 {node.id}")],
                    validator_chain=[self.name],
                )

        return PreValidationResult(passed=True, validator_chain=[self.name])


class PythonImportBudgetValidator:
    """Extra blanket check — rejects any node that looks import-like after AST rewriting."""

    name = "PythonImportBudgetValidator"

    def validate(self, code: str) -> PreValidationResult:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return PreValidationResult(passed=True, validator_chain=[self.name])

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                return PreValidationResult(
                    passed=False,
                    level="block",
                    errors=[ValidationError("安全限制: import 语句被完全禁止")],
                    validator_chain=[self.name],
                )
        return PreValidationResult(passed=True, validator_chain=[self.name])


def run_python_validators(code: str) -> PreValidationResult:
    """Run the full host-side validator chain; short-circuits on first block."""
    chain: List[str] = []
    all_warnings: List[ValidationError] = []

    for validator in [
        PythonSyntaxValidator(),
        PythonAstSafetyValidator(),
        PythonImportBudgetValidator(),
    ]:
        result = validator.validate(code)
        chain.extend(result.validator_chain)
        if not result.passed and result.level == "block":
            result.validator_chain = chain
            result.warnings = all_warnings
            logger.debug("[pipeline] pre-validate blocked by %s: %s",
                         validator.name, result.errors[0].message if result.errors else "")
            return result
        all_warnings.extend(result.warnings)

    return PreValidationResult(
        passed=True,
        level="warn" if all_warnings else "ok",
        warnings=all_warnings,
        validator_chain=chain,
    )
