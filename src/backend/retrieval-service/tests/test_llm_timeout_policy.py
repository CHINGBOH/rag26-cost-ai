"""Tests for LLMTimeoutPolicy — #126 LLM Timeout double standard fix."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.llm_timeout_policy import LLMTimeoutPolicy


def _rt(is_local: bool, model: str = "", provider: str = "") -> dict:
    return {"is_local": is_local, "model": model, "provider": provider}


# ─── Local model timeouts ──────────────────────────────────────────────────────

def test_local_7b_is_fast():
    assert LLMTimeoutPolicy.get_timeout(_rt(True, "Qwen2.5-7B")) == LLMTimeoutPolicy.LOCAL_FAST


def test_local_14b_is_standard():
    assert LLMTimeoutPolicy.get_timeout(_rt(True, "Qwen2.5-14B")) == LLMTimeoutPolicy.LOCAL_STANDARD


def test_local_32b_is_large():
    assert LLMTimeoutPolicy.get_timeout(_rt(True, "Qwen2.5-32B")) == LLMTimeoutPolicy.LOCAL_LARGE


def test_local_72b_is_large():
    assert LLMTimeoutPolicy.get_timeout(_rt(True, "Llama-3-70B")) == LLMTimeoutPolicy.LOCAL_LARGE


def test_local_unknown_model_is_standard():
    assert LLMTimeoutPolicy.get_timeout(_rt(True, "unknown-model")) == LLMTimeoutPolicy.LOCAL_STANDARD


def test_local_fast_less_than_standard():
    assert LLMTimeoutPolicy.LOCAL_FAST < LLMTimeoutPolicy.LOCAL_STANDARD


def test_local_standard_less_than_large():
    assert LLMTimeoutPolicy.LOCAL_STANDARD < LLMTimeoutPolicy.LOCAL_LARGE


# ─── Cloud model timeouts ──────────────────────────────────────────────────────

def test_cloud_deepseek_is_api():
    assert LLMTimeoutPolicy.get_timeout(_rt(False, provider="deepseek")) == LLMTimeoutPolicy.CLOUD_API


def test_cloud_moonshot_is_api():
    assert LLMTimeoutPolicy.get_timeout(_rt(False, provider="moonshot")) == LLMTimeoutPolicy.CLOUD_API


def test_cloud_openai_is_queue():
    assert LLMTimeoutPolicy.get_timeout(_rt(False, provider="openai")) == LLMTimeoutPolicy.CLOUD_QUEUE


def test_cloud_unknown_provider_is_queue():
    assert LLMTimeoutPolicy.get_timeout(_rt(False, provider="")) == LLMTimeoutPolicy.CLOUD_QUEUE


def test_cloud_longer_than_local_fast():
    """Cloud queue timeout must be longer than local fast to fix #126."""
    assert LLMTimeoutPolicy.CLOUD_QUEUE > LLMTimeoutPolicy.LOCAL_FAST


def test_cloud_api_longer_than_local_fast():
    assert LLMTimeoutPolicy.CLOUD_API > LLMTimeoutPolicy.LOCAL_FAST


# ─── Boundary / regression ────────────────────────────────────────────────────

def test_old_logic_was_inverted():
    """Regression: old code gave local=120 > cloud=90; new code gives local_fast=30 < cloud=45."""
    local_timeout = LLMTimeoutPolicy.get_timeout(_rt(True, "Qwen2.5-7B"))
    cloud_timeout = LLMTimeoutPolicy.get_timeout(_rt(False, provider="deepseek"))
    assert local_timeout < cloud_timeout, (
        f"Local ({local_timeout}s) should be shorter than cloud ({cloud_timeout}s)"
    )


def test_returns_int():
    assert isinstance(LLMTimeoutPolicy.get_timeout(_rt(True, "Qwen2.5-14B")), int)
