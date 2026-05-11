"""
Agent Prompts + LLM 初始化
"""

import os
import re
from typing import Any

import httpx
from langchain_openai import ChatOpenAI

from app.runtime_config import bootstrap_llm_proxy_environment, read_runtime_config
from config.llm_timeout_policy import LLMTimeoutPolicy

_runtime = read_runtime_config()
bootstrap_llm_proxy_environment(_runtime.llm_base_url)


SYSTEM_PROMPT = """你是工程造价知识库问答助手。根据提供的检索结果回答用户问题。

格式要求（强制）：
- 禁止使用 Markdown 格式符号，包括 # ## ### * ** ` ``` | --- 等
- 用中文标点和换行组织结构，不用横线、星号、井号
- 回答结构：先说结论，再给论据，最后标来源
- 禁止写任何分段小标题，包括但不限于：核心结论、总结、简要分析、适用范围、适用边界、公式推导、关键信息、计量方式、数据来源、补充说明
- 你只需输出连续的段落文本，不要用任何标题行分割内容
- 来源用【chunk_id】标注在数值之后，例如：建筑工程推荐费率为3.68%【fr_7】

内容规则：
1. 严格基于检索结果，不编造数值
2. 数值必须来自原文，引用标注紧跟数值
3. 检索结果不足时直接说明找不到，不猜测
4. 对比类问题必须给出"一致"或"不一致"的明确结论

回答示例（注意无 Markdown）：
用户：总包管理服务费费率是多少？
助手：总包管理服务费费率参考范围为1.5%至3.5%，推荐使用2.5%【page_4】。计算基数为分包工程含税建安工程造价【doc_p6】。

用户：2023版与2025版利润率是否一致？
助手：两版利润率范围一致，均为3%～7%，推荐费率均为5%【chunk_x】【chunk_y】。
"""


def _strip_think_tags(text: str) -> str:
    """去掉 <think>...</think> 推理过程"""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _normalize_base_url(base_url: str) -> str:
    base_url = (base_url or "").rstrip("/")
    if not base_url:
        base_url = "https://api.deepseek.com/v1"
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
    return base_url


def _is_local_base_url(base_url: str) -> bool:
    return any(host in base_url for host in ("localhost", "127.0.0.1", "::1"))


def _build_runtime(
    provider: str,
    *,
    model: str,
    base_url: str,
    api_key: str,
    engine: str,
    route_mode: str,
) -> dict[str, Any]:
    normalized_base_url = _normalize_base_url(base_url)
    is_local = _is_local_base_url(normalized_base_url)
    return {
        "provider": provider,
        "model": model,
        "base_url": normalized_base_url,
        "api_key": "none" if is_local else (api_key or "none"),
        "engine": engine,
        "route_mode": route_mode,
        "is_local": is_local,
    }


def resolve_llm_runtimes(
    llm_config: dict[str, Any] | None = None,
    *,
    prefer_strong: bool = False,
) -> list[dict[str, Any]]:
    llm_config = llm_config or {}

    explicit_route = str(llm_config.get("route_mode") or "").strip().lower()
    requested_provider = str(llm_config.get("provider") or "").strip().lower()
    requested_model = str(llm_config.get("model") or "").strip()
    requested_engine = str(llm_config.get("engine") or "").strip()

    configured_base_url = _normalize_base_url(
        llm_config.get("base_url") or _runtime.llm_base_url or "https://api.deepseek.com/v1"
    )

    default_route = "local" if _is_local_base_url(configured_base_url) else "deepseek"
    route_mode = explicit_route or default_route

    deepseek_runtime = _build_runtime(
        "deepseek",
        model=requested_model or _runtime.llm_model,
        base_url=llm_config.get("deepseek_base_url")
        or _runtime.deepseek_base_url
        or configured_base_url,
        api_key=llm_config.get("api_key")
        or (_k if (_k := _runtime.llm_api_key) and _k.isascii() else None)
        or "none",
        engine="api",
        route_mode=route_mode,
    )

    local_runtime = _build_runtime(
        "local",
        model=requested_model
        or _runtime.local_llm_model,
        base_url=llm_config.get("local_base_url")
        or _runtime.local_llm_base_url,
        api_key="none",
        engine=requested_engine or _runtime.local_llm_engine,
        route_mode=route_mode,
    )

    if route_mode == "local" or requested_provider == "local":
        return [local_runtime]
    if route_mode == "deepseek" or requested_provider == "deepseek":
        return [deepseek_runtime]
    if route_mode != "auto":
        return [deepseek_runtime]

    return [deepseek_runtime, local_runtime] if prefer_strong else [local_runtime, deepseek_runtime]


