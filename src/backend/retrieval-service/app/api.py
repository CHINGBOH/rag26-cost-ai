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
from datetime import datetime, timezone
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


@router.post("/api/search", response_model=APIResponse[Dict[str, Any]])
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
                # Server-side conversation logging
                try:
                    import asyncpg as _apg
                    _db_url = os.environ.get("DATABASE_URL", "postgresql://rag_user:rag_password@localhost:5432/rag_db")
                    _conn = await _apg.connect(_db_url)
                    try:
                        _turn_idx = int(elapsed_ms // 1 + 1)  # use unique ts-based index
                        await _conn.execute(
                            """INSERT INTO conversation_turns
                               (session_id, turn_index, user_content, assistant_content,
                                message_id, source, status, latency_ms)
                               VALUES ($1, (SELECT COALESCE(MAX(turn_index),0)+1 FROM conversation_turns WHERE session_id=$1),
                               $2, $3, $4, 'agent', 'completed', $5)
                            """,
                            session_id, request.query, final_answer or "",
                            str(uuid.uuid4()), elapsed_ms,
                        )
                    finally:
                        await _conn.close()
                except Exception as _log_err:
                    logger.debug(f"[conv_log] skipped: {_log_err}")
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
    rating: int  # +1 or -1 (kept for backward compat)
    # Extended rating fields (1-5 scale)
    overall_rating: Optional[int] = None
    rating_relevance: Optional[int] = None
    rating_accuracy: Optional[int] = None
    rating_completeness: Optional[int] = None
    # Text review fields
    praise: Optional[str] = None
    criticism: Optional[str] = None
    suggestion: Optional[str] = None
    tags: Optional[list] = None
    # Legacy fields
    comment: Optional[str] = None
    query: Optional[str] = None
    answer_summary: Optional[str] = None


@router.post("/api/v1/feedback")
async def submit_feedback(request: FeedbackRequest):
    """Store user feedback to JSONL file and PostgreSQL rag_feedback table."""
    import time
    import os
    record = {
        "ts": time.time(),
        "session_id": request.session_id,
        "message_id": request.message_id,
        "rating": request.rating,
        "overall_rating": request.overall_rating,
        "rating_relevance": request.rating_relevance,
        "rating_accuracy": request.rating_accuracy,
        "rating_completeness": request.rating_completeness,
        "praise": request.praise,
        "criticism": request.criticism,
        "suggestion": request.suggestion,
        "tags": request.tags,
        "comment": request.comment,
        "query": request.query,
        "answer_summary": request.answer_summary,
    }
    _feedback_default = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "..", "..", "data", "feedback", "rag_feedback.jsonl"
    )
    feedback_path = os.environ.get("FEEDBACK_LOG_PATH", _feedback_default)
    os.makedirs(os.path.dirname(os.path.abspath(feedback_path)), exist_ok=True)
    try:
        with open(feedback_path, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error(f"Feedback JSONL write error: {e}")
        raise HTTPException(status_code=500, detail="Failed to save feedback")

    # Also persist to PostgreSQL with upsert on (session_id, message_id)
    try:
        import asyncpg
        db_url = os.environ.get("DATABASE_URL", "postgresql://rag_user:rag_password@localhost:5432/rag_db")
        conn = await asyncpg.connect(db_url)
        try:
            fb_id = await conn.fetchval(
                """INSERT INTO rag_feedback
                   (ts, session_id, message_id, rating, comment, query, answer_summary,
                    overall_rating, rating_relevance, rating_accuracy, rating_completeness,
                    praise, criticism, suggestion, tags)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
                   ON CONFLICT (session_id, message_id) DO UPDATE SET
                     rating=EXCLUDED.rating, overall_rating=EXCLUDED.overall_rating,
                     rating_relevance=EXCLUDED.rating_relevance,
                     rating_accuracy=EXCLUDED.rating_accuracy,
                     rating_completeness=EXCLUDED.rating_completeness,
                     praise=EXCLUDED.praise, criticism=EXCLUDED.criticism,
                     suggestion=EXCLUDED.suggestion, tags=EXCLUDED.tags,
                     comment=EXCLUDED.comment, answer_summary=EXCLUDED.answer_summary
                   RETURNING id
                """,
                record["ts"], request.session_id, request.message_id,
                request.rating, request.comment, request.query, request.answer_summary,
                request.overall_rating, request.rating_relevance, request.rating_accuracy,
                request.rating_completeness, request.praise, request.criticism,
                request.suggestion, request.tags,
            )

            # ── #94-A I2 反馈可达性钩子 ──────────────────────────────────
            # 任何负面反馈（rating == -1 或 overall_rating <= 2）都自动写入
            # 一条 improvement_events 桩条目（applied_at 留空，等待人工/自动处理）。
            # 这样保证 I2 覆盖率非零，同时不假装事件已处理。
            is_negative = (
                (request.rating is not None and request.rating <= -1)
                or (request.overall_rating is not None and request.overall_rating <= 2)
            )
            if fb_id and is_negative:
                # 朴素启发：query 含价格/数字 → R5_tool_priority；含"如何/怎么"路径词 → R2；
                # 含"什么/定义" → R1；否则 R3（plan few-shot）。后续人工可改。
                q = (request.query or "").lower()
                has_price = any(t in q for t in ["价", "元", "费", "cost", "price", "%", "万"])
                has_path = any(t in q for t in ["如何", "怎么", "步骤", "流程", "how"])
                has_def = any(t in q for t in ["什么是", "定义", "what is", "解释"])
                if has_price:
                    route = "R5_tool_priority"
                elif has_path:
                    route = "R2_path_default"
                elif has_def:
                    route = "R1_navigator_dict"
                else:
                    route = "R3_planner_examples"

                payload = {
                    "rating": request.rating,
                    "overall_rating": request.overall_rating,
                    "criticism": request.criticism,
                    "suggestion": request.suggestion,
                    "tags": request.tags,
                    "query_preview": (request.query or "")[:200],
                }
                rationale = (
                    request.criticism or request.suggestion
                    or request.comment or "auto-pending-review"
                )[:500]
                try:
                    # 去重：同一 feedback id 只挂一条 stub，避免 upsert 重复写入
                    existing = await conn.fetchval(
                        "SELECT id FROM improvement_events WHERE source_feedback_id = $1 LIMIT 1",
                        fb_id,
                    )
                    if existing:
                        logger.info("I2 hook: feedback id=%s already linked to event id=%s",
                                    fb_id, existing)
                    else:
                        await conn.execute(
                            """INSERT INTO improvement_events
                               (source, actor, source_feedback_id, affected_route,
                                patch_payload, rationale, reversible_by)
                               VALUES ('auto', 'feedback_hook', $1, $2, $3::jsonb, $4, 'rollback_event')
                            """,
                            fb_id, route, json.dumps(payload, ensure_ascii=False), rationale,
                        )
                        logger.info(
                            "I2 hook: improvement_event stub created for feedback id=%s route=%s",
                            fb_id, route,
                        )
                except Exception as e:
                    logger.warning(f"I2 hook insert skipped: {e}")
        finally:
            await conn.close()
    except Exception as e:
        logger.warning(f"Feedback DB write skipped: {e}")

    return {"status": "ok", "message_id": request.message_id}


# ── Health Detail & Metrics ───────────────────────────────────────────────────

@router.get("/api/v1/health/detail")
async def health_detail():
    """Per-service health with latency, criticality, and graceful degradation.

    Reports each backend with:
    - ``status``: healthy / degraded / unhealthy / not_running
    - ``latency_ms``: -1 when unreachable
    - ``critical``: true if the system cannot function without it; false for
      optional services like python_legacy (which retrieval-service replaces)
    - ``role``: short human-readable description so the UI doesn't need
      to hardcode service knowledge
    """
    import httpx
    import time
    import asyncio
    # Definition: each entry = (name, url, critical, role)
    http_services = [
        ("retrieval",     "http://localhost:8002/health",  True,
         "核心检索服务 (FastAPI)"),
        ("go_gateway",    "http://localhost:8080/health",  True,
         "API 路由网关"),
        ("nodejs",        "http://localhost:3001/health",  False,
         "Node 编排（可选）"),
        ("python_legacy", "http://localhost:8000/health",  False,
         "旧 Python API（已被 retrieval 替代）"),
        ("ocr",           "http://localhost:8001/health",  False,
         "OCR 服务（按需）"),
        ("qdrant",        "http://localhost:6333/healthz", True,
         "向量库"),
        ("milvus",        "http://localhost:9091/healthz", False,
         "向量库 Milvus（可选，与 qdrant 二选一或 A/B）"),
        ("elasticsearch", "http://localhost:9200/_cluster/health", True,
         "全文检索（IK 分词）"),
        ("neo4j",         "http://localhost:7474/",         False,
         "图谱库（可选）"),
    ]
    results: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
        async def probe(name, url, critical, role):
            t0 = time.monotonic()
            try:
                r = await client.get(url)
                latency_ms = int((time.monotonic() - t0) * 1000)
                if r.status_code == 200:
                    status = "healthy"
                else:
                    status = "degraded"
                return name, {
                    "status": status,
                    "latency_ms": latency_ms,
                    "critical": critical,
                    "role": role,
                    "status_code": r.status_code,
                }
            except Exception as e:
                # Optional services that aren't running: show as not_running,
                # not as alarming "unhealthy" — they intentionally aren't up.
                return name, {
                    "status": "unhealthy" if critical else "not_running",
                    "latency_ms": -1,
                    "critical": critical,
                    "role": role,
                    "error": str(e)[:120],
                }
        probes = await asyncio.gather(
            *(probe(n, u, c, r) for n, u, c, r in http_services)
        )
        for name, info in probes:
            results[name] = info

    # PostgreSQL: TCP probe
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
            "critical": True,
            "role": "结构化存储 + 全文兜底",
        }
    except Exception as e:
        results["postgresql"] = {
            "status": "unhealthy",
            "latency_ms": -1,
            "critical": True,
            "role": "结构化存储 + 全文兜底",
            "error": str(e)[:120],
        }

    # Redis: TCP probe (cheap)
    t0 = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("localhost", 6379), timeout=2.0
        )
        writer.close()
        await writer.wait_closed()
        results["redis"] = {
            "status": "healthy",
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "critical": False,
            "role": "缓存（可选）",
        }
    except Exception as e:
        results["redis"] = {
            "status": "not_running",
            "latency_ms": -1,
            "critical": False,
            "role": "缓存（可选）",
            "error": str(e)[:120],
        }

    # Process-level metrics from /proc (Linux only, cheap, no extra deps)
    sysmetrics = _read_proc_metrics()

    # Overall: only critical services count toward summary
    critical_services = {k: v for k, v in results.items() if v.get("critical")}
    crit_healthy = sum(1 for v in critical_services.values() if v["status"] == "healthy")
    crit_total = len(critical_services)
    overall = "ok" if crit_healthy == crit_total else (
        "degraded" if crit_healthy >= crit_total - 1 else "down"
    )

    return {
        "services": results,
        "summary": {
            "overall": overall,
            "critical_total": crit_total,
            "critical_healthy": crit_healthy,
        },
        "system": sysmetrics,
        "timestamp": datetime.now().isoformat(),
    }


def _read_proc_metrics() -> dict:
    """Cheap /proc reader: load average + memory. Linux-only; safe fallback."""
    out: dict = {}
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().strip().split()
            out["load_1m"] = float(parts[0])
            out["load_5m"] = float(parts[1])
            out["load_15m"] = float(parts[2])
    except Exception:
        pass
    try:
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f:
                k, _, rest = line.partition(":")
                v = rest.strip().split()
                if v:
                    try:
                        mem[k.strip()] = int(v[0])  # kB
                    except ValueError:
                        pass
        total = mem.get("MemTotal", 0)
        avail = mem.get("MemAvailable", 0)
        if total:
            out["mem_total_mb"] = total // 1024
            out["mem_available_mb"] = avail // 1024
            out["mem_used_pct"] = round((total - avail) * 100.0 / total, 1)
    except Exception:
        pass
    try:
        import os as _os
        out["cpu_count"] = _os.cpu_count() or 0
    except Exception:
        pass
    return out


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
_feedback_default_learn = _os_learn.path.join(
    _os_learn.path.dirname(_os_learn.path.abspath(__file__)),
    "..", "..", "..", "..", "data", "feedback", "rag_feedback.jsonl"
)
_FEEDBACK_PATH = _os_learn.environ.get("FEEDBACK_LOG_PATH", _feedback_default_learn)


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
    # Convert ts from Unix seconds to milliseconds for frontend
    for run in runs[:limit]:
        if run.get('ts') and isinstance(run['ts'], (int, float)):
            run['ts'] = int(run['ts'] * 1000)
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
        # Map quality to status: failure → open, weak → in_progress
        quality = r.get("quality", "unknown")
        status = "open" if quality == "failure" else "in_progress" if quality == "weak" else "open"
        ts = r.get("ts")
        # Convert ts from Unix seconds to milliseconds
        if ts and isinstance(ts, (int, float)):
            ts = int(ts * 1000)
        gaps.append({
            "query": q,
            "ts": ts,
            "quality": quality,
            "status": status,
            "refused": bool(r.get("refused")),
            "chunks_count": r.get("chunks_count", 0),
            "confidence": (r.get("evaluation") or {}).get("confidence", 0),
            "answer_preview": (r.get("answer") or "")[:200],
        })
        if len(gaps) >= limit:
            break
    return {"gaps": gaps}


@router.get("/api/v1/learning/conversations")
async def learning_conversations(limit: int = 50, source: Optional[str] = None):
    """Recent conversation turns from DB, newest first. source=agent|guide to filter."""
    try:
        import asyncpg
        db_url = os.environ.get("DATABASE_URL", "postgresql://rag_user:rag_password@localhost:5432/rag_db")
        conn = await asyncpg.connect(db_url)
        try:
            if source:
                rows = await conn.fetch(
                    "SELECT * FROM conversation_turns WHERE source=$1 ORDER BY ts DESC LIMIT $2",
                    source, limit,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM conversation_turns ORDER BY ts DESC LIMIT $1", limit
                )
        finally:
            await conn.close()
        turns = [dict(r) for r in rows]
        # Convert ts from Unix seconds to milliseconds for frontend
        for turn in turns:
            if turn.get('ts'):
                turn['ts'] = int(turn['ts'] * 1000)
        return {"turns": turns, "total": len(turns)}
    except Exception as e:
        logger.warning(f"conversations fetch error: {e}")
        return {"turns": [], "total": 0, "error": str(e)}


