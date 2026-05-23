"""
#164: DomainAdapter abstract base class for pluggable domain validation.

Provides the DomainAdapter ABC, ValidationResult, and Entity dataclasses
that all domain adapters (CostConsultingAdapter, BeautyOSAdapter, etc.)
must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationResult:
    """Result of a domain-specific validation check.

    Fields per issue #164 spec:
        passed: Whether the validation passed.
        error_type: Short error/check code (e.g. 'missing_material', 'citation_hallucination').
        error_location: Where the error was detected (node, field, or section name).
        error_detail: Human-readable description of the failure.
        suggested_alternatives: Optional list of corrective suggestions.
    """

    passed: bool = False
    error_type: str | None = None
    error_location: str | None = None
    error_detail: str = ""
    suggested_alternatives: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """One-line summary for logging."""
        status = "PASSED" if self.passed else "FAILED"
        parts = [status]
        if self.error_type:
            parts.append(f"type={self.error_type}")
        if self.error_location:
            parts.append(f"loc={self.error_location}")
        return " | ".join(parts)


@dataclass
class Entity:
    """Domain entity extracted from a query or indexed data.

    Fields per issue #164 spec:
        entity_id: Unique identifier within the domain (e.g. '粤01-01-01').
        entity_type: Category label (e.g. 'quota_code', 'material_code', 'formula').
        name: Human-readable name.
        attributes: Arbitrary key-value metadata.
        score: Relevance score (0.0-1.0).
    """

    entity_id: str
    entity_type: str
    name: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0


class DomainAdapter(ABC):
    """Abstract base class for domain-specific answer validation adapters.

    Each domain (Cost Consulting, BeautyOS, etc.) implements this interface
    to plug domain-specific validation rules into the agent's contract
    verification pipeline.

    Required properties:
        domain_id: Unique domain identifier string.
        agent_persona: Persona/system prompt role string.

    Required methods:
        validate_static: Validate a chunk against static domain rules.
        validate_runtime: Validate a chunk using sandbox execution.
        build_index: Build an entity index for fast lookup.
        entity_lookup: Look up entities matching a query.

    Backward-compatible methods (implement for existing callers):
        validate_answer: Validate an answer against domain rules.
        get_domain_schema: Return the domain schema / entity definitions.
        get_validation_rules: Return the list of validation rules applied.
    """

    # ── Class-level constants (override in subclasses) ──

    @property
    @abstractmethod
    def domain_id(self) -> str:
        """Unique domain identifier (e.g. 'cost-consulting', 'beauty-os')."""
        ...

    @property
    @abstractmethod
    def agent_persona(self) -> str:
        """System prompt persona / role description."""
        ...

    # ── Issue #164 core interface ──

    @abstractmethod
    def validate_static(self, chunk: dict[str, Any]) -> ValidationResult:
        """Validate a single retrieved chunk against static domain rules.

        Static rules are pattern-based checks that do not require sandbox
        execution. Examples: quota code format validation, material code
        structure check, formula name presence.

        Args:
            chunk: A retrieved evidence chunk dict with keys such as
                   'content' (str), 'metadata' (dict), 'source' (str).

        Returns:
            ValidationResult indicating pass/fail with error details.
        """
        ...

    @abstractmethod
    def validate_runtime(
        self,
        chunk: dict[str, Any],
        sandbox: Any | None = None,
    ) -> ValidationResult:
        """Validate a chunk through sandbox execution.

        For chunks containing computation formulas, execute the formula in a
        sandbox to verify correctness. For chunks without formulas, return
        a passed result.

        Args:
            chunk: A retrieved evidence chunk dict.
            sandbox: Optional sandbox executor callable or module.
                     If None, runtime validation is skipped.

        Returns:
            ValidationResult indicating pass/fail with error details.
        """
        ...

    @abstractmethod
    def build_index(self) -> dict[str, Any]:
        """Build an in-memory entity index for fast lookup.

        Returns:
            A dict-based index structure keyed by entity type and entity_id
            for efficient entity_lookup queries.
        """
        ...

    @abstractmethod
    def entity_lookup(self, query: str) -> list[Entity]:
        """Look up entities matching a query string.

        Args:
            query: Search string (e.g. material name, quota code prefix).

        Returns:
            List of matching Entity objects, sorted by relevance score.
        """
        ...

    # ── Backward-compatible helpers ──

    def validate_answer(
        self,
        answer: str,
        chunks: list[dict[str, Any]],
        query: str = "",
        **kwargs: Any,
    ) -> ValidationResult:
        """Validate an answer against domain-specific rules.

        Default implementation: run validate_static on each chunk and
        aggregate results. Override for domain-specific answer-level checks.

        Args:
            answer: The synthesized final answer text.
            chunks: Retrieved evidence chunks used to produce the answer.
            query: The original user query.
            **kwargs: Additional domain-specific context.

        Returns:
            ValidationResult indicating pass/fail with error details.
        """
        failures: list[ValidationResult] = []
        for chunk in chunks:
            result = self.validate_static(chunk)
            if not result.passed:
                failures.append(result)

        if failures:
            return ValidationResult(
                passed=False,
                error_type=failures[0].error_type,
                error_location=failures[0].error_location,
                error_detail=f"{len(failures)} chunks failed static validation: "
                + "; ".join(f.error_detail for f in failures[:3]),
                suggested_alternatives=failures[0].suggested_alternatives,
            )
        return ValidationResult(passed=True)

    def get_domain_schema(self) -> dict[str, Any]:
        """Return the domain schema definition.

        Default returns basic metadata. Override for domain-specific schemas.
        """
        return {
            "domain_id": self.domain_id,
            "agent_persona": self.agent_persona,
        }

    def get_validation_rules(self) -> list[dict[str, Any]]:
        """Return the list of validation rules applied by this adapter.

        Each rule is a dict with keys:
            code: Short rule code (e.g. 'R01_valid_quota_code').
            description: Human-readable description.
            severity: 'error' | 'warning'.
            applies_to: Which domain context(s) the rule targets.
        """
        return []
