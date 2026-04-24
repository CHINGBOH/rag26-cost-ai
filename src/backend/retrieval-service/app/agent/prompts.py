"""
Agent Prompts + LLM 初始化
"""

import os
import re
from pathlib import Path
import httpx
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

# 加载仓库根目录 .env（从 app/agent/ 往上 5 级 → rag-dashboard/）
load_dotenv(Path(__file__).parents[5] / ".env")

# ALL_PROXY / all_proxy with socks:// scheme causes httpx to fail entirely.
# HTTP_PROXY / HTTPS_PROXY cause local llama-server requests (127.0.0.1) to go
# through the proxy — httpx doesn't honour CIDR ranges in NO_PROXY (127.0.0.0/8).
# Fix: remove ALL_PROXY unconditionally; if LLM_BASE_URL is local, also remove
# HTTP(S)_PROXY so that local inference requests are never proxied.
for _k in ("ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

_llm_url = os.environ.get("LLM_BASE_URL", "")
if any(h in _llm_url for h in ("localhost", "127.0.0.1", "::1")):
    for _k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        os.environ.pop(_k, None)


SYSTEM_PROMPT = """你是工程造价知识库问答助手。根据提供的检索结果回答用户问题。

格式要求（强制）：
- 禁止使用 Markdown 格式符号，包括 # ## ### * ** ` ``` | --- 等
- 用中文标点和换行组织结构，不用横线、星号、井号
- 回答结构：先说结论，再给论据，最后标来源；不写"核心结论""总结"等标题
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


def get_llm(thinking: bool = False, prefer_strong: bool = False):
    """
    初始化 LLM。

    - 本地 llama-server（LLM_BASE_URL 含 localhost/127.0.0.1）：api_key 用 "none"
    - 远程 API（DeepSeek 等）：使用 LLM_API_KEY

    Args:
        thinking: 是否允许更长输出（synthesis 阶段可开启）。
        prefer_strong: 保留参数，当前无实际作用。
    """
    base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    # 确保 base_url 以 /v1 结尾（兼容 llama-server 和 DeepSeek）
    if not base_url.rstrip("/").endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"

    is_local = any(h in base_url for h in ("localhost", "127.0.0.1", "::1"))
    api_key = "none" if is_local else os.getenv("LLM_API_KEY", "none")

    # Local llama-server: bypass proxy env vars entirely so httpx doesn't route
    # http://127.0.0.1:xxx through the system HTTP_PROXY.
    http_client = httpx.AsyncClient(trust_env=False) if is_local else None

    return ChatOpenAI(
        model=os.getenv("LLM_MODEL", "deepseek-chat"),
        api_key=api_key,
        base_url=base_url,
        temperature=0.0,
        max_tokens=4096 if thinking else 2048,
        timeout=120 if is_local else 90,
        http_async_client=http_client,
    )