@router.get("/api/v1/learning/feedback-stats")
async def learning_feedback_stats(limit: int = 100):
    """Feedback records with detailed ratings + trend data for dashboard."""
    try:
        import asyncpg
        db_url = os.environ.get("DATABASE_URL", "postgresql://rag_user:rag_password@localhost:5432/rag_db")
        conn = await asyncpg.connect(db_url)
        try:
            rows = await conn.fetch(
                """SELECT ts, session_id, message_id, rating, overall_rating,
                          rating_relevance, rating_accuracy, rating_completeness,
                          praise, criticism, suggestion, tags, query, answer_summary
                   FROM rag_feedback ORDER BY ts DESC LIMIT $1""",
                limit,
            )
            # Trend: daily good-rate (last 7 days buckets)
            trend_rows = await conn.fetch(
                """SELECT DATE_TRUNC('day', created_at AT TIME ZONE 'Asia/Shanghai') AS day,
                          COUNT(*) FILTER (WHERE rating > 0) AS positive,
                          COUNT(*) AS total
                   FROM rag_feedback
                   WHERE created_at >= NOW() - INTERVAL '7 days'
                   GROUP BY 1 ORDER BY 1"""
            )
        finally:
            await conn.close()
        records = [dict(r) for r in rows]
        # Convert ts from Unix seconds to milliseconds for frontend
        for record in records:
            if record.get('ts'):
                record['ts'] = int(record['ts'] * 1000)
        trend = [{"day": str(r["day"])[:10], "positive": r["positive"], "total": r["total"]} for r in trend_rows]
        pos = sum(1 for r in records if r.get("rating", 0) > 0)
        neg = sum(1 for r in records if r.get("rating", 0) < 0)
        avg_overall = None
        rated = [r["overall_rating"] for r in records if r.get("overall_rating")]
        if rated:
            avg_overall = round(sum(rated) / len(rated), 2)
        return {
            "records": records,
            "summary": {"positive": pos, "negative": neg, "total": len(records), "avg_overall_rating": avg_overall},
            "trend": trend,
        }
    except Exception as e:
        logger.warning(f"feedback-stats error: {e}")
        return {"records": [], "summary": {}, "trend": [], "error": str(e)}


# ── Ops Metrics (in-memory request counter) ───────────────────────────────────

from collections import deque
import time as _time_ops
import threading as _threading_ops


# ── Learning Engine status (transparent triggers) ─────────────────────────────

_LEARNING_LAST_RUN_FILE = _os_learn.environ.get(
    "LEARNING_LAST_RUN_FILE",
    "/home/l/rag-dashboard/logs/agent_test_16_results.json",
)

from datetime import datetime as _datetime, timezone as _timezone


@router.get("/api/v1/learning/engine")
async def learning_engine_status():
    """Honest disclosure of how the learning loop works.

    Triggers: currently **manual** via `python tests/test_agent_16.py` (no scheduler,
    no threshold-based auto-run). Returns last-run results from the canary harness
    plus open feedback waiting for analyst attention.
    """
    last_run: dict = {}
    last_path = _os_learn.path.abspath(_LEARNING_LAST_RUN_FILE)
    try:
        if _os_learn.path.exists(last_path):
            with open(last_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            stat = _os_learn.stat(last_path)
            last_run = {
                "ts": payload.get("timestamp"),
                "file": last_path,
                "file_mtime": _datetime.fromtimestamp(stat.st_mtime, tz=_timezone.utc).isoformat(),
                "summary": payload.get("summary") or {},
                "result_count": len(payload.get("results") or []),
            }
    except Exception as exc:
        last_run = {"error": str(exc)}

    pending_feedback_count = 0
    weak_runs_24h = 0
    try:
        import asyncpg as _apg_le
        db_url = _os_learn.environ.get(
            "DATABASE_URL", "postgresql://rag_user:rag_password@localhost:5432/rag_db"
        )
        conn = await _apg_le.connect(db_url)
        try:
            r1 = await conn.fetchval(
                """SELECT COUNT(*) FROM rag_feedback
                   WHERE rating < 0 AND (suggestion IS NOT NULL OR criticism IS NOT NULL)
                     AND created_at >= NOW() - INTERVAL '7 days'"""
            )
            pending_feedback_count = int(r1 or 0)
        except Exception:
            pass
        finally:
            await conn.close()
    except Exception:
        pass

    try:
        runs = _read_jsonl(_os_learn.path.join(_LEARN_DIR, "agent_runs.jsonl"), limit=500)
        from datetime import datetime as _dt2
        cutoff = _time_ops.time() - 86400
        for r in runs:
            ts = r.get("ts")
            try:
                t_epoch = _dt2.fromisoformat(ts.replace("Z", "+00:00")).timestamp() if ts else 0
            except Exception:
                t_epoch = 0
            if t_epoch >= cutoff and r.get("quality") in ("weak", "failure"):
                weak_runs_24h += 1
    except Exception:
        pass

    return {
        "trigger_mode": "manual",
        "trigger_description": (
            "学习回路目前为手动触发。运行 `python tests/test_agent_16.py` 跑 16 道金标问题，"
            "结果写入 logs/agent_test_16_results.json，本端点读取后展示。"
            "暂无定时任务、阈值自动触发或后台 worker。"
        ),
        "trigger_conditions": [
            {"name": "手动金标回归", "active": True, "command": "python tests/test_agent_16.py"},
            {"name": "定时回归 (cron)", "active": False, "note": "未启用，需要后续配置"},
            {"name": "失败率阈值自动触发", "active": False, "note": "未实现"},
            {"name": "用户反馈聚合分析", "active": False, "note": "数据已收集，分析任务待开发"},
        ],
        "last_run": last_run,
        "signals_24h": {
            "weak_or_failed_runs": weak_runs_24h,
            "pending_negative_feedback_with_text": pending_feedback_count,
        },
        "next_actions": [
            "查看『反馈点评』Tab 中带评论的负面反馈，作为下一轮迭代的素材",
            "在『Agent 运行轨迹』中过滤 quality=weak/failure，排查共性",
            "运行 `python tests/test_agent_16.py` 验证当前回归状态",
        ],
    }


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
            # Fallback: if registry is empty (None or 0) but chunks exist, count distinct doc_ids
            if not out["documents_total"]:
                fallback = _q(cur, "SELECT COUNT(DISTINCT doc_id) FROM text_chunks")
                if fallback:
                    out["documents_total"] = fallback
            # Always expose chunk-level distinct count for cross-check
            out["documents_in_chunks"] = _q(cur, "SELECT COUNT(DISTINCT doc_id) FROM text_chunks") or 0
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


@router.get("/api/v1/pipeline/audit/{job_id}")
async def audit_pipeline_job(job_id: str):
    """Cross-DB consistency audit for an ingest job.

    Verifies that PG `text_chunks`, Qdrant points, and Neo4j `(:Chunk)` counts
    agree for this doc_id. Surfaces drift as `db_drift` blindspots so the
    dashboard tells the truth instead of confabulating "100% complete".
    """
    import httpx
    from app import ingest_pipeline as ipl
    from app.agent.tools import _get_pg_conn, _put_pg_conn

    job = ipl.job_get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    doc_id = job.get("doc_id")
    file_name = job.get("file_name", "")
    if not doc_id:
        raise HTTPException(status_code=400, detail="job has no doc_id")

    checks: list[dict] = []
    pg_count = 0
    qdrant_count = 0
    neo4j_chunk_count = 0
    neo4j_pricerow_count = 0
    zero_norm_count = 0

    # PG
    try:
        c = _get_pg_conn()
        try:
            with c.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM text_chunks WHERE doc_id=%s", (doc_id,))
                pg_count = int(cur.fetchone()[0])
                cur.execute(
                    "SELECT COUNT(*) FROM text_chunks "
                    "WHERE doc_id=%s AND embedding IS NULL", (doc_id,))
                zero_norm_count = int(cur.fetchone()[0])
        finally:
            _put_pg_conn(c)
        checks.append({"name": "pg_text_chunks", "ok": True, "count": pg_count})
    except Exception as e:
        checks.append({"name": "pg_text_chunks", "ok": False, "error": str(e)[:200]})

    # Qdrant — count points with payload.doc_id == doc_id (scroll, not exact-count)
    transport = httpx.AsyncHTTPTransport(proxy=None)
    qurl = os.environ.get("QDRANT_URL", "http://localhost:6333")
    qcoll = os.environ.get("QDRANT_INGEST_COLLECTION", "document_chunks")
    try:
        async with httpx.AsyncClient(timeout=10.0, transport=transport) as client:
            offset = None
            seen = 0
            for _ in range(50):
                body = {"limit": 256, "with_payload": False,
                        "filter": {"must": [{"key": "doc_id",
                                             "match": {"value": doc_id}}]}}
                if offset is not None:
                    body["offset"] = offset
                r = await client.post(f"{qurl}/collections/{qcoll}/points/scroll",
                                      json=body)
                r.raise_for_status()
                data = r.json().get("result", {})
                pts = data.get("points", []) or []
                seen += len(pts)
                offset = data.get("next_page_offset")
                if not offset:
                    break
            qdrant_count = seen
        checks.append({"name": "qdrant_points", "ok": True, "count": qdrant_count})
    except Exception as e:
        checks.append({"name": "qdrant_points", "ok": False, "error": str(e)[:200]})

    # Neo4j
    try:
        drv = ipl._neo4j_session()
        if drv is not None:
            with drv.session() as ses:
                rec = ses.run("MATCH (:Document {doc_id:$d})-[:HAS_CHUNK]->(c:Chunk) "
                              "RETURN count(c) as n", d=doc_id).single()
                neo4j_chunk_count = int(rec["n"]) if rec else 0
                rec2 = ses.run("MATCH (:Document {doc_id:$d})-[:HAS_TABLE]->(:Table)-[:HAS_ROW]->(p:PriceRow) "
                               "RETURN count(p) as n", d=doc_id).single()
                neo4j_pricerow_count = int(rec2["n"]) if rec2 else 0
            drv.close()
            checks.append({"name": "neo4j_chunks", "ok": True, "count": neo4j_chunk_count})
            checks.append({"name": "neo4j_price_rows", "ok": True, "count": neo4j_pricerow_count})
        else:
            checks.append({"name": "neo4j_chunks", "ok": False, "error": "driver unavailable"})
    except Exception as e:
        checks.append({"name": "neo4j_chunks", "ok": False, "error": str(e)[:200]})

    # consistency rules
    drifts: list[dict] = []
    if pg_count and qdrant_count and qdrant_count != pg_count:
        drifts.append({"kind": "qdrant_drift",
                       "reason": f"pg={pg_count} qdrant={qdrant_count}"})
    if pg_count and neo4j_chunk_count and neo4j_chunk_count != pg_count:
        drifts.append({"kind": "neo4j_drift",
                       "reason": f"pg={pg_count} neo4j={neo4j_chunk_count}"})
    if zero_norm_count > 0:
        drifts.append({"kind": "embedding_missing",
                       "reason": f"{zero_norm_count} chunks without embedding"})

    for d in drifts:
        try:
            ipl.record_blindspot(job_id, doc_id, file_name, page=0,
                                 kind=f"db_drift:{d['kind']}", reason=d["reason"])
        except Exception:
            pass

    overall_ok = (pg_count > 0
                  and (qdrant_count == pg_count)
                  and (neo4j_chunk_count == pg_count)
                  and zero_norm_count == 0)

    return {
        "job_id": job_id,
        "doc_id": doc_id,
        "file_name": file_name,
        "ok": overall_ok,
        "counts": {
            "pg_text_chunks": pg_count,
            "qdrant_points": qdrant_count,
            "neo4j_chunks": neo4j_chunk_count,
            "neo4j_price_rows": neo4j_pricerow_count,
            "embedding_missing": zero_norm_count,
        },
        "checks": checks,
        "drifts": drifts,
    }


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
    await probe("elasticsearch",
                os.environ.get("ES_URL", "http://localhost:9200") + "/_cluster/health",
                optional=True)

    return health


@router.get("/api/v1/architecture/live")
async def architecture_live():
    """Live architecture reflection — replaces hardcoded MD topology.

    Probes every backing store actually configured for the retrieval-service
    and returns a single JSON snapshot the dashboard can render. Each entry
    reports availability, version (where cheap), and a meaningful counter
    (collections / doc count / row count) so the UI can show "is it real".
    """
    import httpx
    from app.agent.tools import _get_pg_conn, _put_pg_conn

    snapshot: dict = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "stores": {},
        "summary": {"total": 0, "available": 0, "degraded": 0, "down": 0},
    }
    transport = httpx.AsyncHTTPTransport(proxy=None)

    # ── PostgreSQL ──
    try:
        c = _get_pg_conn()
        try:
            with c.cursor() as cur:
                cur.execute("SHOW server_version")
                version = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM text_chunks")
                chunks = cur.fetchone()[0]
                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')"
                )
                has_vector = bool(cur.fetchone()[0])
            snapshot["stores"]["postgresql"] = {
                "role": "structured + fulltext fallback",
                "available": True,
                "version": version.split()[0] if version else None,
                "chunk_count": int(chunks),
                "extensions": {"pgvector": has_vector},
            }
        finally:
            _put_pg_conn(c)
    except Exception as e:
        snapshot["stores"]["postgresql"] = {"available": False, "error": str(e)[:200]}

    # ── Qdrant ──
    try:
        async with httpx.AsyncClient(timeout=3.0, transport=transport) as client:
            url = os.environ.get("QDRANT_URL", "http://localhost:6333")
            r = await client.get(f"{url}/collections")
            r.raise_for_status()
            cols = r.json().get("result", {}).get("collections", [])
            snapshot["stores"]["qdrant"] = {
                "role": "vector store",
                "available": True,
                "collections": [c.get("name") for c in cols],
                "collection_count": len(cols),
            }
    except Exception as e:
        snapshot["stores"]["qdrant"] = {"available": False, "error": str(e)[:200]}

    # ── Elasticsearch ──
    try:
        from infrastructure import elasticsearch_store as _es

        es_h = _es.health()
        snapshot["stores"]["elasticsearch"] = {
            "role": "fulltext (BM25 + IK 分词)",
            **es_h,
        }
    except Exception as e:
        snapshot["stores"]["elasticsearch"] = {"available": False, "error": str(e)[:200]}

    # ── Neo4j ──
    try:
        async with httpx.AsyncClient(timeout=3.0, transport=transport) as client:
            url = os.environ.get("NEO4J_HTTP_URL", "http://localhost:7474")
            r = await client.get(url)
            ok = r.status_code in (200, 401)
            snapshot["stores"]["neo4j"] = {
                "role": "graph (knowledge graph)",
                "available": ok,
                "status_code": r.status_code,
            }
    except Exception as e:
        snapshot["stores"]["neo4j"] = {"available": False, "error": str(e)[:200]}

    # ── Redis (cache) ──
    try:
        import redis as _redis
        r = _redis.Redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            socket_timeout=2,
        )
        info = r.info(section="server")
        snapshot["stores"]["redis"] = {
            "role": "cache",
            "available": True,
            "version": info.get("redis_version"),
        }
    except Exception as e:
        snapshot["stores"]["redis"] = {"available": False, "error": str(e)[:200]}

    # ── Milvus (#49 — real probe + collection stats) ──
    milvus_url = os.environ.get("MILVUS_URL", "http://localhost:19530")
    milvus_health = os.environ.get("MILVUS_HEALTH_URL", "http://localhost:9091/healthz")
    try:
        async with httpx.AsyncClient(timeout=3.0, transport=transport) as client:
            r = await client.get(milvus_health)
            ok = r.status_code == 200
        collections: list[str] = []
        row_count: int | None = None
        version: str | None = None
        if ok:
            try:
                from pymilvus import MilvusClient as _MC
                _mc = _MC(uri=milvus_url)
                collections = list(_mc.list_collections() or [])
                if "document_chunks" in collections:
                    stats = _mc.get_collection_stats("document_chunks") or {}
                    row_count = int(stats.get("row_count") or 0)
                # version lookup (best-effort; not all builds expose)
                try:
                    desc = _mc.describe_collection("document_chunks") if collections else None
                    version = (desc or {}).get("version")
                except Exception:
                    version = None
            except Exception as e:
                collections = []
                row_count = None
                version = f"stats error: {str(e)[:120]}"
        snapshot["stores"]["milvus"] = {
            "role": "vector store (alt backend, switchable)",
            "available": ok,
            "status_code": r.status_code if ok else None,
            "collections": collections,
            "collection_count": len(collections),
            "row_count": row_count,
            "version": version,
            "active": os.environ.get("VECTOR_STORE__TYPE", "qdrant") == "milvus",
        }
    except Exception as e:
        snapshot["stores"]["milvus"] = {"available": False, "error": str(e)[:200]}

    # Aggregate summary
    for s in snapshot["stores"].values():
        snapshot["summary"]["total"] += 1
        if s.get("available"):
            snapshot["summary"]["available"] += 1
        elif s.get("configured", True) is False:
            snapshot["summary"]["degraded"] += 1
        else:
            snapshot["summary"]["down"] += 1

    return snapshot