def create_llm(runtime: dict[str, Any], *, thinking: bool = False, streaming: bool = False) -> ChatOpenAI:
    http_async_client = httpx.AsyncClient(trust_env=False) if runtime["is_local"] else None
    http_client = httpx.Client(trust_env=False) if runtime["is_local"] else None
    return ChatOpenAI(
        model=runtime["model"],
        api_key=runtime["api_key"],
        base_url=runtime["base_url"],
        temperature=0.0,
        max_tokens=4096 if thinking else 2048,
        timeout=LLMTimeoutPolicy.get_timeout(runtime),
        http_async_client=http_async_client,
        http_client=http_client,
        streaming=streaming,
    )


def invoke_llm(
    messages: list[Any],
    *,
    thinking: bool = False,
    prefer_strong: bool = False,
    llm_config: dict[str, Any] | None = None,
):
    last_error = None
    for runtime in resolve_llm_runtimes(llm_config, prefer_strong=prefer_strong):
        try:
            response = create_llm(runtime, thinking=thinking).invoke(messages)
            return response, runtime
        except Exception as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError("No LLM runtime available")


def invoke_llm_with_tools(
    messages: list[Any],
    tools: list[Any],
    *,
    tool_choice: str = "auto",
    thinking: bool = False,
    prefer_strong: bool = False,
    llm_config: dict[str, Any] | None = None,
):
    last_error = None
    for runtime in resolve_llm_runtimes(llm_config, prefer_strong=prefer_strong):
        try:
            llm = create_llm(runtime, thinking=thinking).bind_tools(tools, tool_choice=tool_choice)
            response = llm.invoke(messages)
            return response, runtime
        except Exception as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError("No LLM runtime available")


def extract_text_delta(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict):
                maybe_text = item.get("text") or item.get("content")
                if isinstance(maybe_text, str):
                    text_parts.append(maybe_text)
        return "".join(text_parts)
    if isinstance(content, dict):
        maybe_text = content.get("text") or content.get("content")
        return maybe_text if isinstance(maybe_text, str) else ""
    return ""


async def stream_llm_response(
    messages: list[Any],
    *,
    thinking: bool = False,
    prefer_strong: bool = False,
    llm_config: dict[str, Any] | None = None,
):
    last_error = None
    runtimes = resolve_llm_runtimes(llm_config, prefer_strong=prefer_strong)
    for index, runtime in enumerate(runtimes):
        llm = create_llm(runtime, thinking=thinking, streaming=True)
        started = False
        try:
            yield {"type": "runtime", "runtime": runtime, "fallback": index > 0}
            async for chunk in llm.astream(messages):
                delta = extract_text_delta(getattr(chunk, "content", chunk))
                if not delta:
                    continue
                started = True
                yield {"type": "token", "delta": delta, "runtime": runtime}
            return
        except Exception as exc:
            last_error = exc
            if started or index == len(runtimes) - 1:
                raise
    if last_error is not None:
        raise last_error


def get_llm(
    thinking: bool = False,
    prefer_strong: bool = False,
    llm_config: dict[str, Any] | None = None,
):
    runtime = resolve_llm_runtimes(llm_config, prefer_strong=prefer_strong)[0]
    return create_llm(runtime, thinking=thinking)
