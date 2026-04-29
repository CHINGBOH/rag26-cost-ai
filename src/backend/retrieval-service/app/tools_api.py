"""
Agent Toolbox API
=================
把 app.agent.tools 里所有 @tool 装饰的函数暴露为统一的 HTTP 接口，
让前端可以像 agent 一样直接调用每个原子工具。

Endpoints
---------
GET  /api/v1/tools                 -> 列出所有工具及 schema
GET  /api/v1/tools/{name}          -> 单工具元数据
POST /api/v1/tools/{name}/invoke   -> 执行工具，返回结果 + 原始字符串 + 延时

工具来自 LangChain `@tool` 装饰器，自动暴露 .name / .description / .args。
"""

from __future__ import annotations

import json
import time
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agent import tools as _tools_mod

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

# 分类用于前端分组；键名与 tool.name 对齐
_CATEGORIES: Dict[str, str] = {
    "vector_search":     "retrieval",
    "keyword_search":    "retrieval",
    "hybrid_search":     "retrieval",
    "concept_search":    "retrieval",
    "graph_search":      "retrieval",
    "topology_search":   "retrieval",
    "category_search":   "retrieval",
    "text_search":       "retrieval",
    "pdf_page_search":   "retrieval",
    "rule_clause_search": "retrieval",
    "get_catalog_map":   "retrieval",
    "price_query":       "pricing",
    "price_trend":       "pricing",
    "calculator":        "compute",
    "python_eval":       "compute",
}

_EXAMPLES: Dict[str, Dict[str, Any]] = {
    "vector_search":   {"query": "钢筋混凝土工程消耗量", "top_k": 5},
    "keyword_search":  {"query": "送配电装置系统调试", "top_k": 5},
    "hybrid_search":   {"query": "铝合金门窗工 2026-01 价格", "top_k": 5, "path_constraint": ""},
    "concept_search":  {"query": "屋面防水工程", "top_k": 5, "include_evidence": True},
    "graph_search":    {"query": "脚手架综合费用", "top_k": 5},
    "topology_search": {"query": "电气安装工程", "top_k": 5, "max_depth": 2},
    "category_search": {"query": "措施项目费", "top_k": 5},
    "text_search":     {"query": "送配电装置系统调试 计算规则", "top_k": 5, "path_constraint": ""},
    "pdf_page_search": {"query": "脚手架计算规则", "top_k": 5},
    "rule_clause_search": {"query": "建筑面积 计算规则", "top_k": 5},
    "get_catalog_map": {"query": "电气工程", "top_k": 8},
    "price_query":     {"material_name": "钢筋", "specification": "", "year_month": "2026-01", "top_k": 3},
    "price_trend":     {"material_name": "水泥", "start_month": "2025-10", "end_month": "2026-01"},
    "calculator":      {"expression": "1234 * 0.85"},
    "python_eval":     {"code": "result = 1 + 1", "chunks_json": "[]"},
}


def _build_registry() -> List[Dict[str, Any]]:
    """枚举 app.agent.tools 模块里所有 BaseTool 实例并提取 metadata."""
    from langchain_core.tools import BaseTool

    entries: List[Dict[str, Any]] = []
    for name in dir(_tools_mod):
        obj = getattr(_tools_mod, name)
        if not isinstance(obj, BaseTool):
            continue
        try:
            args_schema = obj.args  # langchain helper: dict[name -> {title,type,...}]
        except Exception:
            args_schema = {}
        entries.append({
            "name": obj.name,
            "description": (obj.description or "").strip(),
            "category": _CATEGORIES.get(obj.name, "other"),
            "args": args_schema,
            "example": _EXAMPLES.get(obj.name, {}),
        })
    entries.sort(key=lambda x: (x["category"], x["name"]))
    return entries


def _get_tool(name: str):
    obj = getattr(_tools_mod, name, None)
    from langchain_core.tools import BaseTool
    if not isinstance(obj, BaseTool):
        return None
    return obj


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ToolInvokeRequest(BaseModel):
    args: Dict[str, Any] = {}


class ToolInvokeResponse(BaseModel):
    tool: str
    args: Dict[str, Any]
    result: Any  # 解析后的 JSON（list/dict/str）
    raw: str    # 工具原始返回值
    latency_ms: float
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/api/v1/tools")
async def list_tools():
    """列出所有 agent 工具及其 schema。"""
    registry = _build_registry()
    return {
        "tools": registry,
        "count": len(registry),
        "categories": sorted({t["category"] for t in registry}),
    }


@router.get("/api/v1/tools/{name}")
async def get_tool_meta(name: str):
    tool = _get_tool(name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"tool '{name}' not found")
    try:
        args_schema = tool.args
    except Exception:
        args_schema = {}
    return {
        "name": tool.name,
        "description": (tool.description or "").strip(),
        "category": _CATEGORIES.get(tool.name, "other"),
        "args": args_schema,
        "example": _EXAMPLES.get(tool.name, {}),
    }


@router.post("/api/v1/tools/{name}/invoke", response_model=ToolInvokeResponse)
async def invoke_tool(name: str, request: ToolInvokeRequest):
    tool = _get_tool(name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"tool '{name}' not found")

    args = request.args or {}
    start = time.perf_counter()
    raw_str = ""
    try:
        raw = tool.invoke(args)
        raw_str = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
        try:
            parsed = json.loads(raw_str) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            parsed = raw_str
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info("[tools_api] tool=%s args=%s latency=%sms", name, args, latency_ms)
        return ToolInvokeResponse(
            tool=name,
            args=args,
            result=parsed,
            raw=raw_str,
            latency_ms=latency_ms,
        )
    except Exception as e:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.exception("[tools_api] invoke failed tool=%s args=%s", name, args)
        return ToolInvokeResponse(
            tool=name,
            args=args,
            result=None,
            raw=raw_str,
            latency_ms=latency_ms,
            error=str(e),
        )
