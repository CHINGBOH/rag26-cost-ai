"""
LLM timeout policy: cloud APIs need more time than local GPUs.

Canonical config: extend via LLMTimeoutPolicy attributes or environment variables
RAG__LLM__LOCAL_FAST_TIMEOUT, RAG__LLM__CLOUD_QUEUE_TIMEOUT, etc.
"""

import logging

logger = logging.getLogger(__name__)

# Cloud providers that typically have short queue times (domestic APIs)
_FAST_CLOUD_PROVIDERS = frozenset({"deepseek", "moonshot", "qwen", "baidu", "zhipu"})


class LLMTimeoutPolicy:
    """Dynamic timeout selection based on runtime context.

    Local models are bounded by GPU throughput (fast).
    Cloud APIs add network + queue latency and need more headroom.
    """

    # Local GPU timeouts (seconds)
    LOCAL_FAST: int = 30       # 7B models on modern GPU
    LOCAL_STANDARD: int = 60   # 14B models
    LOCAL_LARGE: int = 120     # 32B+ models

    # Cloud API timeouts (seconds)
    CLOUD_API: int = 45        # Fast domestic APIs (deepseek, moonshot, etc.)
    CLOUD_QUEUE: int = 90      # International APIs with potential queuing

    @classmethod
    def get_timeout(cls, runtime: dict) -> int:
        """Select appropriate timeout for a given runtime descriptor.

        Args:
            runtime: dict with keys: is_local (bool), model (str), provider (str, optional)

        Returns:
            Timeout in seconds.
        """
        is_local: bool = runtime.get("is_local", False)

        if is_local:
            model_name: str = runtime.get("model", "").upper()
            if "7B" in model_name:
                timeout = cls.LOCAL_FAST
            elif any(tag in model_name for tag in ("32B", "72B", "70B")):
                timeout = cls.LOCAL_LARGE
            else:
                timeout = cls.LOCAL_STANDARD
        else:
            provider: str = runtime.get("provider", "").lower()
            if provider in _FAST_CLOUD_PROVIDERS:
                timeout = cls.CLOUD_API
            else:
                timeout = cls.CLOUD_QUEUE

        logger.debug(
            "[LLMTimeoutPolicy] is_local=%s model=%s provider=%s → timeout=%ds",
            is_local,
            runtime.get("model", ""),
            runtime.get("provider", ""),
            timeout,
        )
        return timeout
