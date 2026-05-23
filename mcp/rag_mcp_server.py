#!/usr/bin/env python3
"""
RAG26 MCP Server — 暴露 RAG26 造价工具给 Hermes/Claude/OpenCode。

通过 HTTP 调用 retrieval-service 的 tool API (:8002/api/v1/tools/*)。
Agent 通过此 MCP Server 获得 41 个造价专业工具，包括：
检索、价格查询、费率查询、沙箱计算、图谱穿透、数据科学、图表生成。

Hermes 配置 (~/.hermes/config.yaml):
  mcp_servers:
    rag26:
      command: "python3"
      args: ["/path/to/rag26-cost-ai/mcp/rag_mcp_server.py"]
      env:
        RAG_URL: "http://localhost:8002"
      timeout: 180
"""

import os
import json
import httpx
from fastmcp import FastMCP

for _k in ("ALL_PROXY", "all_proxy"):
    if os.environ.get(_k, "").startswith("socks://"):
        os.environ.pop(_k, None)
os.environ.setdefault("FASTMCP_NO_VERSION_CHECK", "1")

RAG_URL = os.getenv("RAG_URL", "http://localhost:8002").rstrip("/")
TIMEOUT = float(os.getenv("RAG_TIMEOUT", "180"))

mcp = FastMCP(
    name="RAG26 工程造价知识库",
    instructions=(
        "深圳市建设工程造价专业检索系统。提供材料价格、费率标准、消耗量定额、"
        "工程量计算规则等专业知识查询。所有结果带引用来源和计算过程。\n\n"
        "工具分为 5 类：检索(14)、数据库(8)、图谱(7)、计算(11)、可视化(1)。\n"
        "复杂问题用 agent_query 跑完整推理链。简单查询用对应 tool 直接调用。"
    ),
)


async def _api(method: str, path: str, data: dict | None = None) -> dict:
    url = f"{RAG_URL}{path}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        if method == "GET":
            resp = await client.get(url)
        else:
            resp = await client.post(url, json=data)
        resp.raise_for_status()
        return resp.json()


async def _call_tool(name: str, kwargs: dict) -> str:
    """调用 /api/v1/tools/<name>"""
    try:
        data = await _api("POST", f"/api/v1/tools/{name}", {"kwargs": kwargs})
    except Exception as e:
        return f"工具调用失败: {e}"
    result = data.get("result", data)
    if isinstance(result, (dict, list)):
        return json.dumps(result, ensure_ascii=False, indent=2)
    return str(result)


# ═══════════════════════════════════════════════════════════════════════════
# 核心工具
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def agent_query(question: str, max_iterations: int = 5) -> str:
    """通过完整 Agent 图查询造价知识。自动执行意图分析→概念检索→强制RAG→
    质量评估→ReAct补充推理。返回结构化答案（含计算链、图表数据、引用来源）。
    适用：复杂计算、多步推理、需要格式化呈现的问题。"""
    try:
        data = await _api("POST", "/api/v1/agent", {
            "query": question, "max_iterations": max_iterations,
        })
    except Exception as e:
        return f"Agent 查询失败: {e}"
    answer = data.get("answer", "").strip()
    if not answer:
        return "未找到相关信息。"
    return answer


@mcp.tool()
async def price_query(material_name: str, specification: str = "",
                       year_month: str = "", top_k: int = 5) -> str:
    """查询建设工程材料信息价。返回含税价格、规格、单位、数据期次。"""
    return await _call_tool("price_query", {
        "material_name": material_name,
        "specification": specification,
        "year_month": year_month,
        "top_k": top_k,
    })


@mcp.tool()
async def price_trend(material_name: str, start_month: str = "",
                       end_month: str = "") -> str:
    """查询材料价格历史走势。返回月度均价列表和趋势分析。"""
    return await _call_tool("price_trend", {
        "material_name": material_name,
        "start_month": start_month,
        "end_month": end_month,
    })


@mcp.tool()
async def search(query: str, top_k: int = 8) -> str:
    """混合检索：向量语义+BM25全文+结构化表三路并行，RRF融合排序。"""
    return await _call_tool("hybrid_search", {"query": query, "top_k": top_k})


@mcp.tool()
async def vector_search(query: str, top_k: int = 8) -> str:
    """纯向量语义检索。pgvector 余弦相似度。"""
    return await _call_tool("vector_search", {"query": query, "top_k": top_k})


@mcp.tool()
async def calculator(expression: str) -> str:
    """数学表达式计算。"""
    return await _call_tool("calculator", {"expression": expression})


@mcp.tool()
async def python_eval(code: str) -> str:
    """Python 代码沙箱执行。适合复杂造价计算，返回可复现结果。"""
    return await _call_tool("python_eval", {"code": code})


@mcp.tool()
async def system_info() -> str:
    """RAG26 系统状态：健康检查+知识库统计+自学习状态。"""
    try:
        health = await _api("GET", "/health")
        kb = await _api("GET", "/api/v1/system/kb")
        learning = await _api("GET", "/api/v1/learning/summary")
    except Exception as e:
        return f"查询失败: {e}"
    return json.dumps({
        "health": health, "knowledge_base": kb, "learning": learning,
    }, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