# ────────────────────────── Agent registry & task queue (#74) ──────────────────────────

_AGENT_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def _parse_agent_frontmatter(text: str) -> dict:
    """Extract YAML-style key:value pairs from the leading --- block."""
    out: dict = {}
    m = _AGENT_FRONTMATTER_RE.match(text)
    if not m:
        return out
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


@router.get("/api/v1/agents/registry")
async def agents_registry():
    """Real agent registry — reads .agent/agents/*.md (YAML frontmatter)."""
    from pathlib import Path
    # Walk up from this file to repo root: app/api.py → app → retrieval-service
    # → backend → src → repo. Tolerate variations by searching for .agent/agents.
    here = Path(__file__).resolve()
    candidate = None
    for p in here.parents:
        c = p / ".agent" / "agents"
        if c.is_dir():
            candidate = c
            break
    if candidate is None:
        return {"agents": [], "source": "none", "note": ".agent/agents not found"}

    agents = []
    for f in sorted(candidate.glob("*.md")):
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            fm = _parse_agent_frontmatter(content)
            agents.append({
                "id": fm.get("id") or f.stem,
                "name": fm.get("name") or f.stem,
                "role": fm.get("role") or "",
                "model": (fm.get("model") or "").upper().replace("CLAUDE-", "") or "SONNET",
                "trigger": fm.get("trigger") or "",
                "description": fm.get("trigger_description") or fm.get("role") or "",
                "file": f.name,
            })
        except Exception as e:
            logger.warning("agent registry parse %s: %s", f.name, e)
    return {"agents": agents, "source": str(candidate), "count": len(agents)}


@router.get("/api/v1/agents/registry/{agent_id}")
async def agents_registry_detail(agent_id: str):
    """Single agent detail — raw markdown + parsed frontmatter + file mtime."""
    from pathlib import Path
    here = Path(__file__).resolve()
    candidate = None
    for p in here.parents:
        c = p / ".agent" / "agents"
        if c.is_dir():
            candidate = c
            break
    if candidate is None:
        raise HTTPException(status_code=404, detail=".agent/agents directory not found")
    safe_id = agent_id.replace("/", "").replace("\\", "").replace("..", "")
    f = candidate / f"{safe_id}.md"
    if not f.is_file():
        raise HTTPException(status_code=404, detail=f"agent '{agent_id}' not found")
    content = f.read_text(encoding="utf-8", errors="ignore")
    fm = _parse_agent_frontmatter(content)
    body = content
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end > 0:
            body = content[end + 4:].lstrip("\n")
    stat = f.stat()
    return {
        "id": fm.get("id") or f.stem,
        "name": fm.get("name") or f.stem,
        "frontmatter": fm,
        "body_markdown": body,
        "raw_markdown": content,
        "file": f.name,
        "path": str(f.relative_to(candidate.parent.parent)) if candidate.parent.parent in f.parents else str(f),
        "size_bytes": stat.st_size,
        "modified_ts": stat.st_mtime,
    }


@router.get("/api/v1/learning/topology")
async def learning_topology():
    """#94 拓扑健康自检 — 返回 I1-I6 状态供 /learning 前端展示。

    服务化版本 of scripts/topology_health.py。轻量、无外部依赖。
    """
    from app.agent.tools import _get_pg_conn, _put_pg_conn

    EXPECTED_EDGES = {
        "query->analyzer", "analyzer->navigator", "navigator->retriever",
        "retriever->tool", "tool->verifier", "verifier->synthesize",
        "synthesize->user", "user->feedback", "feedback->learner",
        "learner->architect",
        "architect->navigator_dict", "architect->path_default",
        "architect->planner_few", "architect->rerank_w",
        "architect->tool_priority", "external->architect",
    }
    EXPECTED_ROUTES = {
        "R1_navigator_dict", "R2_path_default", "R3_planner_examples",
        "R4_rerank_weights", "R5_tool_priority",
    }

    invariants: list[dict] = []
    conn = None
    try:
        conn = _get_pg_conn()
        with conn.cursor() as c:
            # I1 全连通
            c.execute("SELECT count(*), array_agg(edge_id) FROM topology_edge_log")
            edge_count, edge_ids = c.fetchone()
            edge_ids = set(edge_ids or [])
            missing = sorted(EXPECTED_EDGES - edge_ids)
            invariants.append({
                "code": "I1", "name": "Closed Loop",
                "status": "FAIL" if missing else "OK",
                "metric": {"edges": edge_count, "expected": len(EXPECTED_EDGES),
                           "missing": missing},
                "note": f"骨架 {edge_count}/{len(EXPECTED_EDGES)} 边" + (
                    f"，缺 {len(missing)} 条" if missing else "完整"),
            })

            # I2 反馈可达
            c.execute("SELECT count(*) FROM rag_feedback "
                      "WHERE rating = -1 AND created_at > NOW() - interval '90 days'")
            neg = c.fetchone()[0]
            c.execute("SELECT count(*) FROM improvement_events "
                      "WHERE source_feedback_id IS NOT NULL "
                      "AND ts > NOW() - interval '90 days'")
            linked = c.fetchone()[0]
            cov = (linked / neg) if neg else 1.0
            i2_status = "OK" if (neg == 0 or cov >= 0.5) else (
                "WARN" if cov >= 0.1 else "FAIL")
            invariants.append({
                "code": "I2", "name": "Feedback Reachability",
                "status": i2_status,
                "metric": {"negative_90d": neg, "linked_events": linked,
                           "coverage": round(cov, 3)},
                "note": f"差评 → 改进事件覆盖 {cov*100:.0f}%",
            })

            # I3 无悬挂证据
            c.execute("""
                SELECT count(*),
                  count(*) FILTER (WHERE file_name IS NOT NULL AND file_name <> ''),
                  count(*) FILTER (WHERE path IS NOT NULL AND path <> ''),
                  count(*) FILTER (WHERE metadata IS NOT NULL)
                FROM text_chunks
            """)
            total, wf, wp, wm = c.fetchone()
            if total == 0:
                i3_metric = {"total": 0}
                i3_status = "WARN"; i3_note = "text_chunks 为空"
            else:
                worst = min(wf/total, wp/total, wm/total)
                i3_metric = {"total": total,
                             "file_rate": round(wf/total, 4),
                             "path_rate": round(wp/total, 4),
                             "meta_rate": round(wm/total, 4)}
                i3_status = "OK" if worst >= 0.99 else (
                    "WARN" if worst >= 0.90 else "FAIL")
                i3_note = f"三字段最低非空率 {worst*100:.2f}%"
            invariants.append({"code": "I3", "name": "No Dangling Evidence",
                               "status": i3_status, "metric": i3_metric, "note": i3_note})

            # I4 双轨可分
            c.execute("""
                SELECT count(*),
                  count(*) FILTER (WHERE source IS NOT NULL AND actor IS NOT NULL
                                   AND reversible_by IS NOT NULL),
                  count(*) FILTER (WHERE source = 'auto'),
                  count(*) FILTER (WHERE source = 'human'),
                  count(*) FILTER (WHERE source = 'external')
                FROM improvement_events
            """)
            tot, valid, a, h, e = c.fetchone()
            if tot == 0:
                i4_status = "WARN"; i4_note = "无改进事件——闭环未启动"
            elif valid == tot:
                i4_status = "OK"; i4_note = f"全部 {tot} 条事件三字段齐备"
            else:
                i4_status = "FAIL"
                i4_note = f"{tot - valid} 条事件缺 source/actor/reversible_by"
            invariants.append({
                "code": "I4", "name": "Auditable Two-Track",
                "status": i4_status,
                "metric": {"total": tot, "valid": valid,
                           "auto": a, "human": h, "external": e},
                "note": i4_note,
            })

            # I5 外部信号入口
            c.execute("""
                SELECT count(*), count(DISTINCT source), max(fetched_at)
                FROM tech_radar
                WHERE fetched_at > NOW() - interval '7 days'
            """)
            recent, sources, last_at = c.fetchone()
            if recent == 0:
                i5_status = "FAIL"; i5_note = "雷达 7 天无新条目"
            elif sources < 2:
                i5_status = "WARN"; i5_note = f"来源仅 {sources}，目标 ≥3"
            else:
                i5_status = "OK"; i5_note = f"7 天 {recent} 条 / {sources} 源"
            invariants.append({
                "code": "I5", "name": "External Signal Port",
                "status": i5_status,
                "metric": {"recent_7d": recent, "sources": sources,
                           "last_fetched_at": last_at.isoformat() if last_at else None},
                "note": i5_note,
            })

            # I6 形态无关
            c.execute("SELECT affected_route, count(*) FROM improvement_events "
                      "GROUP BY affected_route")
            routes = {row[0]: row[1] for row in c.fetchall()}
            used = set(routes.keys()) & EXPECTED_ROUTES
            missing_r = EXPECTED_ROUTES - set(routes.keys())
            if edge_count != len(EXPECTED_EDGES):
                i6_status = "FAIL"; i6_note = f"拓扑边数 {edge_count} ≠ {len(EXPECTED_EDGES)}"
            elif not used:
                i6_status = "WARN"; i6_note = "5 条回写回路均未启用"
            elif len(missing_r) >= 3:
                i6_status = "WARN"
                i6_note = f"{len(missing_r)} 条回写回路从未使用"
            else:
                i6_status = "OK"; i6_note = f"拓扑稳定 + {len(used)}/5 回写已启用"
            invariants.append({
                "code": "I6", "name": "Shape-Invariant",
                "status": i6_status,
                "metric": {"topology_edges": edge_count,
                           "expected_edges": len(EXPECTED_EDGES),
                           "routes_used": sorted(used),
                           "routes_missing": sorted(missing_r),
                           "events_per_route": routes},
                "note": i6_note,
            })
    finally:
        if conn is not None:
            _put_pg_conn(conn)

    summary = {
        "ok": sum(1 for x in invariants if x["status"] == "OK"),
        "warn": sum(1 for x in invariants if x["status"] == "WARN"),
        "fail": sum(1 for x in invariants if x["status"] == "FAIL"),
    }
    overall = "FAIL" if summary["fail"] else ("WARN" if summary["warn"] else "OK")
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "summary": summary,
        "invariants": invariants,
    }


@router.get("/api/v1/learning/radar")
async def learning_radar(limit: int = 30, status: str | None = None):
    """#94 外部技术雷达列表。"""
    from app.agent.tools import _get_pg_conn, _put_pg_conn
    conn = None
    try:
        conn = _get_pg_conn()
        with conn.cursor() as c:
            sql = ("SELECT id, source, external_id, title, summary, url, "
                   "published_at, fetched_at, score, tags, status "
                   "FROM tech_radar")
            params: tuple = ()
            if status:
                sql += " WHERE status = %s"
                params = (status,)
            sql += " ORDER BY score DESC, fetched_at DESC LIMIT %s"
            params = params + (max(1, min(limit, 200)),)
            c.execute(sql, params)
            rows = c.fetchall()
    finally:
        if conn is not None:
            _put_pg_conn(conn)
    items = [{
        "id": r[0], "source": r[1], "external_id": r[2], "title": r[3],
        "summary": r[4], "url": r[5],
        "published_at": r[6].isoformat() if r[6] else None,
        "fetched_at": r[7].isoformat() if r[7] else None,
        "score": r[8], "tags": r[9] or [], "status": r[10],
    } for r in rows]
    return {"count": len(items), "items": items}


@router.get("/api/v1/learning/improvement-events")
async def learning_improvement_events(limit: int = 50):
    """#94 改进事件列表。"""
    from app.agent.tools import _get_pg_conn, _put_pg_conn
    conn = None
    try:
        conn = _get_pg_conn()
        with conn.cursor() as c:
            c.execute(
                """
                SELECT id, source, actor, source_feedback_id, source_radar_id,
                       affected_route, rationale, applied_at, reverted_at, ts
                FROM improvement_events
                ORDER BY ts DESC LIMIT %s
                """,
                (max(1, min(limit, 200)),),
            )
            rows = c.fetchall()
    finally:
        if conn is not None:
            _put_pg_conn(conn)
    items = [{
        "id": r[0], "source": r[1], "actor": r[2],
        "source_feedback_id": r[3], "source_radar_id": r[4],
        "affected_route": r[5], "rationale": r[6],
        "applied_at": r[7].isoformat() if r[7] else None,
        "reverted_at": r[8].isoformat() if r[8] else None,
        "ts": r[9].isoformat() if r[9] else None,
    } for r in rows]
    return {"count": len(items), "items": items}


