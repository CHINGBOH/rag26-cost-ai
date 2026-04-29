"""
FastAPI 路由定义
/api/v1/search, /rerank, /evaluate, /decompose, /health, /rag
"""

import uuid
import re
import logging
import os
import time
import json
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks
from datetime import datetime
from langchain_core.messages import HumanMessage

from domain_models.retrieval import RetrievalRequest, RetrievalConfig
from domain_models.api import APIResponse
from app.models import (
    SearchRequest,
    RerankRequest,
    EvaluationRequest,
    DecomposeRequest,
)
from infrastructure.reranker_service import get_reranker_service
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

# 全局服务实例（由 main.py 在 lifespan 中注入）
pipeline = None
store = None


def set_services(pipeline_instance, store_instance):
    global pipeline, store
    pipeline = pipeline_instance
    store = store_instance


@router.get("/health")
async def health_check():
    """健康检查 - 四库状态"""
    if store:
        health = store.health_check()
        all_healthy = all(v == "healthy" for v in health.values())
        return {
            "status": "ok" if all_healthy else "degraded",
            "services": health,
            "timestamp": datetime.now().isoformat(),
        }
    return {"status": "error", "message": "Store not initialized"}


@router.post("/api/v1/search", response_model=APIResponse[Dict[str, Any]])
async def search(request: SearchRequest):
    """混合检索（向量+关键词+图）"""
    global pipeline

    if not pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")

    try:
        config = RetrievalConfig(
            vector_top_k=30 if request.mode in ["vector", "hybrid"] else 0,
            keyword_top_k=20 if request.mode in ["keyword", "hybrid"] else 0,
            graph_top_k=10 if request.mode in ["graph", "hybrid"] else 0,
        )

        retrieval_request = RetrievalRequest(
            query=request.query, config=config, session_id=request.session_id
        )

        response = pipeline.retrieve(retrieval_request)

        return APIResponse.success(
            {
                "request_id": response.request_id,
                "query": request.query,
                "results": [
                    {
                        "chunk_id": doc.chunk_id,
                        "doc_id": doc.doc_id,
                        "content": doc.content[:500] + "..."
                        if len(doc.content) > 500
                        else doc.content,
                        "score": round(doc.score, 4),
                        "metadata": doc.metadata,
                    }
                    for doc in response.documents[: request.top_k]
                ],
                "latency_ms": round(response.latency_ms, 2),
                "stats": response.stats,
            }
        )

    except Exception as e:
        logger.error(f"Search error: {e}")
        return APIResponse.error(str(e), "SEARCH_ERROR")


@router.post("/api/v1/rerank")
async def rerank_documents(request: RerankRequest):
    """精排 - 兼容 documents 和 candidates 两种字段"""
    try:
        # 统一转换为 (id, content) 列表
        if request.documents is not None:
            docs = [
                {
                    "id": doc.get("id", f"doc_{i}"),
                    "content": doc.get("content", ""),
                    "score": doc.get("score", 0.5),
                }
                for i, doc in enumerate(request.documents)
            ]
        else:
            docs = [
                {
                    "id": f"doc_{i}",
                    "content": cand,
                    "score": 0.5,
                }
                for i, cand in enumerate(request.candidates)
            ]

        if not docs:
            return {"results": [], "query": request.query}

        # 提取内容用于 rerank
        contents = [d["content"] for d in docs]

        reranker = get_reranker_service()
        scores = reranker.rerank(request.query, contents)

        results = []
        for i, (doc, score) in enumerate(zip(docs, scores)):
            results.append(
                {
                    "id": doc["id"],
                    "content": doc["content"][:200]
                    if len(doc["content"]) > 200
                    else doc["content"],
                    "score": float(score),
                    "original_index": i,
                }
            )

        results.sort(key=lambda x: x["score"], reverse=True)
        return {"results": results[: request.top_k], "query": request.query}

    except Exception as e:
        logger.error(f"Rerank error: {e}")
        # 降级处理
        docs_source = request.documents or [
            {"id": f"doc_{i}", "content": c, "score": 0.5}
            for i, c in enumerate(request.candidates or [])
        ]
        return {
            "results": [
                {
                    "id": doc.get("id", f"doc_{i}"),
                    "content": doc.get("content", "")[:200]
                    if len(doc.get("content", "")) > 200
                    else doc.get("content", ""),
                    "score": doc.get("score", 0.5),
                }
                for i, doc in enumerate(docs_source[: request.top_k])
            ],
            "query": request.query,
            "error": str(e),
        }


@router.post("/api/v1/evaluate")
async def evaluate_retrieval(request: EvaluationRequest):
    """检索质量评估"""
    try:
        chunks = request.retrieved_chunks

        # 基础分数
        avg_score = sum(c.get("score", 0) for c in chunks) / len(chunks) if chunks else 0

        # 来源多样性
        sources = set(c.get("source", "") for c in chunks)
        source_diversity = min(len(sources) / 3, 1.0)

        # 信息增益（随轮次递减）
        information_gain = max(0.1, 0.5 - request.history_rounds * 0.1)

        # 完整性
        total_length = sum(len(c.get("content", "")) for c in chunks)
        completeness = min(total_length / 2000, 0.95)

        # 一致性
        scores = [c.get("score", 0) for c in chunks]
        if scores:
            avg = sum(scores) / len(scores)
            variance = sum((s - avg) ** 2 for s in scores) / len(scores)
            consistency = max(0.5, 1 - variance)
        else:
            consistency = 0.5

        # 事实一致性（基于引用数量）
        citations = re.findall(r"\[\d+\]", request.generated_answer)
        fact_consistency = min(0.5 + len(citations) * 0.1, 0.95)

        # 覆盖率
        coverage_estimate = min(avg_score * source_diversity * 1.5, 0.95)

        # 置信度
        confidence = (completeness + consistency + fact_consistency + source_diversity) / 4

        return {
            "completeness": round(completeness, 4),
            "consistency": round(consistency, 4),
            "confidence": round(confidence, 4),
            "information_gain": round(information_gain, 4),
            "source_diversity": round(source_diversity, 4),
            "fact_consistency": round(fact_consistency, 4),
            "coverage_estimate": round(coverage_estimate, 4),
        }
    except Exception as e:
        logger.error(f"Evaluation error: {e}")
        return {
            "completeness": 0.5,
            "consistency": 0.5,
            "confidence": 0.5,
            "information_gain": 0.3,
            "source_diversity": 0.5,
            "fact_consistency": 0.5,
            "coverage_estimate": 0.5,
        }


@router.post("/api/v1/decompose")
async def decompose_query(request: DecomposeRequest):
    """查询分解"""
    query = request.query
    sub_queries = []

    sub_queries.append(
        {
            "id": f"sq_{uuid.uuid4().hex[:8]}",
            "query": f"{query} 基础概念定义",
            "targetDB": "vector",
            "status": "pending",
        }
    )

    sub_queries.append(
        {
            "id": f"sq_{uuid.uuid4().hex[:8]}",
            "query": f"{query} 实现方法 技术细节",
            "targetDB": "knowledge",
            "status": "pending",
        }
    )

    if any(kw in query for kw in ["如何", "怎么", "怎样", "案例", "示例"]):
        sub_queries.append(
            {
                "id": f"sq_{uuid.uuid4().hex[:8]}",
                "query": f"{query} 实际案例 应用示例",
                "targetDB": "graph",
                "status": "pending",
            }
        )

    if any(kw in query for kw in ["区别", "对比", "比较", "vs", "versus"]):
        sub_queries.append(
            {
                "id": f"sq_{uuid.uuid4().hex[:8]}",
                "query": f"{query} 对比分析 优缺点",
                "targetDB": "vector",
                "status": "pending",
            }
        )

    return {"sub_queries": sub_queries, "original_query": query}


