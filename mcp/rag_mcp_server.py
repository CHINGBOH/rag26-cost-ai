#!/usr/bin/env python3
"""
RAG MCP Server — 把 retrieval-service 包装成 MCP tool 供 opencode 调用。

启动: /home/l/rag-dashboard/venv/bin/python mcp/rag_mcp_server.py
"""

import os

# Remove SOCKS proxy — httpx doesn't support socks:// natively
for _k in ("ALL_PROXY", "all_proxy"):
    if os.environ.get(_k, "").startswith("socks://"):
        os.environ.pop(_k, None)

# Suppress fastmcp version check network call
os.environ.setdefault("FASTMCP_NO_VERSION_CHECK", "1")

import httpx
from fastmcp import FastMCP

RAG_URL = os.getenv("RAG_URL", "http://localhost:8002/api/v1/agent")
TIMEOUT = float(os.getenv("RAG_TIMEOUT", "120"))

mcp = FastMCP(
    name="工程造价RAG知识库",
    instructions=(
        "提供工程造价领域的专业知识查询，包括：\n"
        "- 深圳市建设工程信息价（材料单价、价格走势）\n"
        "- 消耗量标准（人工费、材料费、机械费定额）\n"
        "- 费率标准（安全文明施工费、企业管理费、利润等）\n"
        "- 工程量计算规则\n"
        "需要回答任何工程造价相关问题时，必须先调用 query_rag 工具获取知识库数据。"
    ),
)


@mcp.tool()
async def query_rag(question: str, session_id: str = "opencode") -> str:
    """
    查询工程造价知识库，返回带引用来源的专业答案。

    Args:
        question: 用户的工程造价问题，支持中文自然语言。
        session_id: 会话 ID，用于多轮对话上下文（可选）。

    Returns:
        包含答案、来源引用和置信度信息的文本。
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            resp = await client.post(
                RAG_URL,
                json={"query": question, "session_id": session_id},
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException:
            return "⚠️ 知识库查询超时（>120s），请稍后重试或简化问题。"
        except Exception as e:
            return f"⚠️ 知识库连接失败: {e}"

    answer = data.get("answer", "").strip()
    chunks = data.get("chunks", [])
    iterations = data.get("iterations", 0)
    query_type = data.get("query_type", "")

    if not answer or answer == "知识库中未找到相关信息，无法回答此问题。":
        return "知识库中未找到相关信息。"

    # 附加来源摘要
    sources = []
    seen = set()
    for c in chunks[:5]:
        src = c.get("metadata", {}).get("source") or c.get("doc_id", "")
        if src and src not in seen:
            seen.add(src)
            sources.append(src)

    result = answer
    if sources:
        result += f"\n\n📚 数据来源: {', '.join(sources)}"
    result += f"\n🔍 检索到 {len(chunks)} 条相关记录（迭代 {iterations} 次，类型: {query_type}）"

    return result


if __name__ == "__main__":
    mcp.run(transport="stdio")
