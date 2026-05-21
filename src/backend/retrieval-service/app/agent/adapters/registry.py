import os
from typing import Dict, Optional, Type

from app.agent.adapters.base import DomainAdapter


class AdapterRegistry:
    _registry: Dict[str, Type[DomainAdapter]] = {}

    @classmethod
    def register(cls, adapter_class: Type[DomainAdapter]) -> Type[DomainAdapter]:
        cls._registry[adapter_class.domain_id] = adapter_class
        return adapter_class

    @classmethod
    def get(cls, domain_id: str) -> DomainAdapter:
        if domain_id not in cls._registry:
            raise KeyError(
                f"No adapter registered for domain_id={domain_id!r}. "
                f"Available: {list(cls._registry)}"
            )
        return cls._registry[domain_id]()

    @classmethod
    def get_active(cls) -> DomainAdapter:
        """Instantiate the adapter selected by AGENT_DOMAIN_ID (default: construction-cost)."""
        domain_id = os.getenv("AGENT_DOMAIN_ID", "construction-cost")
        return cls.get(domain_id)

    @classmethod
    def available(cls) -> list:
        return list(cls._registry.keys())


def _bootstrap_registry() -> None:
    from app.agent.adapters.cost_consulting import CostConsultingAdapter

    AdapterRegistry.register(CostConsultingAdapter)


_bootstrap_registry()