# ── LangGraph RAG ──────────────────────────────────────────────────────────────

class RAGRequest(BaseModel):
    query: str
    session_id: Optional[str] = None


@router.post("/api/v1/rag")
async def rag_query(request: RAGRequest):
    """
    LangGraph RAG pipeline: retrieve → rerank → generate
    替代 Node.js XState 编排，直接返回完整结果。
    """
    if not request.query or not request.query.strip():
        raise HTTPException(status_code=400, detail="query 不能为空")

    import asyncio
    from app.rag_pipeline import run_rag

    try:
        # run_rag 是同步的，放到线程池避免阻塞事件循环
        result = await asyncio.to_thread(run_rag, request.query.strip(), pipeline)
        return {
            "session_id": request.session_id,
            "query": result["query"],
            "answer": result["answer"],
            "chunks": result["chunks"],
            "error": result.get("error"),
        }
    except Exception as e:
        logger.error(f"RAG pipeline error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── LangGraph ReAct Agent ─────────────────────────────────────────────────────

def _normalize_chunk(c: dict) -> dict:
    """Normalize internal chunk dict to match frontend AgentChunk / RetrievalChunk schema."""
    doc_id = str(c.get("doc_id", ""))
    page = c.get("page_number") or c.get("page") or 0
    score = c.get("score", 0.0)
    return {
        "chunk_id": f"tc_{doc_id}_{page}",
        "doc_id": doc_id,
        "page": page,
        "content": c.get("content", ""),
        "score": round(float(score), 4),
        "passed_threshold": score >= 0.60,
        "source": c.get("doc_filename") or c.get("source", ""),
        "metadata": {
            "page": page,
            "filename": c.get("doc_filename") or c.get("source", ""),
        },
    }


class AgentRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    max_iterations: int = 3
    llm_route: str = "deepseek"
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_engine: Optional[str] = None


@router.post("/api/v1/agent")
async def agent_query(request: AgentRequest):
    """
    LangGraph ReAct Agent: retrieve → evaluate → loop
    替代线性 RAG，支持自主选工具和迭代优化。
    """
    if not request.query or not request.query.strip():
        raise HTTPException(status_code=400, detail="query 不能为空")

    import asyncio
    from app.agent.graph import get_agent_graph

    try:
        graph = get_agent_graph()
        thread_id = request.session_id or str(uuid.uuid4())
        # 每次请求使用独立 thread_id，避免 MemorySaver 在同一 session 内
        # 累积历史消息（含上次未清理的 tool_calls），导致 DeepSeek HTTP 400
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        initial_state = {
            "query": request.query.strip(),
            "query_type": "",
            "sub_queries": [],
            "messages": [],
            "iterations": 0,
            "max_iterations": request.max_iterations,
            "retrieved_chunks": [],
            "evaluation": None,
            "final_answer": "",
            "tool_call_cache": {},
            "calculation_inputs": {},
            "plan": [],
            "current_step": 0,
            "thought_process": [],
            "category_hints": [],
            "fallback_mode": False,
            "has_tool_calls": False,
            "llm_config": {
                "route_mode": request.llm_route,
                "provider": request.llm_provider,
                "model": request.llm_model,
                "engine": request.llm_engine,
            },
            "llm_runtime": {},
            "stream_response": False,
            "synthesis_prompt": "",
            "citations_text": "",
            "step_number": 0,
            "total_steps": 0,
            "step_hint": "",
            "pending_tool_calls": [],
            "step_summary": "",
            "presentation": None,
            "presentation_policy": None,
            "roadmap": [],
            "workspace": [],
            # Iterative convergence / outer-loop contract verification
            "contract_results": [],
            "outer_iteration": 0,
            "max_outer_iterations": 3,
            "quality_converged": False,
            "corrective_actions": [],
            "root_cause_node": "",
            "tool_fallback_level": 0,
            "used_tool_categories": [],
        }
        result = await asyncio.to_thread(graph.invoke, initial_state, config=config)
        return {
            "session_id": thread_id,
            "query": result["query"],
            "query_type": result.get("query_type", ""),
            "answer": result.get("final_answer", ""),
            "chunks": [_normalize_chunk(c) for c in result.get("retrieved_chunks", [])],
            "evaluation": result.get("evaluation"),
            "iterations": result.get("iterations", 0),
            "runtime": result.get("llm_runtime", {}),
            "presentation": result.get("presentation"),
            "followup_suggestions": result.get("followup_suggestions") or [],
            "data_gaps": result.get("data_gaps") or [],
        }
    except Exception as e:
        logger.error(f"Agent pipeline error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Agent Streaming (SSE) ─────────────────────────────────────────────────────

import asyncio
import json
from fastapi.responses import StreamingResponse


class AgentStreamRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    max_iterations: int = 3
    score_threshold: float = 0.60
    top_k: int = 8
    search_mode: str = "hybrid"
    doc_types: list = []
    llm_route: str = "deepseek"
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_engine: Optional[str] = None


def _sse_event(event_type: str, data: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _build_llm_config(request: AgentStreamRequest | AgentRequest) -> dict[str, Any]:
    return {
        "route_mode": request.llm_route,
        "provider": request.llm_provider,
        "model": request.llm_model,
        "engine": request.llm_engine,
    }


@router.post("/api/v1/agent/stream")
async def agent_query_stream(request: AgentStreamRequest):
    """Streaming Agent via SSE. Use fetch() with AbortController on frontend."""
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="query 不能为空")

    session_id = request.session_id or str(uuid.uuid4())

    async def event_generator():
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()
        llm_config = _build_llm_config(request)
        start_time = loop.time()

        yield _sse_event("progress", {"stage": "analysis", "message": "正在理解问题..."})
        await asyncio.sleep(0)

        def run_graph():
            try:
                from app.agent.graph import get_agent_graph

                graph = get_agent_graph()
                # 每次 stream 请求使用独立 thread_id，防止跨请求消息状态污染
                config = {"configurable": {"thread_id": str(uuid.uuid4())}}
                initial_state = {
                    "query": request.query.strip(),
                    "query_type": "",
                    "sub_queries": [],
                    "messages": [],
                    "iterations": 0,
                    "max_iterations": request.max_iterations,
                    "retrieved_chunks": [],
                    "evaluation": None,
                    "final_answer": "",
                    "tool_call_cache": {},
                    "calculation_inputs": {},
                    "plan": [],
                    "current_step": 0,
                    "thought_process": [],
                    "category_hints": [],
                    "fallback_mode": False,
                    "has_tool_calls": False,
                    "llm_config": llm_config,
                    "llm_runtime": {},
                    "stream_response": True,
                    "synthesis_prompt": "",
                    "citations_text": "",
                    "step_number": 0,
                    "total_steps": 0,
                    "step_hint": "",
                    "pending_tool_calls": [],
                    "step_summary": "",
                    "presentation": None,
                    "presentation_policy": None,
                    "roadmap": [],
                    "workspace": [],
                    # Iterative convergence / outer-loop contract verification
                    "contract_results": [],
                    "outer_iteration": 0,
                    "max_outer_iterations": 3,
                    "quality_converged": False,
                    "corrective_actions": [],
                    "root_cause_node": "",
                    "tool_fallback_level": 0,
                    "used_tool_categories": [],
                }
                for chunk in graph.stream(initial_state, config=config):
                    loop.call_soon_threadsafe(queue.put_nowait, ("chunk", chunk))
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, ("error", str(e)))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, ("done", None))

        import threading
        t = threading.Thread(target=run_graph, daemon=True)
        t.start()

        final_answer = ""
        total_iterations = 0
        seen_chunk_ids: set[str] = set()
        retrieved_chunks_accum: list[dict[str, Any]] = []
        current_runtime: dict[str, Any] = {}
        current_plan: list[str] = []
        current_presentation: dict[str, Any] | None = None
        current_query_type = ""

        while True:
            try:
                kind, payload = await asyncio.wait_for(queue.get(), timeout=150.0)
            except asyncio.TimeoutError:
                yield _sse_event("error", {"message": "请求超时，请稍后重试", "code": "TIMEOUT"})
                break

            if kind == "error":
                yield _sse_event("error", {"message": payload, "code": "AGENT_ERROR"})
                break

            if kind == "done":
                elapsed_ms = int((loop.time() - start_time) * 1000)
                # Round 7: compute followup chips here so they ship with `done`
                try:
                    from app.agent.graph import build_followup_suggestions as _build_followups
                    followups = _build_followups(
                        request.query.strip(),
                        list(retrieved_chunks_accum or []),
                        final_answer or "",
                        max_n=5,
                    )
                except Exception as _e:
                    logger.debug(f"[stream] followups failed: {_e}")
                    followups = []
                if followups:
                    yield _sse_event("followup_suggestions", {"suggestions": followups})
                try:
                    from app.agent.graph import _gather_blindspots_for_chunks as _gbs
                    data_gaps = _gbs(list(retrieved_chunks_accum or []))
                except Exception:
                    data_gaps = []
                if data_gaps:
                    yield _sse_event("data_gaps", {"gaps": data_gaps})
                yield _sse_event(
                    "done",
                    {
                        "answer": final_answer,
                        "session_id": session_id,
                        "iterations": total_iterations,
                        "latency_ms": elapsed_ms,
                        "provider": current_runtime.get("provider"),
                        "model": current_runtime.get("model"),
                        "engine": current_runtime.get("engine"),
                        "route_mode": current_runtime.get("route_mode") or llm_config.get("route_mode"),
                        "presentation": current_presentation,
                        "followup_suggestions": followups,
                        "data_gaps": data_gaps,
                    },
                )
                break

            # kind == "chunk"
            chunk = payload
            node_name = list(chunk.keys())[0]
            node_output = chunk[node_name]

            if node_name == "query_analysis":
                analysis = {
                    "intent": node_output.get("query_type", ""),
                    "sub_queries": node_output.get("sub_queries", []),
                    "entities": {},
                }
                current_query_type = node_output.get("query_type", "") or ""
                yield _sse_event("query_analysis", analysis)
                # chitchat / off-topic：直接以 token 事件推送答案（图在此结束，synthesize 不会运行）
                off_answer = node_output.get("final_answer", "")
                if off_answer:
                    final_answer = off_answer
                    yield _sse_event("synthesizing", {"provider": "builtin", "model": "builtin", "engine": "default", "route_mode": llm_config.get("route_mode")})
                    yield _sse_event("token", {"delta": off_answer})

            elif node_name == "planner_node":
                # 规划完成，发送步骤列表供前端展示进度
                plan = node_output.get("plan", [])
                current_plan = plan
                runtime = node_output.get("llm_runtime") or current_runtime
                if runtime:
                    current_runtime = runtime
                yield _sse_event("progress", {"stage": "planning", "message": "制定检索计划..."})
                yield _sse_event("plan", {"steps": plan})

            elif node_name == "executor_node":
                total_iterations = node_output.get("iterations", total_iterations)
                runtime = node_output.get("llm_runtime") or current_runtime
                if runtime:
                    current_runtime = runtime
                step_number = node_output.get("step_number", 0)
                total_steps = node_output.get("total_steps", 0)
                step_hint = node_output.get("step_hint", "")
                if step_number:
                    yield _sse_event(
                        "executing",
                        {
                            "step": step_number,
                            "total": total_steps,
                            "message": f"执行步骤 {step_number}/{max(total_steps, 1)}",
                            "query": step_hint,
                        },
                    )
                for tool_call in node_output.get("pending_tool_calls", []) or []:
                    yield _sse_event(
                        "tool_call_start",
                        {
                            "call_id": tool_call.get("id", ""),
                            "tool": tool_call.get("name", ""),
                            "args": tool_call.get("args", {}),
                            "step": step_number,
                            "total": total_steps,
                        },
                    )
                step_summary = node_output.get("step_summary")
                if step_summary:
                    yield _sse_event(
                        "step_done",
                        {
                            "step": step_number,
                            "total": total_steps,
                            "message": step_summary,
                        },
                    )

            elif node_name == "tool_node":
                # 新增 chunks → 逐条 emit retrieval_result
                for c in node_output.get("retrieved_chunks", []):
                    normalized = _normalize_chunk(c)
                    chunk_id = normalized["chunk_id"]
                    if chunk_id in seen_chunk_ids:
                        continue
                    seen_chunk_ids.add(chunk_id)
                    retrieved_chunks_accum.append(c)
                    yield _sse_event("retrieval_result", normalized)
                # tool call results
                for msg in node_output.get("messages", []):
                    if hasattr(msg, "name") and hasattr(msg, "content"):
                        tool_data = {
                            "call_id": getattr(msg, "tool_call_id", ""),
                            "tool": msg.name,
                            "result_summary": str(msg.content)[:200],
                            "duration_ms": 0,
                        }
                        yield _sse_event("tool_call_end", tool_data)
                yield _sse_event(
                    "step_done",
                    {
                        "step": node_output.get("current_step", 0) + 1,
                        "total": max(len(current_plan), 1),
                        "message": f"当前已检索到 {len(node_output.get('retrieved_chunks', []))} 个相关片段",
                    },
                )

            elif node_name == "synthesize_node":
                prompt = node_output.get("synthesis_prompt", "")
                eval_result = node_output.get("evaluation") or {}
                runtime = node_output.get("llm_runtime") or current_runtime
                citations_text = node_output.get("citations_text", "")
                from app.agent.graph import refine_citations_for_answer, finalize_presentation_payload
                presentation = node_output.get("presentation")
                if presentation:
                    current_presentation = presentation
                    yield _sse_event("presentation", presentation)

                if prompt:
                    try:
                        from app.agent.prompts import stream_llm_response

                        async for stream_event in stream_llm_response(
                            [HumanMessage(content=prompt)],
                            thinking=False,
                            prefer_strong=False,
                            llm_config=llm_config,
                        ):
                            if stream_event["type"] == "runtime":
                                runtime = stream_event["runtime"]
                                current_runtime = runtime
                                yield _sse_event(
                                    "synthesizing",
                                    {
                                        "provider": runtime.get("provider"),
                                        "model": runtime.get("model"),
                                        "engine": runtime.get("engine"),
                                        "route_mode": runtime.get("route_mode"),
                                        "fallback": stream_event.get("fallback", False),
                                    },
                                )
                                continue

                            delta = stream_event["delta"]
                            final_answer += delta
                            yield _sse_event("token", {"delta": delta})
                    except Exception as exc:
                        yield _sse_event("error", {"message": str(exc), "code": "SYNTHESIS_ERROR"})
                        break
                else:
                    answer = node_output.get("final_answer", "")
                    if answer:
                        final_answer = answer
                        yield _sse_event("token", {"delta": answer})

                if citations_text:
                    citations_text = refine_citations_for_answer(
                        final_answer,
                        node_output.get("retrieved_chunks", []) or [],
                        citations_text,
                    )
                    final_answer = re.split(r"\n\s*(?:【参考索引】|参考索引[:：])", final_answer, maxsplit=1)[0].strip()
                    citations_delta = ("\n\n" if final_answer else "") + citations_text
                    final_answer += citations_delta
                    yield _sse_event("token", {"delta": citations_delta})

                final_presentation = finalize_presentation_payload(
                    query=request.query.strip(),
                    query_type=current_query_type,
                    final_answer=final_answer,
                    chunks=node_output.get("retrieved_chunks", []) or [],
                    citations_text=citations_text,
                    existing_presentation=current_presentation,
                )
                if final_presentation and final_presentation != current_presentation:
                    current_presentation = final_presentation
                    yield _sse_event("presentation", final_presentation)
                elif final_presentation:
                    current_presentation = final_presentation

                if eval_result:
                    scores = {
                        "completeness": eval_result.get("completeness", 0),
                        "consistency": eval_result.get("consistency", 0),
                        "confidence": eval_result.get("confidence", 0),
                        "information_gain": eval_result.get("information_gain", 0),
                        "source_diversity": eval_result.get("source_diversity", 0),
                        "fact_consistency": eval_result.get("fact_consistency", 0),
                        "coverage_estimate": eval_result.get("coverage_estimate", 0),
                    }
                    yield _sse_event("eval_scores", scores)
                    loop_data = {
                        "iteration": total_iterations,
                        "eval_score": eval_result.get("confidence", 0),
                        "max_iterations": request.max_iterations,
                    }
                    yield _sse_event("loop_state", loop_data)

            elif node_name == "presentation_policy_node":
                presentation = node_output.get("presentation")
                if presentation:
                    if presentation != current_presentation:
                        current_presentation = presentation
                        yield _sse_event("presentation", presentation)
                    else:
                        current_presentation = presentation

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── Feedback ──────────────────────────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    session_id: str
    message_id: str
    rating: int  # +1 or -1
    comment: Optional[str] = None
    query: Optional[str] = None
    answer_summary: Optional[str] = None


