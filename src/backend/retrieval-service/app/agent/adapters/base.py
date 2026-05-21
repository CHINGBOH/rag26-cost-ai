from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ValidationResult:
    passed: bool
    error_type: Optional[str] = None      # SYMBOL_HALLUCINATION / RUNTIME_ERROR / FACTUAL_CONTRADICTION
    error_location: Optional[str] = None  # file:line:col or doc_id:page
    error_detail: str = ""
    suggested_alternatives: List[str] = field(default_factory=list)


@dataclass
class Entity:
    name: str
    entity_type: str  # quota_number / material / formula / function / class
    source: str       # source document or module


class DomainAdapter(ABC):
    domain_id: str
    agent_persona: str

    @abstractmethod
    def validate_static(self, chunk: str) -> ValidationResult:
        """Static validation: symbol existence, entity index lookup (sync, no side effects)"""

    @abstractmethod
    def validate_runtime(self, chunk: str, sandbox) -> ValidationResult:
        """Runtime validation: sandbox execution + log pattern matching"""

    @abstractmethod
    def validate_factual(self, chunk: str, kb) -> ValidationResult:
        """Factual validation: citation check, entity consistency, value verification"""

    @abstractmethod
    def extract_entities(self, chunk: str) -> List[Entity]:
        """Extract domain entities from chunk for Working Memory updates"""

    @abstractmethod
    def seed_skills(self) -> List[dict]:
        """Return initial domain skill list (name, description, content)"""

    @abstractmethod
    def classify_hallucination(self, error: ValidationResult) -> str:
        """Map a ValidationResult error to a hallucination category string"""
