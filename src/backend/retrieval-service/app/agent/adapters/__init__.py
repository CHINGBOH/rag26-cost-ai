"""#164: DomainAdapter pluggable validation adapters."""

from app.agent.adapters.base import DomainAdapter, ValidationResult, Entity
from app.agent.adapters.cost_consulting_adapter import (
    CostConsultingAdapter,
    get_cost_consulting_adapter,
)

__all__ = [
    "DomainAdapter",
    "ValidationResult",
    "Entity",
    "CostConsultingAdapter",
    "get_cost_consulting_adapter",
]