@router.post("/api/v1/feedback")
async def submit_feedback(request: FeedbackRequest):
    """Store user feedback to JSONL file until conversations table exists."""
    import time
    import os
    record = {
        "ts": time.time(),
        "session_id": request.session_id,
        "message_id": request.message_id,
        "rating": request.rating,
        "comment": request.comment,
        "query": request.query,
        "answer_summary": request.answer_summary,
    }
    feedback_path = os.environ.get("FEEDBACK_LOG_PATH", "/tmp/rag_feedback.jsonl")
    try:
        with open(feedback_path, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"status": "ok", "message_id": request.message_id}
    except Exception as e:
        logger.error(f"Feedback write error: {e}")
        raise HTTPException(status_code=500, detail="Failed to save feedback")


# ── Health Detail & Metrics ───────────────────────────────────────────────────

@router.get("/api/v1/health/detail")
async def health_detail():
    """Per-service health with latency."""
    import httpx
    import time
    import asyncio
    http_services = {
        "python_legacy": "http://localhost:8000/health",
        "retrieval": "http://localhost:8002/health",
        "ocr": "http://localhost:8001/health",
        "qdrant": "http://localhost:6333/healthz",
        "go_gateway": "http://localhost:8080/health",
        "nodejs": "http://localhost:3001/health",
    }
    results = {}
    async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
        for name, url in http_services.items():
            t0 = time.monotonic()
            try:
                r = await client.get(url)
                latency_ms = int((time.monotonic() - t0) * 1000)
                results[name] = {
                    "status": "healthy" if r.status_code == 200 else "degraded",
                    "latency_ms": latency_ms,
                }
            except Exception:
                results[name] = {"status": "unhealthy", "latency_ms": -1}
    # PostgreSQL: TCP probe (no HTTP endpoint)
    t0 = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("localhost", 5432), timeout=2.0
        )
        writer.close()
        await writer.wait_closed()
        results["postgresql"] = {
            "status": "healthy",
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception:
        results["postgresql"] = {"status": "unhealthy", "latency_ms": -1}
    return {"services": results, "timestamp": datetime.now().isoformat()}


# ── Sandbox Code Execution ────────────────────────────────────────────────────

class SandboxRequest(BaseModel):
    code: str
    timeout: Optional[int] = None  # 覆盖默认超时（秒），最大 30


@router.post("/api/v1/sandbox/execute")
async def sandbox_execute(request: SandboxRequest):
    """
    在 Docker 沙箱中安全执行 Python 代码。
    - 无网络、内存 256M、CPU 1 核、10 秒超时
    - 禁止 import / 文件写入等危险操作
    """
    from infrastructure.sandbox import execute_python, SANDBOX_TIMEOUT
    import asyncio

    if not request.code or not request.code.strip():
        raise HTTPException(status_code=400, detail="code 不能为空")

    timeout = min(request.timeout or SANDBOX_TIMEOUT, 30)

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, execute_python, request.code
        )
        return result
    except Exception as e:
        logger.error(f"[sandbox route] error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/sandbox/health")