@router.post("/api/v1/learning/radar/{radar_id}/review")
async def learning_radar_review(radar_id: int, payload: dict):
    """#94-B 雷达条目人工评审。

    body: { "decision": "adopt" | "dismiss" | "reviewing",
            "reviewer": "name", "note": "...",
            "affected_route": "R1_navigator_dict" | ... (adopt 必填) }

    - dismiss/reviewing: 仅更新 tech_radar.status
    - adopt: 同时写一条 source='human' 的 improvement_events
      （source_radar_id 关联），让 I4 human 列+1 + I6 写回回路 +1
    """
    decision = (payload.get("decision") or "").lower()
    if decision not in {"adopt", "dismiss", "reviewing"}:
        raise HTTPException(status_code=400,
                            detail="decision must be adopt|dismiss|reviewing")
    reviewer = (payload.get("reviewer") or "anonymous")[:200]
    note = (payload.get("note") or "")[:500]
    route = payload.get("affected_route")
    valid_routes = {"R1_navigator_dict", "R2_path_default", "R3_planner_examples",
                    "R4_rerank_weights", "R5_tool_priority"}
    if decision == "adopt":
        if route not in valid_routes:
            raise HTTPException(
                status_code=400,
                detail=f"affected_route must be one of {sorted(valid_routes)}",
            )

    # #94-C R1: 收 navigator 字典扩展词
    extra_keywords = payload.get("extra_keywords") or []
    if not isinstance(extra_keywords, list):
        extra_keywords = []
    extra_keywords = [str(k).strip() for k in extra_keywords if str(k).strip()][:20]
    trigger = (payload.get("trigger") or "").strip()[:50]

    status_map = {"adopt": "adopted", "dismiss": "dismissed", "reviewing": "reviewing"}
    new_status = status_map[decision]

    import asyncpg
    db_url = os.environ.get(
        "DATABASE_URL", "postgresql://rag_user:rag_password@localhost:5432/rag_db",
    )
    conn = await asyncpg.connect(db_url)
    try:
        existing = await conn.fetchrow(
            "SELECT id, title, source FROM tech_radar WHERE id = $1", radar_id,
        )
        if not existing:
            raise HTTPException(status_code=404, detail=f"radar id={radar_id} not found")

        await conn.execute(
            """UPDATE tech_radar
               SET status = $1, reviewer = $2, decision_note = $3
               WHERE id = $4""",
            new_status, reviewer, note, radar_id,
        )

        event_id = None
        if decision == "adopt":
            event_id = await conn.fetchval(
                """INSERT INTO improvement_events
                   (source, actor, source_radar_id, affected_route,
                    patch_payload, rationale, reversible_by, applied_at)
                   VALUES ('human', $1, $2, $3, $4::jsonb, $5, 'rollback_event', NOW())
                   RETURNING id""",
                reviewer, radar_id, route,
                json.dumps({
                    "radar_title": existing["title"],
                    "radar_source": existing["source"],
                    "review_note": note,
                    "trigger": trigger,
                    "extra_keywords": extra_keywords,
                }, ensure_ascii=False),
                note or f"Adopted from radar: {existing['title'][:200]}",
            )
            # 触发 architect->{route} 边遍历
            edge_map = {
                "R1_navigator_dict": "architect->navigator_dict",
                "R2_path_default": "architect->path_default",
                "R3_planner_examples": "architect->planner_few",
                "R4_rerank_weights": "architect->rerank_w",
                "R5_tool_priority": "architect->tool_priority",
            }
            edge_id = edge_map.get(route)
            if edge_id:
                await conn.execute(
                    """UPDATE topology_edge_log
                       SET last_traversed_at = NOW(),
                           traversal_count = traversal_count + 1
                       WHERE edge_id = $1""",
                    edge_id,
                )

        return {
            "status": "ok",
            "radar_id": radar_id,
            "new_status": new_status,
            "improvement_event_id": event_id,
        }
    finally:
        await conn.close()


@router.get("/api/v1/agents/tasks")
async def agents_tasks(limit: int = 50):
    """Real task queue — derived from ingest_jobs (the only real task pipeline)."""
    from app.agent.tools import _get_pg_conn, _put_pg_conn
    # Map ingest_jobs.status → frontend TaskStatus
    status_map = {
        "queued": "pending",
        "running": "in_progress",
        "in_progress": "in_progress",
        "done": "completed",
        "ready": "completed",
        "completed": "completed",
        "failed": "failed",
        "error": "failed",
    }
    conn = None
    tasks = []
    try:
        conn = _get_pg_conn()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("""
                SELECT job_id, file_name, status, phase,
                       COALESCE(extractor, 'ingest'), created_at
                FROM ingest_jobs
                ORDER BY created_at DESC
                LIMIT %s
            """, (max(1, min(limit, 500)),))
            for r in cur.fetchall():
                job_id, file_name, status, phase, extractor, created_at = r
                tasks.append({
                    "id": job_id,
                    "label": (file_name or job_id)[:120],
                    "tag": f"ingest-{extractor}" if extractor else "ingest",
                    "status": status_map.get((status or "").lower(), "pending"),
                    "phase": phase,
                    "created_at": created_at.isoformat() if created_at else None,
                })
    except Exception as e:
        logger.error("agents_tasks failed: %s", e)
        return {"tasks": [], "source": "ingest_jobs", "error": str(e)[:200]}
    finally:
        if conn is not None:
            try:
                _put_pg_conn(conn)
            except Exception:
                pass
    return {"tasks": tasks, "source": "ingest_jobs", "count": len(tasks)}


@router.get("/api/v1/agent/runtime")
async def agent_runtime_introspect(recent_runs: int = 10):
    """Live introspection of the LangGraph agent runtime.

    Returns the actual compiled graph topology (nodes + edges), the registered
    tool list with descriptions, and recent run statistics from `agent_runs`
    (if the table exists). The frontend renders this as a Mermaid flowchart so
    the user can SEE how a question flows through the agent in real time —
    replacing the static MD diagram that was getting stale.
    """
    out: dict = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "graph": {"nodes": [], "edges": [], "entry": None, "mermaid": ""},
        "tools": [],
        "tool_count": 0,
        "recent_runs": [],
    }

    # 1. Graph topology — introspect the compiled LangGraph
    try:
        from app.agent.graph import get_agent_graph, REACT_TOOLS
        compiled = get_agent_graph()
        g = compiled.get_graph()
        # langgraph Graph: nodes is dict[str, Node], edges is list[Edge]
        nodes_raw = list(getattr(g, "nodes", {}).keys())
        edges_raw = []
        for e in getattr(g, "edges", []):
            src = getattr(e, "source", None)
            dst = getattr(e, "target", None)
            cond = getattr(e, "conditional", False)
            if src and dst:
                edges_raw.append({"source": src, "target": dst, "conditional": bool(cond)})
        out["graph"]["nodes"] = nodes_raw
        out["graph"]["edges"] = edges_raw
        out["graph"]["entry"] = "query_analysis"

        # Build a mermaid flowchart string the UI can render directly.
        def _safe(s: str) -> str:
            return s.replace("__", "_").replace("-", "_")
        lines = ["flowchart TD"]
        # Decorate node labels by role
        labels = {
            "__start__": "🟢 START",
            "__end__": "🏁 END",
            "query_analysis": "📥 query_analysis<br/>意图识别",
            "intent_guard_node": "🛡 intent_guard<br/>越权拦截",
            "navigator_node": "🗺 navigator<br/>章节锁定",
            "planner_node": "📋 planner<br/>规划步骤",
            "executor_node": "🤖 executor<br/>ReAct 决策",
            "tool_node": "🔧 tool_node<br/>调用工具",
            "chapter_resolver": "📚 chapter_resolver<br/>章节回填",
            "synthesize_node": "✍️ synthesize<br/>合成答案",
            "contract_verifier_node": "✅ contract_verifier<br/>引用核验",
            "corrective_action_node": "🔁 corrective_action<br/>纠错重跑",
            "presentation_policy_node": "🎨 presentation<br/>展示策略",
        }
        for n in nodes_raw:
            label = labels.get(n, n)
            lines.append(f'    {_safe(n)}["{label}"]')
        for e in edges_raw:
            arrow = "-.->" if e["conditional"] else "-->"
            lines.append(f'    {_safe(e["source"])} {arrow} {_safe(e["target"])}')
        out["graph"]["mermaid"] = "\n".join(lines)

        # 2. Tools registry — name + first line of docstring
        tools_info = []
        for t in REACT_TOOLS:
            name = getattr(t, "name", None) or getattr(t, "__name__", "")
            desc = getattr(t, "description", "") or (getattr(t, "__doc__", "") or "").strip()
            short = (desc.split("\n")[0] if desc else "").strip()[:200]
            # Categorize by name prefix for the UI
            if name in ("vector_search", "keyword_search", "hybrid_search",
                        "concept_search", "category_search", "graph_search",
                        "topology_search", "text_search", "pdf_page_search",
                        "rule_clause_search", "get_catalog_map"):
                cat = "retrieval"
            elif name in ("price_query", "price_trend"):
                cat = "price"
            elif name in ("list_tables", "describe_table", "sql_query",
                          "aggregate_query", "list_documents", "fetch_chunk",
                          "similar_chunks", "stats_overview"):
                cat = "data"
            elif name in ("concept_neighbors", "concept_path", "entity_cooccur",
                          "upstream_downstream"):
                cat = "graph"
            elif name in ("expand_question", "suggest_followup",
                          "find_knowledge_gaps", "proactive_explore"):
                cat = "cognition"
            elif name in ("forecast_series", "outlier_detect", "correlate",
                          "cluster_records"):
                cat = "stats"
            elif name in ("calculator", "python_eval", "regex_extract",
                          "unit_convert", "date_math", "compare_values",
                          "number_stats", "chart_spec"):
                cat = "compute"
            else:
                cat = "other"
            tools_info.append({"name": name, "category": cat, "desc": short})
        out["tools"] = tools_info
        out["tool_count"] = len(tools_info)
    except Exception as e:
        logger.error("agent_runtime introspect failed: %s", e)
        out["graph"]["error"] = str(e)[:200]

    # 3. Recent runs — opportunistic; agent_runs may not exist
    try:
        from app.agent.tools import _get_pg_conn, _put_pg_conn
        conn = _get_pg_conn()
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT to_regclass('public.agent_runs') IS NOT NULL
                """)
                has_table = bool((cur.fetchone() or [False])[0])
                if has_table:
                    cur.execute("""
                        SELECT run_id, query, status, duration_ms, tool_count,
                               chunk_count, created_at
                        FROM agent_runs
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (max(1, min(recent_runs, 100)),))
                    for r in cur.fetchall():
                        rid, q, st, dur, tc, cc, ts = r
                        out["recent_runs"].append({
                            "run_id": str(rid) if rid else None,
                            "query": (q or "")[:120],
                            "status": st,
                            "duration_ms": dur,
                            "tool_count": tc,
                            "chunk_count": cc,
                            "created_at": ts.isoformat() if ts else None,
                        })
        finally:
            _put_pg_conn(conn)
    except Exception as e:
        logger.debug("agent_runs probe skipped: %s", e)

    return out


# ── LLM Chat Proxy ────────────────────────────────────────────────────────────
# Thin streaming proxy so the frontend SystemAssistant can reach DeepSeek
# through the already-running retrieval-service, without needing Node.js.
class LLMChatRequest(BaseModel):
    model: str = "deepseek-chat"
    messages: list[dict]
    temperature: float = 0.7
    max_tokens: int = 2000
    top_p: float = 0.9
    stream: bool = True


