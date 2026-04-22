"""
Agent Prompts + LLM 初始化
"""

import os
import re
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

# 加载仓库根目录 .env（从 app/agent/ 往上 5 级 → rag-dashboard/）
load_dotenv(Path(__file__).parents[5] / ".env")


SYSTEM_PROMPT = """你是工程造价知识库问答助手。根据提供的检索结果回答用户问题。

规则：
1. 严格基于检索结果回答，每个关键事实都用【chunk_id】标注来源
2. 数值（金额、比例、系数）必须来自检索结果原文，不得编造
3. 检索结果不足时明确说明，不要猜测

示例（注意引用格式）：
用户：总包管理服务费费率是多少？
助手：总包管理服务费费率参考范围为1.5%至3.5%，推荐使用2.5%【page_4】。计算基数为分包工程含税建安工程造价【doc_xxx_p6_c10】。
"""


def _strip_think_tags(text: str) -> str:
    """去掉 <think>...</think> 推理过程"""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def get_llm(thinking: bool = False, prefer_strong: bool = False):
    """
    初始化 LLM。

    Args:
        thinking: 是否允许 Qwen3 输出 thinking 标签（synthesis 阶段可开启）。
        prefer_strong: 跳过本地模型，直接使用 DeepSeek API（规划/合成阶段推荐）。
    """
    local_url = "http://localhost:8080/v1"
    import urllib.request

    if not prefer_strong:
        try:
            urllib.request.urlopen(local_url.replace("/v1", "/health"), timeout=2)
            max_tokens = 2048 if thinking else 1024
            return ChatOpenAI(
                model="qwen3:8b",
                api_key="sk-local",
                base_url=local_url,
                temperature=0.1,
                max_tokens=max_tokens,
            )
        except Exception:
            pass

    # DeepSeek API（prefer_strong=True 或本地不可用时使用）
    return ChatOpenAI(
        model=os.getenv("LLM_MODEL", "deepseek-chat"),
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
        temperature=0.1,
        max_tokens=2048 if thinking else 1024,
        timeout=40,  # 40s 超时，防止 planner 卡死
    )