async def sandbox_health():
    """检查沙箱镜像是否存在且可用"""
    from infrastructure.sandbox import _check_image_exists, SANDBOX_IMAGE
    ok = _check_image_exists()
    return {
        "status": "ready" if ok else "unavailable",
        "image": SANDBOX_IMAGE,
    }


@router.get("/api/v1/metrics/llm")
async def metrics_llm():
    """Forward llama-server metrics."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://localhost:8003/metrics")
            return {"raw": r.text[:2000], "status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Learning Loop ─────────────────────────────────────────────────────────────

import os as _os_learn

_LEARN_DIR = _os_learn.environ.get("AGENT_RUN_LOG_DIR", "/home/l/rag-dashboard/data/learning")
_FEEDBACK_PATH = _os_learn.environ.get("FEEDBACK_LOG_PATH", "/tmp/rag_feedback.jsonl")


def _read_jsonl(path: str, limit: int = 500) -> list[dict]:
    if not _os_learn.path.exists(path):
        return []
    rows: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.warning(f"read jsonl failed {path}: {e}")
        return []
    return rows[-limit:]


@router.get("/api/v1/learning/runs")
async def learning_runs(limit: int = 50, quality: Optional[str] = None):
    """Recent agent runs from JSONL log. Filter by quality=failure|weak|good."""
    runs = _read_jsonl(_os_learn.path.join(_LEARN_DIR, "agent_runs.jsonl"), limit=max(limit * 4, 200))
    if quality:
        runs = [r for r in runs if r.get("quality") == quality]
    runs.reverse()  # newest first
    return {"runs": runs[:limit], "total_in_window": len(runs)}


@router.get("/api/v1/learning/summary")
async def learning_summary():
    """Aggregate stats over recent agent runs + feedback."""
    runs = _read_jsonl(_os_learn.path.join(_LEARN_DIR, "agent_runs.jsonl"), limit=500)
    feedback = _read_jsonl(_FEEDBACK_PATH, limit=500)

    total = len(runs)
    by_quality = {"good": 0, "weak": 0, "failure": 0}
    refused = 0
    confidence_sum = 0.0
    confidence_n = 0
    tool_freq: dict[str, int] = {}
    type_freq: dict[str, int] = {}

    for r in runs:
        q = r.get("quality") or "unknown"
        by_quality[q] = by_quality.get(q, 0) + 1
        if r.get("refused"):
            refused += 1
        ev = r.get("evaluation") or {}
        c = ev.get("confidence")
        if isinstance(c, (int, float)):
            confidence_sum += float(c)
            confidence_n += 1
        for t in r.get("tools_used", []) or []:
            tool_freq[t] = tool_freq.get(t, 0) + 1
        qt = r.get("query_type") or "unknown"
        type_freq[qt] = type_freq.get(qt, 0) + 1

    pos = sum(1 for fb in feedback if fb.get("rating", 0) > 0)
    neg = sum(1 for fb in feedback if fb.get("rating", 0) < 0)

    avg_conf = (confidence_sum / confidence_n) if confidence_n else 0.0
    return {
        "total_runs": total,
        "by_quality": by_quality,
        "refused_count": refused,
        "avg_confidence": round(avg_conf, 3),
        "tool_frequency": dict(sorted(tool_freq.items(), key=lambda kv: -kv[1])[:20]),
        "type_frequency": type_freq,
        "feedback": {
            "positive": pos,
            "negative": neg,
            "total": len(feedback),
        },
    }


@router.get("/api/v1/learning/gaps")
async def learning_gaps(limit: int = 30):
    """Distinct failed/weak queries — surface knowledge gaps."""
    runs = _read_jsonl(_os_learn.path.join(_LEARN_DIR, "agent_runs.jsonl"), limit=500)
    seen: set[str] = set()
    gaps: list[dict] = []
    for r in reversed(runs):
        if r.get("quality") not in ("failure", "weak"):
            continue
        q = (r.get("query") or "").strip()
        if not q or q in seen:
            continue
        seen.add(q)
        gaps.append({
            "query": q,
            "ts": r.get("ts"),
            "quality": r.get("quality"),
            "refused": bool(r.get("refused")),
            "chunks_count": r.get("chunks_count", 0),
            "confidence": (r.get("evaluation") or {}).get("confidence", 0),
            "answer_preview": (r.get("answer") or "")[:200],
        })
        if len(gaps) >= limit:
            break
    return {"gaps": gaps}


# ── Ops Metrics (in-memory request counter) ───────────────────────────────────

from collections import deque
import time as _time_ops
import threading as _threading_ops

_OPS_LOCK = _threading_ops.Lock()
_OPS_REQUESTS: deque = deque(maxlen=2000)  # (ts, latency_ms, status_code, path)


def ops_record_request(latency_ms: float, status_code: int, path: str) -> None:
    """Called by middleware on every HTTP response."""
    with _OPS_LOCK:
        _OPS_REQUESTS.append((_time_ops.time(), float(latency_ms), int(status_code), path))


@router.get("/api/v1/ops/metrics")
async def ops_metrics(window_sec: int = 60):
    """Aggregated request metrics over the last `window_sec` seconds."""
    now = _time_ops.time()
    cutoff = now - window_sec
    with _OPS_LOCK:
        recent = [r for r in _OPS_REQUESTS if r[0] >= cutoff]
        all_recent = list(_OPS_REQUESTS)

    n = len(recent)
    if n == 0:
        return {
            "window_sec": window_sec,
            "requests": 0,
            "qps": 0.0,
            "p50_ms": 0,
            "p95_ms": 0,
            "p99_ms": 0,
            "error_rate": 0.0,
            "by_status": {},
            "top_paths": [],
            "qps_buckets": [],
        }

    latencies = sorted(r[1] for r in recent)

    def _pct(p: float) -> int:
        idx = min(len(latencies) - 1, int(len(latencies) * p))
        return int(latencies[idx])

    by_status: dict[str, int] = {}
    paths: dict[str, int] = {}
    errors = 0
    for _, _, code, path in recent:
        key = f"{code // 100}xx"
        by_status[key] = by_status.get(key, 0) + 1
        if code >= 400:
            errors += 1
        # collapse path to bucket
        bucket = path.split("?")[0]
        paths[bucket] = paths.get(bucket, 0) + 1

    # 1-second QPS buckets for sparkline (last 60s window)
    bucket_count = min(window_sec, 60)
    buckets = [0] * bucket_count
    base = now - bucket_count
    for ts, _, _, _ in recent:
        idx = int(ts - base)
        if 0 <= idx < bucket_count:
            buckets[idx] += 1

    top_paths = sorted(paths.items(), key=lambda kv: -kv[1])[:10]

    return {
        "window_sec": window_sec,
        "requests": n,
        "qps": round(n / max(window_sec, 1), 2),
        "p50_ms": _pct(0.50),
        "p95_ms": _pct(0.95),
        "p99_ms": _pct(0.99),
        "error_rate": round(errors / n, 4),
        "by_status": by_status,
        "top_paths": [{"path": p, "count": c} for p, c in top_paths],
        "qps_buckets": buckets,
        "total_recorded": len(all_recent),
    }


# ── System Endpoints (real config / kb stats / version) ──────────────────────

import subprocess as _subp_sys
import platform as _plat_sys


@router.get("/api/v1/system/version")
async def system_version():
    """Git commit hash, build time, python version, service start time."""
    try:
        sha = _subp_sys.check_output(
            ["git", "-C", "/home/l/rag-dashboard", "rev-parse", "--short", "HEAD"],
            stderr=_subp_sys.DEVNULL, timeout=2,
        ).decode().strip()
    except Exception:
        sha = "unknown"
    try:
        branch = _subp_sys.check_output(
            ["git", "-C", "/home/l/rag-dashboard", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=_subp_sys.DEVNULL, timeout=2,
        ).decode().strip()
    except Exception:
        branch = "unknown"
    return {
        "git_sha": sha,
        "git_branch": branch,
        "python_version": _plat_sys.python_version(),
        "platform": _plat_sys.platform(),
        "service_start_ts": _SERVICE_START_TS,
    }


_SERVICE_START_TS = _time_ops.time()


@router.get("/api/v1/system/config")
async def system_config():
    """Currently effective LLM/embedding/retrieval config — env-aware."""
    return {
        "llm": {
            "provider": _os_learn.environ.get("LLM_PROVIDER", "deepseek"),
            "model": _os_learn.environ.get("LLM_MODEL", "deepseek-chat"),
            "route": _os_learn.environ.get("LLM_ROUTE", "deepseek"),
            "base_url": _os_learn.environ.get("LLM_BASE_URL", "https://api.deepseek.com"),
            "max_tokens": int(_os_learn.environ.get("LLM_MAX_TOKENS", "2048")),
            "temperature": float(_os_learn.environ.get("LLM_TEMPERATURE", "0.0")),
        },
        "embedding": {
            "model": _os_learn.environ.get("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5"),
            "backend": _os_learn.environ.get("EMBEDDING_BACKEND", "local"),
            "dim": int(_os_learn.environ.get("EMBEDDING_DIM", "1024")),
        },
        "retrieval": {
            "default_top_k": int(_os_learn.environ.get("DEFAULT_TOP_K", "8")),
            "score_threshold": float(_os_learn.environ.get("SCORE_THRESHOLD", "0.6")),
            "max_iterations": int(_os_learn.environ.get("MAX_ITERATIONS", "3")),
            "rrf_k": int(_os_learn.environ.get("RRF_K", "60")),
        },
        "stores": {
            "postgres": _os_learn.environ.get("POSTGRES_HOST", "localhost"),
            "qdrant": _os_learn.environ.get("QDRANT_HOST", "localhost"),
            "neo4j": _os_learn.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        },
    }


@router.get("/api/v1/system/kb")
async def system_kb():
    """Knowledge base statistics — document count, chunks, vector count, latest ingest."""
    from app.agent.tools import _get_pg_conn, _put_pg_conn
    out: dict = {}
    conn = None
    def _q(cur, sql, default=None):
        try:
            cur.execute(sql)
            r = cur.fetchone()
            return r[0] if r else default
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return default

    try:
        conn = _get_pg_conn()
        conn.autocommit = True
        with conn.cursor() as cur:
            out["chunks_total"] = _q(cur, "SELECT COUNT(*) FROM text_chunks")
            out["documents_total"] = _q(cur, "SELECT COUNT(*) FROM document_registry")
            if out["documents_total"] is None:
                out["documents_total"] = _q(cur, "SELECT COUNT(DISTINCT doc_id) FROM text_chunks")
            out["concepts_total"] = _q(cur, "SELECT COUNT(*) FROM canonical_concepts")
            if out["concepts_total"] is None:
                out["concepts_total"] = _q(cur, "SELECT COUNT(*) FROM catalog_index")
            out["relations_total"] = _q(cur, "SELECT COUNT(*) FROM concept_relations")
            if out["relations_total"] is None:
                out["relations_total"] = _q(cur, "SELECT COUNT(*) FROM trend_relations")
            out["price_records_total"] = _q(cur, "SELECT COUNT(*) FROM price_records")
            try:
                cur.execute("""
                    SELECT COALESCE(metadata->>'source','unknown') AS src, COUNT(*)
                    FROM text_chunks GROUP BY 1 ORDER BY 2 DESC LIMIT 10
                """)
                out["chunks_by_source"] = [{"source": r[0], "count": r[1]} for r in cur.fetchall()]
            except Exception:
                conn.rollback() if conn else None
                out["chunks_by_source"] = []
            try:
                cur.execute("SELECT MAX(created_at) FROM text_chunks")
                row = cur.fetchone()
                out["latest_chunk_ts"] = row[0].isoformat() if row and row[0] else None
            except Exception:
                conn.rollback() if conn else None
                out["latest_chunk_ts"] = None
    except Exception as e:
        out["error"] = str(e)
    finally:
        if conn:
            _put_pg_conn(conn)
    return out


# ── Prometheus /metrics ───────────────────────────────────────────────────────

try:
    from prometheus_client import (
        Counter as _PromCounter,
        Histogram as _PromHistogram,
        generate_latest as _prom_generate,
        CONTENT_TYPE_LATEST as _PROM_CT,
    )
    _PROM_AVAILABLE = True
except Exception:
    _PROM_AVAILABLE = False


if _PROM_AVAILABLE:
    RAG_TOOL_TOTAL = _PromCounter(
        "rag_tool_invocations_total", "Tool invocation count", ["tool", "status"]
    )
    RAG_TOOL_LATENCY = _PromHistogram(
        "rag_tool_latency_seconds", "Tool latency seconds", ["tool"],
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
    )
    RAG_AGENT_RUNS_TOTAL = _PromCounter(
        "rag_agent_runs_total", "Agent run count", ["quality"]
    )
    RAG_AGENT_LATENCY = _PromHistogram(
        "rag_agent_latency_seconds", "Agent end-to-end latency",
        buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
    )


def prom_record_tool(tool: str, status: str, latency_s: float) -> None:
    """Called from tool wrappers — no-op if prom unavailable."""
    if not _PROM_AVAILABLE:
        return
    try:
        RAG_TOOL_TOTAL.labels(tool=tool, status=status).inc()
        RAG_TOOL_LATENCY.labels(tool=tool).observe(max(0.0, latency_s))
    except Exception:
        pass


def prom_record_agent(quality: str, latency_s: float) -> None:
    if not _PROM_AVAILABLE:
        return
    try:
        RAG_AGENT_RUNS_TOTAL.labels(quality=quality or "unknown").inc()
        RAG_AGENT_LATENCY.observe(max(0.0, latency_s))
    except Exception:
        pass


@router.get("/metrics")
async def prom_metrics():
    """Prometheus scrape endpoint."""
    from fastapi.responses import Response
    if not _PROM_AVAILABLE:
        return Response("# prometheus_client unavailable\n", media_type="text/plain")
    return Response(_prom_generate(), media_type=_PROM_CT)


# ── Learning blind-spot clustering ────────────────────────────────────────────

@router.get("/api/v1/learning/blindspots")
async def learning_blindspots(min_size: int = 2, max_clusters: int = 8):
    """Cluster failed/weak agent queries to surface "topic-level" blind spots.

    Strategy: load failure/weak runs from agent_runs.jsonl, embed each query,
    cluster via simple cosine threshold linkage (no extra deps), return clusters
    with representative query + similar queries + chunk_count stats.
    """
    runs = _read_jsonl(_os_learn.path.join(_LEARN_DIR, "agent_runs.jsonl"), limit=1000)
    bad = [r for r in runs if r.get("quality") in ("failure", "weak") or r.get("refused")]
    seen_q: dict[str, dict] = {}
    for r in bad:
        q = (r.get("query") or "").strip()
        if not q:
            continue
        if q in seen_q:
            seen_q[q]["count"] += 1
        else:
            seen_q[q] = {
                "query": q,
                "count": 1,
                "quality": r.get("quality"),
                "refused": bool(r.get("refused")),
                "confidence": (r.get("evaluation") or {}).get("confidence", 0),
                "chunks_count": r.get("chunks_count", 0),
                "ts": r.get("ts"),
            }
    queries = list(seen_q.values())
    if len(queries) < min_size:
        return {"clusters": [], "total_bad": len(queries), "note": "not enough bad runs to cluster"}

    try:
        from app.agent.tools import _get_embedding_svc  # type: ignore
        emb_svc = _get_embedding_svc()
        vecs = [emb_svc.encode(q["query"]) for q in queries]
    except Exception as e:
        # fallback: token-jaccard similarity
        logger.warning(f"[blindspots] embedding unavailable: {e}; using jaccard fallback")
        vecs = None

    import math
    def cos(a, b):
        s = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        return s / (na * nb) if na and nb else 0.0

    def jaccard(a: str, b: str) -> float:
        sa, sb = set(a), set(b)
        u = sa | sb
        return len(sa & sb) / len(u) if u else 0.0

    clusters: list[list[int]] = []
    threshold = 0.78 if vecs else 0.45
    for i in range(len(queries)):
        placed = False
        for c in clusters:
            rep = c[0]
            sim = cos(vecs[i], vecs[rep]) if vecs else jaccard(queries[i]["query"], queries[rep]["query"])
            if sim >= threshold:
                c.append(i)
                placed = True
                break
        if not placed:
            clusters.append([i])

    clusters.sort(key=lambda c: -len(c))
    out = []
    for c in clusters[:max_clusters]:
        if len(c) < min_size:
            continue
        members = [queries[i] for i in c]
        members.sort(key=lambda m: -m["count"])
        rep = members[0]
        avg_chunks = sum(m["chunks_count"] for m in members) / len(members)
        avg_conf = sum(m["confidence"] for m in members) / len(members)
        out.append({
            "size": len(members),
            "representative": rep["query"],
            "queries": [m["query"] for m in members[:8]],
            "refused_count": sum(1 for m in members if m["refused"]),
            "avg_chunks": round(avg_chunks, 1),
            "avg_confidence": round(avg_conf, 3),
            "diagnosis": _diagnose_blindspot(members, avg_chunks, avg_conf),
        })
    return {
        "clusters": out,
        "total_bad": len(queries),
        "method": "embedding-cosine" if vecs else "jaccard-fallback",
        "threshold": threshold,
    }


def _diagnose_blindspot(members: list[dict], avg_chunks: float, avg_conf: float) -> str:
    """Return a short heuristic explanation of likely root cause."""
    refuse_n = sum(1 for m in members if m["refused"])
    if refuse_n / len(members) >= 0.7:
        return "高频拒绝回答 — 知识库可能完全缺失该主题资料，建议补充文档"
    if avg_chunks < 2:
        return "检索命中过少 — 检索召回不足，建议丰富同义词/扩展chunk metadata"
    if avg_conf < 0.4:
        return "命中但答非所问 — chunk 与问题语义错位，建议优化 chunk 切分或父节摘要"
    return "答案质量弱 — 综合表现偏低，需进一步分析"


# ── Agent traces (#67) ────────────────────────────────────────────────────────

@router.get("/api/v1/agent/traces")
async def list_agent_traces(limit: int = 50):
    from app.agent.trace import list_traces
    return {"traces": list_traces(limit=max(1, min(200, int(limit))))}


@router.get("/api/v1/agent/trace/{trace_id}")
async def get_agent_trace(trace_id: str):
    from app.agent.trace import get_trace
    t = get_trace(trace_id)
    if not t:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="trace not found")
    return t


# ── OCR pipeline (#63) ────────────────────────────────────────────────────────

import asyncio as _pl_asyncio
import shutil as _pl_shutil
import uuid as _pl_uuid
from pathlib import Path as _PlPath

_PIPELINE_DIR = _PlPath(os.environ.get("RAG_PIPELINE_JOBS_DIR",
                                        "/home/l/rag-dashboard/data/pipeline_jobs"))
_PIPELINE_DIR.mkdir(parents=True, exist_ok=True)
_UPLOAD_DIR = _PlPath(os.environ.get("RAG_PIPELINE_UPLOAD_DIR",
                                      "/home/l/rag-dashboard/data/uploads"))
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _pl_write(job_id: str, payload: dict) -> None:
    try:
        (_PIPELINE_DIR / f"{job_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, default=str)
        )
    except Exception as e:
        logger.warning(f"[pipeline] write {job_id}: {e}")


def _pl_read(job_id: str) -> dict | None:
    fp = _PIPELINE_DIR / f"{job_id}.json"
    if not fp.exists():
        return None
    try:
        return json.loads(fp.read_text())
    except Exception:
        return None


def _pl_update(job_id: str, **patch) -> None:
    cur = _pl_read(job_id) or {}
    cur.update(patch)
    cur["updated_ts"] = time.time()
    _pl_write(job_id, cur)


async def _run_pipeline_job(job_id: str, file_path: str, file_name: str) -> None:
    """Background pipeline: OCR → chunk → embed → ingest. Best-effort, robust."""
    import httpx as _httpx
    started = time.time()
    _pl_update(job_id, status="ocr", stage_started_ts=started, file_path=file_path)
    text = ""
    ocr_pages = 0
    suffix = file_path.lower()

    # Stage 1: OCR (only for image/pdf). For .txt/.md just read.
    try:
        if suffix.endswith((".txt", ".md")):
            text = _PlPath(file_path).read_text(encoding="utf-8", errors="ignore")
        elif suffix.endswith((".pdf", ".png", ".jpg", ".jpeg")):
            ocr_url = os.environ.get("OCR_SERVICE_URL", "http://localhost:8001")
            endpoint = "/ocr/pdf" if suffix.endswith(".pdf") else "/ocr/image"
            try:
                async with _httpx.AsyncClient(timeout=180.0) as client:
                    with open(file_path, "rb") as fh:
                        r = await client.post(
                            f"{ocr_url}{endpoint}",
                            files={"file": (file_name, fh)},
                        )
                if r.status_code == 200:
                    data = r.json()
                    pages = data.get("pages") or []
                    text_parts = []
                    for p in pages:
                        t = p.get("text") or p.get("ocr_text") or ""
                        if t:
                            text_parts.append(t)
                    text = "\n\n".join(text_parts)
                    ocr_pages = len(pages)
                else:
                    _pl_update(job_id, ocr_warning=f"OCR returned {r.status_code}: {r.text[:200]}")
            except Exception as oe:
                _pl_update(job_id, ocr_warning=f"OCR call failed: {oe}", ocr_unavailable=True)
                # Fallback: skip OCR, treat as empty if PDF; for unsupported formats abort
                text = ""
        else:
            _pl_update(job_id, status="failed", error=f"unsupported extension: {suffix}")
            return
    except Exception as e:
        _pl_update(job_id, status="failed", error=f"ocr stage failed: {e}")
        return

    if not text.strip():
        _pl_update(
            job_id,
            status="failed",
            error="no extractable text (OCR unavailable or empty document)",
            ocr_pages=ocr_pages,
        )
        return

    _pl_update(job_id, status="ingest", text_chars=len(text), ocr_pages=ocr_pages)

    # Stage 2: ingest into PG + Qdrant. Use existing rag_pipeline if available.
    try:
        from app.agent.tools import _get_pg_conn, _put_pg_conn, _get_embedding_svc
        chunks = _split_text_for_pipeline(text, max_chars=400)
        emb = _get_embedding_svc()
        conn = _get_pg_conn()
        try:
            conn.autocommit = False
            with conn.cursor() as cur:
                # ensure document_registry row exists
                doc_id = job_id
                try:
                    cur.execute(
                        """
                        INSERT INTO document_registry (doc_id, file_name, total_chunks, ingested_at)
                        VALUES (%s, %s, %s, NOW())
                        ON CONFLICT (doc_id) DO UPDATE SET total_chunks = EXCLUDED.total_chunks
                        """,
                        (doc_id, file_name, len(chunks)),
                    )
                except Exception:
                    conn.rollback()

                inserted = 0
                for i, chunk in enumerate(chunks):
                    try:
                        vec = emb.encode(chunk)
                        try:
                            vec_list = vec.tolist() if hasattr(vec, "tolist") else list(vec)
                        except Exception:
                            vec_list = list(vec)
                        cur.execute(
                            """
                            INSERT INTO text_chunks (doc_id, file_name, chunk_index, content,
                                                     section, metadata, embedding, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, NOW())
                            """,
                            (doc_id, file_name, i, chunk, "",
                             json.dumps({"source": "pipeline_upload", "job_id": job_id}),
                             vec_list),
                        )
                        inserted += 1
                    except Exception as ce:
                        conn.rollback()
                        logger.warning(f"[pipeline {job_id}] chunk {i} insert failed: {ce}")
                conn.commit()
        finally:
            _put_pg_conn(conn)

        _pl_update(
            job_id,
            status="done",
            chunks_total=len(chunks),
            chunks_inserted=inserted,
            doc_id=doc_id,
            duration_ms=int((time.time() - started) * 1000),
        )
    except Exception as e:
        _pl_update(job_id, status="failed", error=f"ingest failed: {e}",
                   duration_ms=int((time.time() - started) * 1000))


def _split_text_for_pipeline(text: str, max_chars: int = 400) -> list[str]:
    """Naive paragraph-aware splitter (no external deps)."""
    paragraphs = [p.strip() for p in text.replace("\r", "").split("\n\n") if p.strip()]
    out: list[str] = []
    buf = ""
    for p in paragraphs:
        if not buf:
            buf = p
        elif len(buf) + len(p) + 2 <= max_chars:
            buf = buf + "\n\n" + p
        else:
            out.append(buf)
            if len(p) <= max_chars:
                buf = p
            else:
                # hard split long paragraph
                for k in range(0, len(p), max_chars):
                    out.append(p[k:k + max_chars])
                buf = ""
    if buf:
        out.append(buf)
    return out


@router.post("/api/v1/pipeline/upload")
async def pipeline_upload(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    """Accept a file (pdf/image/txt/md), create PG-backed ingest job, run async."""
    from app import ingest_pipeline as ipl

    fname = file.filename or "upload.bin"
    safe_name = "".join(c for c in fname if c.isalnum() or c in "._-")[:120] or "upload.bin"
    suffix = _PlPath(safe_name).suffix.lower()
    mime_map = {".pdf": "application/pdf", ".png": "image/png",
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".txt": "text/plain", ".md": "text/markdown",
                ".csv": "text/csv",
                ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12"}
    mime = mime_map.get(suffix, "application/octet-stream")

    # generate job_id first so the saved file name is unique
    tmp_id = _pl_uuid.uuid4().hex[:16]
    dest = _UPLOAD_DIR / f"{tmp_id}_{safe_name}"
    try:
        with open(dest, "wb") as fh:
            _pl_shutil.copyfileobj(file.file, fh)
    except Exception as e:
        return {"ok": False, "error": f"save failed: {e}"}

    size = dest.stat().st_size if dest.exists() else 0
    # create job in PG (gets its own job_id)
    job_id = ipl.job_create(file_name=fname, file_path=str(dest),
                            file_size=size, mime=mime)

    # rename file so it carries the real job_id (cosmetic, not required)
    final = _UPLOAD_DIR / f"{job_id}_{safe_name}"
    try:
        dest.rename(final)
        ipl.job_update(job_id, file_path=str(final))
    except Exception:
        pass

    if background_tasks is None:
        _pl_asyncio.create_task(ipl.run_ingest_job(job_id))
    else:
        background_tasks.add_task(ipl.run_ingest_job, job_id)

    return {"ok": True, "job_id": job_id, "file_name": fname,
            "size": size, "status": "queued", "mime": mime}


@router.get("/api/v1/pipeline/jobs")
async def list_pipeline_jobs(limit: int = 50, status: str | None = None):
    from app import ingest_pipeline as ipl
    jobs = ipl.job_list(limit=max(1, min(200, int(limit))), status=status)
    # serialize datetimes
    for j in jobs:
        for k in ("created_at", "updated_at", "started_at", "finished_at"):
            if j.get(k) is not None:
                j[k] = str(j[k])
    return {"jobs": jobs}


@router.get("/api/v1/pipeline/job/{job_id}")
async def get_pipeline_job(job_id: str):
    from app import ingest_pipeline as ipl
    j = ipl.job_get(job_id)
    if not j:
        raise HTTPException(status_code=404, detail="job not found")
    for k in ("created_at", "updated_at", "started_at", "finished_at"):
        if j.get(k) is not None:
            j[k] = str(j[k])
    # attach blindspots so the dashboard can flag pages the extractor skipped
    j["blindspots"] = ipl.blindspots_for_job(job_id)
    return j


@router.get("/api/v1/pipeline/blindspots")
async def list_blindspots(doc_id: str | None = None, limit: int = 100):
    """List image/chart pages where extraction had insufficient text.

    The agent uses this to honestly disclose data gaps instead of confabulating
    chart values it cannot read.
    """
    from app import ingest_pipeline as ipl
    rows = ipl.blindspots_list(doc_id=doc_id, limit=max(1, min(500, int(limit))))
    return {"blindspots": rows, "count": len(rows)}


@router.post("/api/v1/pipeline/retry/{job_id}")
async def retry_pipeline_job(job_id: str, background_tasks: BackgroundTasks = None):
    """Re-run a failed/done job; idempotent via ingest_write_log."""
    from app import ingest_pipeline as ipl
    j = ipl.job_get(job_id)
    if not j:
        raise HTTPException(status_code=404, detail="job not found")
    ipl.job_update(job_id, status="queued", phase="queued",
                   progress_pct=0, error=None)
    if background_tasks is None:
        _pl_asyncio.create_task(ipl.run_ingest_job(job_id))
    else:
        background_tasks.add_task(ipl.run_ingest_job, job_id)
    return {"ok": True, "job_id": job_id, "status": "queued"}


@router.get("/api/v1/pipeline/health")
async def pipeline_health():
    """Probe upstream services so the ops dashboard tells the truth."""
    import httpx
    from app.agent.tools import _get_pg_conn, _put_pg_conn
    health: dict = {"ok": True, "components": {}}

    # bypass any SOCKS proxy for localhost probes
    transport = httpx.AsyncHTTPTransport(proxy=None)

    # PG
    try:
        c = _get_pg_conn()
        try:
            with c.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM ingest_jobs")
                cur.fetchone()
            health["components"]["postgres"] = {"ok": True}
        finally:
            _put_pg_conn(c)
    except Exception as e:
        health["components"]["postgres"] = {"ok": False, "error": str(e)[:200]}
        health["ok"] = False

    async def probe(name: str, url: str, optional: bool = False):
        try:
            async with httpx.AsyncClient(timeout=3.0, transport=transport) as client:
                r = await client.get(url)
                ok = r.status_code in (200, 401)  # 401 = neo4j auth-protected but alive
                health["components"][name] = {"ok": ok, "status_code": r.status_code}
                if not ok and not optional:
                    health["ok"] = False
        except Exception as e:
            health["components"][name] = {"ok": False, "error": str(e)[:200]}
            if optional:
                health["components"][name]["note"] = "optional"
            else:
                health["ok"] = False

    await probe("qdrant", os.environ.get("QDRANT_URL", "http://localhost:6333") + "/collections")
    await probe("ocr",    os.environ.get("OCR_SERVICE_URL", "http://localhost:8001") + "/health",
                optional=True)
    await probe("neo4j",  os.environ.get("NEO4J_HTTP_URL", "http://localhost:7474"),
                optional=True)

    return health