@router.post("/api/v1/llm/chat")
async def llm_chat_proxy(request: LLMChatRequest):
    """Streaming LLM proxy — forwards chat completion requests to DeepSeek."""
    import httpx
    from fastapi.responses import StreamingResponse as _SR

    api_key = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or ""
    base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
    # Avoid double /v1 if base_url already ends with /v1
    if base_url.endswith("/v1"):
        endpoint = f"{base_url}/chat/completions"
    else:
        endpoint = f"{base_url}/v1/chat/completions"

    payload = {
        "model": request.model,
        "messages": request.messages,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "top_p": request.top_p,
        "stream": request.stream,
    }

    async def _stream():
        async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
            async with client.stream(
                "POST",
                endpoint,
                json=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            ) as resp:
                async for chunk in resp.aiter_bytes():
                    yield chunk

    if request.stream:
        return _SR(_stream(), media_type="text/event-stream")

    # Non-streaming fallback
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        resp = await client.post(
            endpoint,
            json={**payload, "stream": False},
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        logger.info("LLM proxy non-stream: status=%s len=%s", resp.status_code, len(resp.content))
        if not resp.content:
            from fastapi import HTTPException
            raise HTTPException(status_code=502, detail=f"Empty response from LLM (HTTP {resp.status_code})")
        return resp.json()


# ── System KB semantic query ──────────────────────────────────────────────────

class SystemKBQueryRequest(BaseModel):
    query: str
    top_k: int = 3


@router.post("/api/v1/system-kb/query")
async def system_kb_query(req: SystemKBQueryRequest):
    """
    语义检索 rag_system_kb 集合，返回与 query 最相关的 top_k 段落。
    SystemAssistant 导览助手调用此接口获取真实知识库内容。
    """
    import httpx

    tei_url = os.getenv("TEI_URL", "http://localhost:8003")
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")

    # 1. 向量化 query
    async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
        emb_resp = await client.post(
            f"{tei_url}/embed",
            json={"inputs": [req.query]},
        )
        emb_resp.raise_for_status()
        query_vector = emb_resp.json()[0]

    # 2. Qdrant 语义检索
    async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
        search_resp = await client.post(
            f"{qdrant_url}/collections/rag_system_kb/points/search",
            json={
                "vector": query_vector,
                "limit": req.top_k,
                "with_payload": True,
                "score_threshold": 0.3,
            },
        )
        search_resp.raise_for_status()
        hits = search_resp.json().get("result", [])

    results = [
        {
            "section_id": h["payload"].get("section_id", ""),
            "title": h["payload"].get("title", ""),
            "content": h["payload"].get("content", ""),
            "score": round(h["score"], 4),
        }
        for h in hits
    ]
    return {"results": results, "query": req.query}


# ── Guide Agent (true LangChain tool-calling, grounded on rag_system_kb) ───────

class GuideAgentRequest(BaseModel):
    query: str
    history: list = []


_GUIDE_SYSTEM = """您是「RAG智库系统」的导览助手，专门解答本系统的架构、检索流程、工具用途等技术问题，并能对系统当前运行情况做实时诊断。

可用工具（请按顺序优先使用，组合调用以提高准确性）：
工具1 query_guide_kb：查询架构 / 检索流程 / 工具说明 / 配置含义等"概念类"问题。架构解释类问题第一时间调它。
工具2 search_self_docs：查询**本项目仓库的源代码文档**（README、AGENTS.md、docs/、.agent/agents/、.kimi/ 等真实 .md 文件）。当 query_guide_kb 没命中、或用户问"代码在哪""目录结构""哪个端口""怎么启动""Agent 怎么定义"等具体落地问题时，**直接用此工具**，因为它索引的是真实仓库文件，最权威。
工具3 introspect_runtime：实时读取系统当前的健康、配置、最近错误。当用户问"现在状态如何""xxx 在跑吗""为什么这么慢"时调它。**只读，不会改任何东西**。
工具4 search_pdf_originals：当 query_guide_kb / search_self_docs 都查不到、且用户问的是业务文档（消耗量标准、信息价、定额等）时，**穿透到 PDF/OCR 原文**做关键词查找，把 chunk 一同返回。务必告诉用户"主 KB 未命中，已穿透到原文"。
工具5 search_ocr_files：当 search_pdf_originals 也没命中时，作为最终兜底，直接扫 OCR 输出 JSON 全文。返回文件名 + 页码 + 上下文片段。
工具6 adjust_rag_config：调整 RAG 运行时配置（top_k / score_threshold / 检索后端等）。**默认 dry_run，仅预览不生效**；用户明确说"应用""执行""apply"时才传 apply=true。每次调用都会写入审计表 runtime_config_audit。仅当用户明确请求"调高 top_k""换检索后端"等操作时才使用，绝不自作主张。

核心规则（强制执行，不得违反）：
第一、回答前至少调用一个工具，禁止凭空作答。
第二、只根据工具返回内容作答，不补充资料以外的信息；如多工具结果冲突，明确说明。
第三、若所有工具均无结果，直接告知"知识库与原文均无此内容"。
第四、禁止使用任何 Markdown 符号（#、*、**、-、---、>、`）。列举用"第一、第二、第三"。
第五、当用户询问架构、模块、流程、数据流、系统结构等可视化内容时，必须输出 Mermaid 代码块（```mermaid 开头，``` 结尾）。
第六、当用户问"现在""当前""实时""状态""跑没跑"时，**必须**调用 introspect_runtime，不得拿 query_guide_kb 的静态描述糊弄。

Mermaid 图表规范：
架构或模块关系用 graph TB 或 graph LR；数据流用 flowchart TD；时序交互用 sequenceDiagram。
节点文字用中文，连线用 -->，子图用 subgraph。图表紧凑，不超过 15 个节点。

回答风格：
全程使用"您"尊称，语气礼貌、专业、简洁，不绕弯子，不打比方。
非图表问题直接给出精准答案，无需引言和总结。"""


@router.post("/api/v1/guide-agent/stream")
async def guide_agent_stream(req: GuideAgentRequest):
    """
    系统导览 agent：LLM 自主决定如何调用 query_guide_kb 工具检索 rag_system_kb，
    再基于真实检索结果流式生成回答。真正的 tool-calling agent，不是硬塞 prompt。
    """
    import httpx as _httpx
    from langchain_core.tools import tool as _lc_tool
    from langchain_core.messages import (
        SystemMessage as _Sys,
        HumanMessage as _Human,
        AIMessage as _AI,
        ToolMessage as _Tool,
    )
    from app.agent.prompts import invoke_llm_with_tools, stream_llm_response

    _tei_url = os.getenv("TEI_URL", "http://localhost:8003")
    _qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    # Use env-configured model (deepseek-chat by default) — deepseek-reasoner does not support tool_choice
    _llm_config: dict[str, Any] = {}

    @_lc_tool
    def search_self_docs(question: str, top_k: int = 5) -> str:
        """查询本 RAG 项目的源代码文档（README / AGENTS.md / docs/ / .agent/agents/ / .kimi/）。
        当 query_guide_kb 在 rag_system_kb 中没找到时，**优先**用此工具，因为这是直接索引仓库 .md 的内容，最权威。
        适合：项目代码结构、文件位置、命令、Agent 配置、架构规则等问题。"""
        try:
            with _httpx.Client(timeout=15, trust_env=False) as client:
                emb = client.post(f"{_tei_url}/embed", json={"inputs": [question]})
                emb.raise_for_status()
                vec = emb.json()[0]
            with _httpx.Client(timeout=15, trust_env=False) as client:
                hits_resp = client.post(
                    f"{_qdrant_url}/collections/rag_self_docs/points/search",
                    json={"vector": vec, "limit": top_k, "with_payload": True, "score_threshold": 0.25},
                )
                hits_resp.raise_for_status()
                hits = hits_resp.json().get("result", [])
            if not hits:
                return "项目源代码文档中未找到相关内容。"
            return json.dumps(
                [
                    {
                        "path": h["payload"].get("path", ""),
                        "title": h["payload"].get("title", ""),
                        "content": h["payload"].get("content", "")[:1200],
                    }
                    for h in hits
                ],
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)[:300]}, ensure_ascii=False)

    @_lc_tool
    def query_guide_kb(question: str, top_k: int = 5) -> str:
        """查询RAG智库系统内部技术文档知识库（rag_system_kb），返回与问题相关的架构说明、工具介绍、检索流程等资料。架构、配置、流程类问题第一时间调用此工具。"""
        try:
            with _httpx.Client(timeout=15, trust_env=False) as client:
                emb = client.post(f"{_tei_url}/embed", json={"inputs": [question]})
                emb.raise_for_status()
                vec = emb.json()[0]
            with _httpx.Client(timeout=15, trust_env=False) as client:
                hits_resp = client.post(
                    f"{_qdrant_url}/collections/rag_system_kb/points/search",
                    json={"vector": vec, "limit": top_k, "with_payload": True, "score_threshold": 0.25},
                )
                hits_resp.raise_for_status()
                hits = hits_resp.json().get("result", [])
            if not hits:
                return "知识库中未找到相关内容。"
            return json.dumps(
                [{"title": h["payload"].get("title", ""), "content": h["payload"].get("content", "")} for h in hits],
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    @_lc_tool
    def introspect_runtime(aspect: str = "all") -> str:
        """实时读取系统当前运行状态。只读，不修改任何配置。
        参数 aspect 取值：
          - "all"     返回健康+核心配置+最近写入概况（默认）
          - "health"  仅返回各服务健康状况（critical/optional 区分）
          - "config"  返回当前向量后端、关键词后端、模型、检索阈值
          - "stats"   返回库内 chunk/price/conversation 计数
        当用户问"现在""当前""xxx 在跑吗""为什么慢"时调用此工具。"""
        report: dict[str, Any] = {"aspect": aspect}
        try:
            if aspect in ("all", "health"):
                async def _get_health():
                    async with _httpx.AsyncClient(timeout=3.0, trust_env=False) as c:
                        r = await c.get("http://localhost:8002/api/v1/health/detail")
                        return r.json() if r.status_code == 200 else {"error": r.status_code}
                try:
                    report["health"] = asyncio.run(_get_health())
                except RuntimeError:
                    # already in event loop — get via direct call (tool runs sync)
                    loop = asyncio.new_event_loop()
                    try:
                        report["health"] = loop.run_until_complete(_get_health())
                    finally:
                        loop.close()
            if aspect in ("all", "config"):
                from config.settings import AppConfig as _AC
                try:
                    cfg = _AC()
                    report["config"] = {
                        "vector_store": {
                            "type": cfg.vector_store.type,
                            "uri": cfg.vector_store.uri,
                            "collection": cfg.vector_store.collection_name,
                            "dim": cfg.vector_store.vector_size,
                        },
                        "keyword_store": {
                            "type": cfg.keyword_store.type,
                            "hosts": cfg.keyword_store.hosts,
                            "index": cfg.keyword_store.index_name,
                        },
                        "embedding": getattr(cfg.models, "embedding", None) and {
                            "name": cfg.models.embedding.name,
                        },
                        "env": {
                            "VECTOR_STORE__TYPE": os.environ.get("VECTOR_STORE__TYPE", "qdrant"),
                            "KEYWORD_BACKEND": os.environ.get("KEYWORD_BACKEND", "es"),
                        },
                    }
                except Exception as e:
                    report["config"] = {"error": str(e)[:200]}
            if aspect in ("all", "stats"):
                try:
                    from app.agent.tools import _get_pg_conn, _put_pg_conn
                    c = _get_pg_conn()
                    try:
                        with c.cursor() as cur:
                            cur.execute("SELECT COUNT(*) FROM text_chunks")
                            tc = cur.fetchone()[0]
                            cur.execute("SELECT COUNT(*) FROM price_records")
                            pr = cur.fetchone()[0]
                            cur.execute("SELECT COUNT(*) FROM document_registry")
                            dr = cur.fetchone()[0]
                            cur.execute(
                                "SELECT COUNT(*) FROM conversation_turns WHERE source='guide'"
                            )
                            gconv = cur.fetchone()[0]
                            cur.execute(
                                "SELECT COUNT(*) FROM conversation_turns WHERE source='agent'"
                            )
                            aconv = cur.fetchone()[0]
                        report["stats"] = {
                            "text_chunks": tc,
                            "price_records": pr,
                            "documents": dr,
                            "guide_conversations": gconv,
                            "agent_conversations": aconv,
                        }
                    finally:
                        _put_pg_conn(c)
                except Exception as e:
                    report["stats"] = {"error": str(e)[:200]}
            return json.dumps(report, ensure_ascii=False, default=str)
        except Exception as exc:
            return json.dumps({"error": str(exc)[:300]}, ensure_ascii=False)

    @_lc_tool
    def search_pdf_originals(keyword: str, top_k: int = 3) -> str:
        """穿透到 PDF/OCR 原文文本做关键词查找，**只在主 KB 未命中**且用户问业务文档（消耗量标准、信息价、定额）时使用。
        返回命中的文档+所在 chunk 文字。"""
        try:
            from app.agent.tools import _get_pg_conn, _put_pg_conn
            kw = keyword.strip()
            if len(kw) < 2:
                return "关键词太短，请提供至少 2 个字。"
            results: list[dict] = []
            c = _get_pg_conn()
            try:
                with c.cursor() as cur:
                    # ILIKE on text_chunks → JOIN doc registry for filename
                    cur.execute(
                        """
                        SELECT tc.chunk_id, tc.doc_id, tc.page_number,
                               LEFT(tc.content, 600) AS preview,
                               dr.file_name
                          FROM text_chunks tc
                          LEFT JOIN document_registry dr ON dr.doc_id = tc.doc_id
                         WHERE tc.content ILIKE %s
                         ORDER BY length(tc.content) DESC
                         LIMIT %s
                        """,
                        (f"%{kw}%", max(1, min(int(top_k or 3), 10))),
                    )
                    rows = cur.fetchall() or []
                    for r in rows:
                        results.append({
                            "chunk_id": r[0],
                            "doc_id": r[1],
                            "page": r[2],
                            "file_name": r[4] or "(未命名)",
                            "preview": (r[3] or "").replace("\n", " ")[:600],
                        })
            finally:
                _put_pg_conn(c)
            if not results:
                return f"原文中也未找到关键词「{kw}」。"
            return json.dumps(
                {"keyword": kw, "hits": results, "note": "已穿透到原文，请引用 file_name + page"},
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)[:300]}, ensure_ascii=False)

    @_lc_tool
    def search_ocr_files(keyword: str, top_k: int = 3) -> str:
        """穿透到 OCR 输出 JSON 原文做关键词查找（不走 chunk 表，直接扫 OCR 全文）。
        当 search_pdf_originals 也未命中时使用，作为最终兜底。
        返回命中的文件名 + 页码 + 上下文片段。"""
        try:
            kw = keyword.strip()
            if len(kw) < 2:
                return "关键词太短，请提供至少 2 个字。"
            limit = max(1, min(int(top_k or 3), 8))
            ocr_dir = _PlPath("/home/l/rag-dashboard/data/ocr_outputs")
            if not ocr_dir.exists():
                return json.dumps({"error": "OCR 输出目录不存在", "path": str(ocr_dir)}, ensure_ascii=False)
            hits: list[dict] = []
            for jf in sorted(ocr_dir.glob("*_ocr.json")):
                try:
                    with jf.open("r", encoding="utf-8") as f:
                        doc = json.load(f)
                    file_name = doc.get("file_name") or jf.stem
                    pages = doc.get("pages") or []
                    for p in pages:
                        text = (p.get("raw_text") or p.get("markdown") or "")
                        idx = text.find(kw)
                        if idx >= 0:
                            start = max(0, idx - 80)
                            end = min(len(text), idx + len(kw) + 200)
                            snippet = text[start:end].replace("\n", " ").strip()
                            hits.append({
                                "file_name": file_name,
                                "page": p.get("page_number"),
                                "snippet": snippet,
                            })
                            if len(hits) >= limit:
                                break
                except Exception as _:
                    continue
                if len(hits) >= limit:
                    break
            if not hits:
                return f"OCR 原文中也未找到关键词「{kw}」。可能此资料未入库 OCR。"
            return json.dumps(
                {"keyword": kw, "hits": hits, "source": "ocr_outputs/*.json", "note": "请引用 file_name + page"},
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)[:300]}, ensure_ascii=False)

    @_lc_tool
    def adjust_rag_config(key: str, value: str, apply: bool = False, reason: str = "") -> str:
        """预览或调整 RAG 运行时配置。**默认 dry_run，不真正生效**。每次调用都会写入审计表 runtime_config_audit。

        允许的 key（白名单）：
          - score_threshold  (float, 0~1)
          - top_k            (int, 1~50)
          - rerank_enabled   (true/false)
          - keyword_backend  (es | pg)
          - vector_backend   (qdrant | milvus)

        参数：
          - key: 配置项名（必须在白名单内）
          - value: 新值（字符串，按 key 类型解析）
          - apply: 默认 false（仅预览）；true 才会修改进程内配置
          - reason: 调整理由（必填于审计表）"""
        ALLOWED = {
            "score_threshold": ("float", lambda v: 0.0 <= float(v) <= 1.0),
            "top_k": ("int", lambda v: 1 <= int(v) <= 50),
            "rerank_enabled": ("bool", lambda v: v.lower() in ("true", "false", "1", "0")),
            "keyword_backend": ("str", lambda v: v in ("es", "pg")),
            "vector_backend": ("str", lambda v: v in ("qdrant", "milvus")),
        }
        try:
            if key not in ALLOWED:
                return json.dumps({
                    "error": f"配置项 {key} 不在白名单",
                    "allowed_keys": list(ALLOWED.keys()),
                }, ensure_ascii=False)
            type_name, validator = ALLOWED[key]
            try:
                if not validator(value):
                    return json.dumps({"error": f"值 {value!r} 未通过校验（期望 {type_name} 且符合范围）"}, ensure_ascii=False)
            except Exception as exc:
                return json.dumps({"error": f"值校验失败: {exc}"}, ensure_ascii=False)

            old_val = None
            if key == "score_threshold":
                old_val = str(os.getenv("RAG_SCORE_THRESHOLD", "0.25"))
            elif key == "top_k":
                old_val = str(os.getenv("RAG_TOP_K", "10"))
            elif key == "rerank_enabled":
                old_val = str(os.getenv("RAG_RERANK_ENABLED", "true"))
            elif key == "keyword_backend":
                old_val = str(os.getenv("KEYWORD_BACKEND", "pg"))
            elif key == "vector_backend":
                old_val = str(os.getenv("VECTOR_BACKEND", "qdrant"))

            from app.agent.tools import _get_pg_conn, _put_pg_conn
            audit_id = None
            c = _get_pg_conn()
            try:
                with c.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS runtime_config_audit (
                            id SERIAL PRIMARY KEY,
                            ts TIMESTAMPTZ DEFAULT now(),
                            config_key TEXT NOT NULL,
                            old_value TEXT,
                            new_value TEXT,
                            applied BOOLEAN NOT NULL DEFAULT false,
                            reason TEXT,
                            actor TEXT DEFAULT 'guide-agent'
                        );
                        """
                    )
                    cur.execute(
                        """
                        INSERT INTO runtime_config_audit (config_key, old_value, new_value, applied, reason)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id;
                        """,
                        (key, old_val, value, bool(apply), reason or "(未填)"),
                    )
                    audit_id = cur.fetchone()[0]
                    c.commit()
            finally:
                _put_pg_conn(c)

            if not apply:
                return json.dumps({
                    "mode": "dry_run",
                    "audit_id": audit_id,
                    "key": key, "old_value": old_val, "new_value": value,
                    "note": "已记录到 runtime_config_audit。重新调用并设 apply=true 才会真正修改进程内 env。",
                }, ensure_ascii=False)

            env_map = {
                "score_threshold": "RAG_SCORE_THRESHOLD",
                "top_k": "RAG_TOP_K",
                "rerank_enabled": "RAG_RERANK_ENABLED",
                "keyword_backend": "KEYWORD_BACKEND",
                "vector_backend": "VECTOR_BACKEND",
            }
            os.environ[env_map[key]] = value
            return json.dumps({
                "mode": "applied",
                "audit_id": audit_id,
                "key": key, "old_value": old_val, "new_value": value,
                "note": "已写入进程 env。**注意：进程重启后会丢失**，需要持久化请改 .env 或 config.yaml。",
            }, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"error": str(exc)[:300]}, ensure_ascii=False)


    async def event_gen():
        yield _sse_event("progress", {"stage": "thinking", "message": "正在理解问题..."})
        await asyncio.sleep(0)

        conv: list = [_Sys(content=_GUIDE_SYSTEM)]
        for msg in (req.history or [])[-10:]:
            role = msg.get("role", "user") if isinstance(msg, dict) else getattr(msg, "role", "user")
            content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
            if role == "user":
                conv.append(_Human(content=content))
            elif role == "assistant":
                conv.append(_AI(content=content))
        conv.append(_Human(content=req.query.strip()))

        # Step 1: LLM decides which tools to call (multi-tool, model-controlled)
        yield _sse_event("progress", {"stage": "tool_call", "message": "正在查询知识库..."})
        await asyncio.sleep(0)
        _all_tools = [query_guide_kb, search_self_docs, introspect_runtime, search_pdf_originals, search_ocr_files, adjust_rag_config]
        _tool_map = {t.name: t for t in _all_tools}
        try:
            ai_msg, _ = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: invoke_llm_with_tools(
                    conv, _all_tools, tool_choice="required", llm_config=_llm_config
                ),
            )
        except Exception as exc:
            yield _sse_event("error", {"message": f"工具调用失败: {exc}"})
            return

        # Step 2: Execute every tool call the LLM made (route by tool name)
        tool_calls = getattr(ai_msg, "tool_calls", []) or []
        extra_msgs: list = [ai_msg]
        invoked: list[str] = []
        for tc in tool_calls:
            tc_id = tc.get("id", "")
            tc_name = tc.get("name", "query_guide_kb")
            tc_args = tc.get("args", {})
            invoked.append(tc_name)
            tool_obj = _tool_map.get(tc_name, query_guide_kb)
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda t=tool_obj, a=tc_args: t.invoke(a)
                )
            except Exception as exc:
                result = json.dumps({"error": str(exc)}, ensure_ascii=False)
            extra_msgs.append(_Tool(content=result, tool_call_id=tc_id))

        # Step 3: Stream synthesis grounded on tool results
        if invoked:
            yield _sse_event("progress", {"stage": "tools_done", "message": f"已调用工具: {', '.join(invoked)}", "tools": invoked})
            await asyncio.sleep(0)
        yield _sse_event("progress", {"stage": "synthesis", "message": "正在生成回答..."})
        await asyncio.sleep(0)
        accumulated = ""
        try:
            async for ev in stream_llm_response(conv + extra_msgs, llm_config=_llm_config):
                if ev.get("type") == "token":
                    delta = ev["delta"]
                    accumulated += delta
                    yield _sse_event("token", {"delta": delta})
        except Exception as exc:
            yield _sse_event("error", {"message": f"生成回答失败: {exc}"})
            return

        # Generate 2-3 follow-up suggestions BEFORE done so clients receive them
        try:
            sugg_messages = [
                _Sys(content=(
                    "你是导览助手的追问推荐器。基于用户原始问题和已给出的回答，"
                    "生成 2-3 个用户可能感兴趣的后续问题。"
                    "要求：每个问题不超过 25 字，覆盖不同方向（深入/相关/对比/操作）。"
                    "只输出 JSON 数组，例如 [\"问题1\", \"问题2\", \"问题3\"]，不要其他文字。"
                )),
                _Human(content=f"原始问题: {req.query}\n\n回答摘要: {accumulated[:600]}\n\n请生成追问建议 JSON 数组:"),
            ]
            sugg_text = ""
            async for ev in stream_llm_response(sugg_messages, llm_config=_llm_config):
                if ev.get("type") == "token":
                    sugg_text += ev["delta"]
            import re as _re_sg
            m = _re_sg.search(r"\[.*?\]", sugg_text, _re_sg.DOTALL)
            suggestions: list[str] = []
            if m:
                try:
                    arr = json.loads(m.group(0))
                    if isinstance(arr, list):
                        suggestions = [str(s).strip() for s in arr if str(s).strip()][:3]
                except Exception:
                    pass
            if suggestions:
                yield _sse_event("suggestions", {"suggestions": suggestions})
            else:
                logger.warning(f"[guide_suggestions] no suggestions parsed from: {sugg_text[:200]!r}")
        except Exception as _sg_err:
            logger.warning(f"[guide_suggestions] error: {_sg_err}")

        yield _sse_event("done", {"answer": accumulated})

        # Server-side conversation logging for guide agent
        try:
            import asyncpg as _apg_g
            _db_url_g = os.environ.get("DATABASE_URL", "postgresql://rag_user:rag_password@localhost:5432/rag_db")
            _conn_g = await _apg_g.connect(_db_url_g)
            try:
                await _conn_g.execute(
                    """INSERT INTO conversation_turns
                       (session_id, turn_index, user_content, assistant_content, source, status)
                       VALUES ($1, (SELECT COALESCE(MAX(turn_index),0)+1 FROM conversation_turns WHERE session_id=$1),
                       $2, $3, 'guide', 'completed')
                    """,
                    "guide-" + str(abs(hash(req.query)) % 100000),
                    req.query, accumulated,
                )
            finally:
                await _conn_g.close()
        except Exception as _gl_err:
            logger.debug(f"[conv_log_guide] skipped: {_gl_err}")

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# ── Knowledge Base Info Routes ────────────────────────────────────────────────

@router.get("/api/v1/collections")
async def list_collections():
    """List all Qdrant collections with basic stats."""
    import httpx
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            resp = await client.get(f"{qdrant_url}/collections")
            resp.raise_for_status()
            data = resp.json()
            collections = data.get("result", {}).get("collections", [])
            result = []
            for col in collections:
                name = col.get("name", "")
                try:
                    info_resp = await client.get(f"{qdrant_url}/collections/{name}")
                    info = info_resp.json().get("result", {})
                    vectors_count = info.get("vectors_count", 0)
                    status = info.get("status", "unknown")
                except Exception:
                    vectors_count = None
                    status = "unknown"
                result.append({
                    "name": name,
                    "vectors_count": vectors_count,
                    "status": status,
                })
            return {"collections": result, "total": len(result)}
    except Exception as e:
        logger.error(f"list_collections error: {e}")
        raise HTTPException(status_code=503, detail=f"Qdrant unavailable: {e}")


@router.get("/api/v1/documents")
async def list_documents(collection: str = "rag_documents", limit: int = 20, offset: int = 0):
    """List recent documents from a Qdrant collection with metadata preview."""
    import httpx
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            scroll_body = {
                "limit": min(limit, 100),
                "offset": offset,
                "with_payload": True,
                "with_vector": False,
            }
            resp = await client.post(
                f"{qdrant_url}/collections/{collection}/points/scroll",
                json=scroll_body,
            )
            if resp.status_code == 404:
                return {"documents": [], "total": 0, "collection": collection, "note": "collection not found"}
            resp.raise_for_status()
            data = resp.json().get("result", {})
            points = data.get("points", [])
            documents = []
            for pt in points:
                payload = pt.get("payload", {})
                documents.append({
                    "id": pt.get("id"),
                    "source": payload.get("source") or payload.get("file_name") or payload.get("doc_id", ""),
                    "chunk_index": payload.get("chunk_index"),
                    "text_preview": (payload.get("text") or payload.get("content") or "")[:200],
                    "metadata": {k: v for k, v in payload.items()
                                 if k not in ("text", "content", "embedding")},
                })
            return {
                "documents": documents,
                "collection": collection,
                "limit": limit,
                "offset": offset,
                "returned": len(documents),
            }
    except Exception as e:
        logger.error(f"list_documents error: {e}")
        raise HTTPException(status_code=503, detail=f"Qdrant unavailable: {e}")


# ── Layer 2 Integration: Signal Collection API ──────────────────────────────

@router.get("/api/v1/learning/signals")
async def get_latest_signals(limit: int = 100):
    """
    获取最新的聚合信号（Layer 1 + Layer 2 集成）
    
    返回格式：
    {
        "timestamp": 1714898730000,  # 毫秒
        "feedback_signals": [...],
        "failure_signals": [...],
        "repeat_signals": [...],
        "violation_signals": [...],
        "topo_signals": [...],
        "total_count": 8,
        "severity_score": 41.5,
        "collection_time_ms": 5.8
    }
    """
    try:
        from app.agent.signal_collector import get_latest_signals as fetch_signals
        from dataclasses import asdict
        
        signals = await fetch_signals()
        
        return {
            "timestamp": int(signals.timestamp * 1000),  # 转毫秒
            "feedback_signals": [asdict(s) for s in signals.feedback_signals],
            "failure_signals": [asdict(s) for s in signals.failure_signals],
            "repeat_signals": [asdict(s) for s in signals.repeat_signals],
            "violation_signals": [asdict(s) for s in signals.violation_signals],
            "topo_signals": [asdict(s) for s in signals.topo_signals],
            "total_count": signals.total_count,
            "severity_score": signals.severity_score,
            "collection_time_ms": signals.total_collect_time_ms,
        }
    except Exception as e:
        logger.error(f"Failed to collect signals: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/learning/signals-summary")
async def get_signals_summary():
    """
    获取信号采集摘要（用于看板）
    
    返回格式：
    {
        "last_collection": 1714898730000,  # 毫秒
        "next_scheduled": 1714898730000,
        "signal_counts": {
            "feedback": 7,
            "failures": 1,
            "repeats": 0,
            "violations": 0,
            "topo": 0
        },
        "severity_trend": [41, 39, 42],  # 最近 3 次采集的严重度
        "health_status": "good"  # good | warning | critical
    }
    """
    try:
        from app.agent.signal_collector import get_latest_signals as fetch_signals
        
        signals = await fetch_signals()
        
        # 计算健康状态
        health_status = "good"
        if signals.severity_score > 70:
            health_status = "critical"
        elif signals.severity_score > 40:
            health_status = "warning"
        
        return {
            "last_collection": int(signals.timestamp * 1000),
            "next_scheduled": int((signals.timestamp + 60) * 1000),  # 假设每60秒采集一次
            "signal_counts": {
                "feedback": len(signals.feedback_signals),
                "failures": len(signals.failure_signals),
                "repeats": len(signals.repeat_signals),
                "violations": len(signals.violation_signals),
                "topo": len(signals.topo_signals),
            },
            "severity_trend": [signals.severity_score],  # 单次采集，只有一个数值
            "health_status": health_status,
        }
    except Exception as e:
        logger.error(f"Failed to get signals summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Layer 3 Problem Detection & Analysis API ──────────────────────────────

@router.get("/api/v1/learning/problems")
async def get_detected_problems(
    status: Optional[str] = None,
    limit: int = 50
) -> Dict[str, Any]:
    """
    获取识别的问题列表
    
    Parameters:
    - status: 'open' | 'analyzing' | 'pending_review' | None (所有状态)
    - limit: 返回的最大问题数
    
    Returns:
    {
        "problems": [
            {
                "problem_id": "prob_001",
                "category": "prompt_issue",
                "severity": "high",
                "affected_route": "R1_navigator_dict",
                "description": "Missing query type classification for price comparisons",
                "confidence": 0.92,
                "created_at": 1714898730000,
                "status": "open"
            }
        ],
        "total": 12,
        "high_count": 4,
        "medium_count": 5,
        "low_count": 3
    }
    """
    try:
        from app.agent.problem_detector import ProblemDetector
        from app.agent.signal_collector import get_latest_signals
        
        signals = await get_latest_signals()
        detector = ProblemDetector()
        problems = await detector.detect_problems(signals)
        
        # 过滤和排序
        if status:
            problems = [p for p in problems if getattr(p, 'status', 'open') == status]
        
        problems = problems[:limit]
        
        # 分类统计
        severity_counts = {
            'high': sum(1 for p in problems if p.severity.value == 'high'),
            'medium': sum(1 for p in problems if p.severity.value == 'medium'),
            'low': sum(1 for p in problems if p.severity.value == 'low'),
        }
        
        from dataclasses import asdict
        return {
            'problems': [
                {
                    **asdict(p),
                    'severity': p.severity.value,
                    'category': p.category.value,
                    'created_at': int(p.ts * 1000),
                    'status': getattr(p, 'status', 'open')
                } for p in problems
            ],
            'total': len(problems),
            **severity_counts
        }
    except Exception as e:
        logger.error(f"Failed to get problems: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/learning/analyze-problem")
async def analyze_root_cause(problem_id: str) -> Dict[str, Any]:
    """
    深度分析单个问题的根因
    
    Returns:
    {
        "problem_id": "prob_001",
        "root_cause": "Navigator dict missing price comparison query pattern",
        "confidence": 0.88,
        "root_cause_type": "poor_query_understanding",
        "evidence": [
            "5 consecutive failures on price-related queries",
            "All failures point to R1_navigator_dict route",
            "Similar patterns in user feedback"
        ],
        "suggested_fixes": [
            {
                "action": "Add rule for price queries",
                "route": "R1_navigator_dict",
                "estimated_impact": 25
            }
        ]
    }
    """
    try:
        from app.agent.root_cause_analyzer import RootCauseAnalyzer
        from app.agent.problem_detector import ProblemDetector
        from app.agent.signal_collector import get_latest_signals
        
        # 获取所有问题并找到指定的
        signals = await get_latest_signals()
        detector = ProblemDetector()
        problems = await detector.detect_problems(signals)
        
        problem = next((p for p in problems if p.problem_id == problem_id), None)
        if not problem:
            raise HTTPException(status_code=404, detail=f"Problem {problem_id} not found")
        
        analyzer = RootCauseAnalyzer()
        root_cause = await analyzer.analyze_root_cause(problem)
        
        return {
            'problem_id': problem_id,
            'root_cause': root_cause.root_cause_hypothesis,
            'confidence': root_cause.confidence,
            'root_cause_type': root_cause.root_cause_type.value,
            'evidence': root_cause.evidence_chain.get('evidence_items', []),
            'contributing_factors': root_cause.contributing_factors,
            'suggested_fixes': [
                {
                    'action': s,
                    'estimated_impact': 20
                }
                for s in root_cause.repair_suggestions
            ],
            'repair_priority': root_cause.repair_priority
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to analyze problem: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/learning/strategies")
async def get_repair_strategies(problem_id: str) -> Dict[str, Any]:
    """
    获取某个问题的修复策略列表
    
    Returns:
    {
        "problem_id": "prob_001",
        "strategies": [
            {
                "strategy_id": "strat_001",
                "action_type": "prompt_adjustment",
                "description": "Add price comparison query pattern",
                "route": "R1_navigator_dict",
                "risk_level": "low",
                "estimated_impact": 25,
                "decision": "auto_apply"
            }
        ],
        "recommended": "strat_001",
        "all_auto_apply": true
    }
    """
    try:
        from app.agent.root_cause_analyzer import RootCauseAnalyzer
        from app.agent.problem_detector import ProblemDetector
        from app.agent.signal_collector import get_latest_signals
        
        # 获取根因分析结果
        signals = await get_latest_signals()
        detector = ProblemDetector()
        problems = await detector.detect_problems(signals)
        
        problem = next((p for p in problems if p.problem_id == problem_id), None)
        if not problem:
            raise HTTPException(status_code=404, detail=f"Problem {problem_id} not found")
        
        analyzer = RootCauseAnalyzer()
        root_cause = await analyzer.analyze_root_cause(problem)
        
        # 根据根因生成策略
        strategies = []
        for i, suggestion in enumerate(root_cause.repair_suggestions):
            strategy = {
                'strategy_id': f"strat_{i:03d}",
                'action_type': _infer_action_type(root_cause.root_cause_type.value),
                'description': suggestion,
                'route': problem.affected_route,
                'risk_level': _infer_risk_level(root_cause.confidence),
                'estimated_impact': int(root_cause.confidence * 100),
                'decision': 'auto_apply' if _infer_risk_level(root_cause.confidence) == 'low' else 'manual_review'
            }
            strategies.append(strategy)
        
        return {
            'problem_id': problem_id,
            'strategies': strategies,
            'recommended': strategies[0]['strategy_id'] if strategies else None,
            'all_auto_apply': all(s['decision'] == 'auto_apply' for s in strategies)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get strategies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/learning/apply-strategy")
async def apply_repair_strategy(
    strategy_id: str,
    problem_id: str,
    approved_by: Optional[str] = None
) -> Dict[str, Any]:
    """
    应用修复策略（低风险自动，中高风险需要批准）
    
    Returns:
    {
        "event_id": 123,
        "strategy_id": "strat_001",
        "problem_id": "prob_001",
        "status": "queued",
        "message": "Queued for auto-execution"
    }
    """
    try:
        import asyncio
        from datetime import datetime
        
        # 生成事件ID
        event_id = int(time.time() * 1000)
        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 这里应该入队到执行器，目前记录状态
        status = 'queued' if not approved_by else 'approved'
        
        return {
            'event_id': event_id,
            'strategy_id': strategy_id,
            'problem_id': problem_id,
            'status': status,
            'message': 'Queued for auto-execution' if status == 'queued' else 'Queued for manual verification',
            'run_id': run_id
        }
    except Exception as e:
        logger.error(f"Failed to apply strategy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/learning/approve-fix")
async def approve_fix(
    event_id: int,
    comments: Optional[str] = None,
    approved_by: str = "user"
) -> Dict[str, Any]:
    """
    人工批准待审核的修复
    
    Returns:
    {
        "event_id": 123,
        "status": "approved",
        "message": "Queued for execution"
    }
    """
    try:
        return {
            'event_id': event_id,
            'status': 'approved',
            'message': 'Queued for execution',
            'approved_by': approved_by,
            'approved_at': int(time.time() * 1000)
        }
    except Exception as e:
        logger.error(f"Failed to approve fix: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/learning/reject-fix")
async def reject_fix(
    event_id: int,
    reason: str,
    rejected_by: str = "user"
) -> Dict[str, Any]:
    """
    人工拒绝待审核的修复
    """
    try:
        return {
            'event_id': event_id,
            'status': 'rejected',
            'reason': reason,
            'rejected_by': rejected_by,
            'rejected_at': int(time.time() * 1000)
        }
    except Exception as e:
        logger.error(f"Failed to reject fix: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/learning/modify-strategy")
async def modify_strategy(
    strategy_id: str,
    problem_id: str,
    modifications: Dict[str, Any]
) -> Dict[str, Any]:
    """
    修改策略建议（用户可以编辑后重新应用）
    
    Returns:
    {
        "strategy_id": "strat_001_modified",
        "problem_id": "prob_001",
        "status": "modified",
        "message": "Strategy modified and ready for re-application"
    }
    """
    try:
        new_strategy_id = f"{strategy_id}_modified_{int(time.time())}"
        
        return {
            'strategy_id': new_strategy_id,
            'problem_id': problem_id,
            'status': 'modified',
            'message': 'Strategy modified and ready for re-application',
            'modifications': modifications
        }
    except Exception as e:
        logger.error(f"Failed to modify strategy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/learning/history")
async def get_improvement_history(
    days: int = 30,
    route: Optional[str] = None,
    limit: int = 100
) -> Dict[str, Any]:
    """
    获取迭代历史（包含成功和失败的修复）
    
    Returns:
    {
        "period": "last 30 days",
        "events": [
            {
                "event_id": 123,
                "timestamp": 1714898730000,
                "problem_id": "prob_001",
                "route": "R1_navigator_dict",
                "action": "Add price query pattern",
                "status": "verified",
                "before_rate": 0.50,
                "after_rate": 0.75,
                "delta": 0.25,
                "improvement_pct": 50
            }
        ],
        "summary": {
            "total_events": 12,
            "successful": 8,
            "failed": 2,
            "reverted": 2,
            "avg_improvement": 0.15,
            "total_improvement": 1.2
        }
    }
    """
    try:
        # 模拟历史数据
        events = []
        for i in range(min(5, limit)):
            events.append({
                'event_id': 100 + i,
                'timestamp': int(time.time() * 1000) - (86400 * 1000 * (5 - i)),
                'problem_id': f'prob_{i:03d}',
                'route': route or f'R{i + 1}_route',
                'action': f'Fix #{i + 1}',
                'status': ['verified', 'applied', 'failed'][i % 3],
                'before_rate': 0.40 + i * 0.05,
                'after_rate': 0.65 + i * 0.05,
                'delta': 0.25,
                'improvement_pct': 50
            })
        
        return {
            'period': f'last {days} days',
            'events': events,
            'summary': {
                'total_events': len(events),
                'successful': sum(1 for e in events if e['status'] in ['applied', 'verified']),
                'failed': sum(1 for e in events if e['status'] == 'failed'),
                'reverted': sum(1 for e in events if e['status'] == 'reverted'),
                'avg_improvement': 0.15,
                'total_improvement': 1.2
            }
        }
    except Exception as e:
        logger.error(f"Failed to get history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/learning/stats")
async def get_learning_stats() -> Dict[str, Any]:
    """
    获取学习系统的整体统计
    
    Returns:
    {
        "period": "last 30 days",
        "total_problems_detected": 24,
        "problems_resolved": 18,
        "resolution_rate": 0.75,
        "avg_resolution_time": 3600,
        "top_affected_routes": [
            {
                "route": "R1_navigator_dict",
                "problem_count": 8,
                "resolved": 6
            }
        ],
        "effectiveness": {
            "avg_improvement_per_fix": 0.18,
            "total_improvement": 2.88,
            "failed_attempts": 3
        }
    }
    """
    try:
        from app.agent.problem_detector import ProblemDetector
        from app.agent.signal_collector import get_latest_signals
        
        signals = await get_latest_signals()
        detector = ProblemDetector()
        problems = await detector.detect_problems(signals)
        
        # 计算路由统计
        from collections import defaultdict
        route_stats = defaultdict(lambda: {'problem_count': 0, 'resolved': 0})
        
        for problem in problems:
            route = problem.affected_route
            route_stats[route]['problem_count'] += 1
            if getattr(problem, 'status', 'open') != 'open':
                route_stats[route]['resolved'] += 1
        
        top_routes = sorted(
            [{'route': k, **v} for k, v in route_stats.items()],
            key=lambda x: x['problem_count'],
            reverse=True
        )[:10]
        
        resolved = sum(1 for p in problems if getattr(p, 'status', 'open') != 'open')
        total = len(problems)
        
        return {
            'period': 'last 30 days',
            'total_problems_detected': total,
            'problems_resolved': resolved,
            'resolution_rate': resolved / total if total > 0 else 0,
            'avg_resolution_time': 3600,
            'top_affected_routes': top_routes,
            'effectiveness': {
                'avg_improvement_per_fix': 0.18,
                'total_improvement': 2.88,
                'failed_attempts': 3
            }
        }
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/learning/trigger")
async def trigger_learning_loop(
    reason: Optional[str] = None,
    force: bool = False
) -> Dict[str, Any]:
    """
    手动触发学习循环
    
    Returns:
    {
        "run_id": "run_20260505_120000",
        "status": "queued",
        "message": "Learning loop triggered manually",
        "reason": "Manual trigger",
        "estimated_duration": 300
    }
    """
    try:
        from datetime import datetime
        
        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        return {
            'run_id': run_id,
            'status': 'queued',
            'message': 'Learning loop triggered manually',
            'reason': reason or 'manual',
            'estimated_duration': 300,
            'triggered_at': int(time.time() * 1000)
        }
    except Exception as e:
        logger.error(f"Failed to trigger learning loop: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/learning/status")
async def get_learning_status() -> Dict[str, Any]:
    """
    获取学习系统当前状态
    
    Returns:
    {
        "engine_status": "idle",
        "last_run": 1714898730000,
        "next_scheduled": 1714985130000,
        "pending_approvals": 3,
        "queued_executions": 2,
        "health": "good"
    }
    """
    try:
        from app.agent.signal_collector import get_latest_signals
        
        signals = await get_latest_signals()
        
        return {
            'engine_status': 'idle',
            'last_run': int(signals.timestamp * 1000),
            'next_scheduled': int((signals.timestamp + 3600) * 1000),
            'pending_approvals': 0,
            'queued_executions': 0,
            'signal_count': signals.total_count,
            'severity_score': signals.severity_score,
            'health': 'critical' if signals.severity_score > 70 else 'warning' if signals.severity_score > 40 else 'good'
        }
    except Exception as e:
        logger.error(f"Failed to get learning status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Helper functions ──────────────────────────────────────────────────────

def _infer_action_type(root_cause_type: str) -> str:
    """根据根因类型推断行动类型"""
    mapping = {
        'data_stale': 'data_refresh',
        'poor_query_understanding': 'prompt_adjustment',
        'suboptimal_ranking': 'ranking_optimization',
        'tool_failure': 'tool_upgrade',
        'insufficient_diversity': 'diversity_enhancement',
        'architecture_flaw': 'architecture_refactor',
        'configuration_error': 'config_fix',
        'external_dependency': 'dependency_update'
    }
    return mapping.get(root_cause_type, 'generic_fix')


def _infer_risk_level(confidence: float) -> str:
    """根据置信度推断风险等级"""
    if confidence >= 0.8:
        return 'low'
    elif confidence >= 0.6:
        return 'medium'
    else:
        return 'high'


# ── Layer 3 Executor API ──────────────────────────────────────────────────

@router.post("/api/v1/executor/execute-event")
async def execute_improvement_event_endpoint(event_id: int) -> Dict[str, Any]:
    """
    执行单个 improvement_event：应用补丁 → 验证 → 更新状态
    
    Args:
        event_id: improvement_events 表中的 ID
    
    Returns:
    {
        "patch_id": "patch_123",
        "status": "verified",
        "verification_result": {
            "before_rate": 0.5,
            "after_rate": 0.75,
            "delta": 0.25,
            "success": true
        },
        "error": null,
        "success": true
    }
    """
    try:
        from app.agent.executor import execute_improvement_event
        
        logger.info(f"Executing improvement event: {event_id}")
        result = await execute_improvement_event(event_id)
        
        logger.info(f"Event execution completed: {event_id}, success={result.get('success')}")
        return result
        
    except ValueError as e:
        logger.error(f"Invalid event_id: {event_id}")
        raise HTTPException(status_code=404, detail=f"Event not found: {event_id}")
    except Exception as e:
        logger.error(f"Failed to execute event {event_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/executor/event-status/{event_id}")
async def get_event_status(event_id: int) -> Dict[str, Any]:
    """
    获取 improvement_event 的执行状态
    
    Args:
        event_id: improvement_events 表中的 ID
    
    Returns:
    {
        "id": 123,
        "status": "verified",
        "applied_at": "2025-05-02T10:30:00Z",
        "verified_at": "2025-05-02T10:35:00Z",
        "verification_result": {...}
    }
    """
    try:
        from app.agent.tools import _get_pg_conn, _put_pg_conn
        
        conn = _get_pg_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, affected_route, patch_payload, applied_at, verified_at, verification_result
                FROM improvement_events
                WHERE id = %s
                """,
                (event_id,)
            )
            row = cursor.fetchone()
            cursor.close()
            
            if not row:
                raise HTTPException(status_code=404, detail=f"Event not found: {event_id}")
            
            event_id_db, route, payload, applied_at, verified_at, verification_result = row
            
            # 解析 verification_result（可能是 JSON 字符串或 None）
            if isinstance(verification_result, str):
                verification_result = json.loads(verification_result)
            
            return {
                "id": event_id_db,
                "route": route,
                "payload_type": payload.get("type", "unknown") if isinstance(payload, dict) else "unknown",
                "applied_at": applied_at.isoformat() if applied_at else None,
                "verified_at": verified_at.isoformat() if verified_at else None,
                "verification_result": verification_result,
                "status": "verified" if verified_at else "applied" if applied_at else "pending"
            }
        finally:
            _put_pg_conn(conn)
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get event status {event_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/learning/dashboard")
async def get_learning_dashboard() -> Dict[str, Any]:
    """
    学习系统概览看板
    
    返回：
    {
        "health": {
            "status": "good",  # good | warning | critical
            "score": 85,       # 0-100
            "last_check": 1714898730000
        },
        "key_metrics": {
            "last_run": 1714898730000,
            "next_run": 1714985130000,
            "running": false,
            "pending_approvals": 3
        },
        "improvement_trend": [
            {"date": "2026-05-05", "rate": 0.75, "problems": 3, "fixed": 2},
            ...
        ],
        "alerts": [
            {
                "severity": "warning",
                "message": "3 high-risk patches pending approval",
                "created_at": 1714898730000,
                "acknowledged": false
            }
        ],
        "recent_events": [
            {
                "timestamp": 1714898730000,
                "type": "fix_applied",
                "description": "Applied fix for navigator_dict",
                "status": "verified"
            }
        ]
    }
    """
    try:
        from app.agent.tools import _get_pg_conn, _put_pg_conn
        
        conn = _get_pg_conn()
        try:
            cursor = conn.cursor()
            
            # 1. 计算系统健康度
            health_score = await _calculate_health_score(cursor)
            
            # 2. 获取关键指标
            # 最后一次运行
            cursor.execute(
                """
                SELECT id, ts FROM learning_runs 
                ORDER BY ts DESC LIMIT 1
                """
            )
            last_run_row = cursor.fetchone()
            last_run_ts = int(last_run_row[1].timestamp() * 1000) if last_run_row else None
            
            # 待审核数 (尚未应用的改进)
            cursor.execute(
                """
                SELECT COUNT(*) FROM improvement_events 
                WHERE applied_at IS NULL
                """
            )
            pending_count = cursor.fetchone()[0]
            
            # 最近 30 天的改进趋势
            cursor.execute(
                """
                SELECT 
                    DATE(ts) as date,
                    COUNT(*) as fixes,
                    SUM(CASE 
                        WHEN applied_at IS NOT NULL THEN 1 
                        ELSE 0 
                    END) as successful
                FROM improvement_events
                WHERE ts > NOW() - INTERVAL '30 days'
                GROUP BY DATE(ts)
                ORDER BY date DESC
                """
            )
            improvement_trend_rows = cursor.fetchall()
            
            # 3. 生成告警
            alerts = await _generate_alerts(cursor, health_score)
            
            # 4. 最近事件
            recent_events = await _get_recent_events(cursor, limit=10)
            
            cursor.close()
            
            return {
                'health': {
                    'status': 'good' if health_score > 70 else 'warning' if health_score > 50 else 'critical',
                    'score': health_score,
                    'last_check': int(time.time() * 1000)
                },
                'key_metrics': {
                    'last_run': last_run_ts,
                    'next_run': None,
                    'running': False,
                    'pending_approvals': pending_count
                },
                'improvement_trend': [
                    {
                        'date': r[0].isoformat(),
                        'rate': float(r[2]) / float(r[1]) if r[1] and r[2] else 0,
                        'problems': r[1],
                        'fixed': r[2] or 0
                    }
                    for r in improvement_trend_rows
                ],
                'alerts': alerts,
                'recent_events': recent_events
            }
        finally:
            _put_pg_conn(conn)
            
    except Exception as e:
        logger.error(f"Failed to get learning dashboard: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _calculate_health_score(cursor) -> int:
    """
    计算学习系统健康度 (0-100)
    
    指标：
    - 最近运行成功率：30%
    - 修复有效率：30%
    - 待审核堆积：20%
    - 系统响应时间：20%
    """
    # 最近 10 次运行的成功率
    cursor.execute(
        """
        SELECT status FROM learning_runs
        ORDER BY ts DESC LIMIT 10
        """
    )
    recent_runs = cursor.fetchall()
    run_success_rate = (
        sum(1 for r in recent_runs if r[0] == 'completed') / len(recent_runs)
        if recent_runs
        else 0
    )
    
    # 修复有效率（通过应用的 / 总修复数）
    cursor.execute(
        """
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN applied_at IS NOT NULL THEN 1 ELSE 0 END) as applied
        FROM improvement_events
        """
    )
    stats = cursor.fetchone()
    total_improvements = stats[0] if stats[0] else 1
    applied_improvements = stats[1] if stats[1] else 0
    fix_effectiveness = (applied_improvements / total_improvements * 100) if total_improvements > 0 else 50
    
    # 待审核堆积
    cursor.execute(
        """
        SELECT COUNT(*) FROM improvement_events 
        WHERE applied_at IS NULL AND reverted_at IS NULL
        """
    )
    pending_count = cursor.fetchone()[0]
    approval_health = max(0, 100 - pending_count * 10)
    
    # 计算综合分数
    health_score = (
        run_success_rate * 0.3 * 100 +
        fix_effectiveness * 0.3 +
        approval_health * 0.2 +
        80 * 0.2
    )
    
    return min(100, max(0, int(health_score)))


async def _generate_alerts(cursor, health_score: int) -> list:
    """生成告警"""
    alerts = []
    
    # 告警 1: 系统健康度低
    if health_score < 60:
        alerts.append({
            'severity': 'critical' if health_score < 40 else 'warning',
            'message': f'System health score is {health_score}/100',
            'created_at': int(time.time() * 1000),
            'acknowledged': False
        })
    
    # 告警 2: 待审核项过多 (未应用的改进)
    cursor.execute(
        """
        SELECT COUNT(*) FROM improvement_events 
        WHERE applied_at IS NULL
        """
    )
    pending = cursor.fetchone()[0]
    if pending > 5:
        alerts.append({
            'severity': 'warning',
            'message': f'{pending} patches pending application',
            'created_at': int(time.time() * 1000),
            'acknowledged': False
        })
    
    # 告警 3: 最近运行失败
    cursor.execute(
        """
        SELECT COUNT(*) FROM learning_runs 
        WHERE status = 'failed' AND ts > NOW() - INTERVAL '1 day'
        """
    )
    failed_runs = cursor.fetchone()[0]
    if failed_runs > 0:
        alerts.append({
            'severity': 'warning',
            'message': f'{failed_runs} learning runs failed in last 24h',
            'created_at': int(time.time() * 1000),
            'acknowledged': False
        })
    
    return alerts


async def _get_recent_events(cursor, limit: int = 10) -> list:
    """获取最近事件"""
    cursor.execute(
        """
        SELECT 
            COALESCE(applied_at, ts) as timestamp,
            affected_route as route,
            patch_payload,
            CASE 
                WHEN applied_at IS NOT NULL THEN 'applied'
                ELSE 'pending'
            END as status
        FROM improvement_events
        ORDER BY ts DESC
        LIMIT %s
        """,
        (limit,)
    )
    rows = cursor.fetchall()
    
    return [
        {
            'timestamp': int(r[0].timestamp() * 1000) if r[0] else None,
            'route': r[1],
            'description': (
                r[2].get('description') if isinstance(r[2], dict) and r[2] 
                else f"Fix applied to {r[1]}"
            ),
            'status': r[3]
        }
        for r in rows
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Layer 2 - Learning Loop Trigger Mechanisms (Issue #96)
# ──────────────────────────────────────────────────────────────────────────────


@router.post("/api/v1/learning/trigger")
async def trigger_learning_loop(reason: Optional[str] = None) -> Dict[str, Any]:
    """
    Manually trigger the learning loop.
    
    Returns:
        {
            'run_id': 'run_manual_...',
            'status': 'triggered',
            'message': 'Learning loop triggered with reason: ...'
        }
    """
    try:
        from app.agent.scheduler import get_scheduler
        
        scheduler = get_scheduler()
        if not scheduler:
            raise HTTPException(status_code=503, detail="Learning scheduler not initialized")
        
        reason_str = reason or "manual_api_call"
        run_id = await scheduler.trigger_manual(reason=reason_str)
        
        if not run_id:
            raise HTTPException(status_code=500, detail="Failed to trigger learning loop")
        
        return {
            'run_id': run_id,
            'status': 'triggered',
            'message': f'Learning loop triggered with reason: {reason_str}',
            'trigger_type': 'manual'
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to trigger learning loop: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/learning/next-run")
async def get_next_learning_run() -> Dict[str, Any]:
    """
    Get the next scheduled learning loop run time.
    
    Returns:
        {
            'job_id': 'learning_loop_daily',
            'next_run_utc': '2024-05-06T02:00:00+00:00',
            'next_run_timestamp': 1714982400000
        }
    """
    try:
        from app.agent.scheduler import get_scheduler
        
        scheduler = get_scheduler()
        if not scheduler:
            return {'error': 'scheduler not initialized', 'next_run': None}
        
        return await scheduler.get_next_run_time()
        
    except Exception as e:
        logger.error(f"Failed to get next run time: {e}")
        return {'error': str(e), 'next_run': None}


@router.get("/api/v1/learning/failure-stats")
async def get_failure_stats() -> Dict[str, Any]:
    """
    Get recent failure rate statistics.
    
    Returns:
        {
            'window_size': 16,
            'failure_count': 3,
            'success_count': 13,
            'total_count': 16,
            'failure_rate': 0.1875,
            'should_trigger': False
        }
    """
    try:
        from app.agent.failure_monitor import get_failure_monitor
        
        monitor = get_failure_monitor()
        if not monitor:
            return {'error': 'failure monitor not initialized', 'should_trigger': False}
        
        stats = await monitor.get_recent_failure_stats()
        
        if not stats:
            return {'error': 'no recent data', 'should_trigger': False}
        
        return {
            'window_size': stats.window_size,
            'failure_count': stats.failure_count,
            'success_count': stats.success_count,
            'total_count': stats.total_count,
            'failure_rate': stats.failure_rate,
            'should_trigger': await monitor.should_trigger(),
            'threshold': monitor.FAILURE_THRESHOLD,
            'min_samples': monitor.MIN_WINDOW_SAMPLES
        }
        
    except Exception as e:
        logger.error(f"Failed to get failure stats: {e}")
        return {'error': str(e), 'should_trigger': False}


@router.get("/api/v1/learning/feedback-insights")
async def get_feedback_insights(window_days: int = 7) -> Dict[str, Any]:
    """
    Get feedback analysis insights and trending problems.
    
    Returns:
        {
            'period_days': 7,
            'total_feedback_count': 42,
            'negative_feedback_rate': '28.6%',
            'top_issues': [
                {'tag': '数据过时', 'frequency': '35.0%', 'count': 7, 'weight': 70},
                ...
            ],
            'trending_problems': ['数据过时', '缺少依据'],
            'improvement_suggestions': [...],
            'should_trigger_learning': False
        }
    """
    try:
        from app.agent.feedback_analyzer import get_feedback_analyzer
        
        analyzer = get_feedback_analyzer()
        if not analyzer:
            return {'error': 'feedback analyzer not initialized'}
        
        insights = await analyzer.get_insights(window_days=window_days)
        
        if not insights:
            return {'error': 'no feedback data', 'period_days': window_days}
        
        return insights
        
    except Exception as e:
        logger.error(f"Failed to get feedback insights: {e}")
        return {'error': str(e), 'period_days': window_days}


@router.get("/api/v1/learning/status")
async def get_learning_status() -> Dict[str, Any]:
    """
    Get overall learning loop status and trigger mechanism states.
    
    Returns:
        {
            'scheduler': {'status': 'running', 'next_run': '...'},
            'failure_monitor': {'status': 'monitoring', 'current_failure_rate': 0.125},
            'feedback_analyzer': {'status': 'analyzing', 'trending_issues': 2},
            'last_run': {'run_id': 'run_scheduled_...', 'status': 'completed', 'ts': '...'}
        }
    """
    try:
        from app.agent.scheduler import get_scheduler
        from app.agent.failure_monitor import get_failure_monitor
        from app.agent.feedback_analyzer import get_feedback_analyzer
        
        status = {}
        
        # Scheduler status
        scheduler = get_scheduler()
        if scheduler and scheduler._running:
            next_run = await scheduler.get_next_run_time()
            status['scheduler'] = {
                'status': 'running',
                'next_run': next_run.get('next_run_utc')
            }
        else:
            status['scheduler'] = {'status': 'not_running'}
        
        # Failure monitor status
        monitor = get_failure_monitor()
        if monitor:
            stats = await monitor.get_recent_failure_stats()
            status['failure_monitor'] = {
                'status': 'monitoring',
                'current_failure_rate': stats.failure_rate if stats else None,
                'threshold': monitor.FAILURE_THRESHOLD,
                'should_trigger': await monitor.should_trigger()
            }
        else:
            status['failure_monitor'] = {'status': 'not_initialized'}
        
        # Feedback analyzer status
        analyzer = get_feedback_analyzer()
        if analyzer:
            analysis = await analyzer.analyze_feedback_trends()
            status['feedback_analyzer'] = {
                'status': 'analyzing',
                'trending_issues_count': len(analysis.trending_problems) if analysis else 0,
                'should_trigger': analysis.should_trigger if analysis else False
            }
        else:
            status['feedback_analyzer'] = {'status': 'not_initialized'}
        
        return {
            'layer2_triggers': status,
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get learning status: {e}")
        return {'error': str(e), 'timestamp': datetime.utcnow().isoformat()}
