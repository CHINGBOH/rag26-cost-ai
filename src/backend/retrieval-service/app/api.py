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
            await conn.execute(
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
                """,
                record["ts"], request.session_id, request.message_id,
                request.rating, request.comment, request.query, request.answer_summary,
                request.overall_rating, request.rating_relevance, request.rating_accuracy,
                request.rating_completeness, request.praise, request.criticism,
                request.suggestion, request.tags,
            )
        finally:
            await conn.close()
    except Exception as e:
        logger.warning(f"Feedback DB write skipped: {e}")

    return {"status": "ok", "message_id": request.message_id}


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

    # ── Milvus (probe but not required yet — #49) ──
    milvus_url = os.environ.get("MILVUS_URL")
    if milvus_url:
        try:
            async with httpx.AsyncClient(timeout=3.0, transport=transport) as client:
                r = await client.get(f"{milvus_url}/health")
                snapshot["stores"]["milvus"] = {
                    "role": "vector store (planned)",
                    "available": r.status_code == 200,
                    "status_code": r.status_code,
                }
        except Exception as e:
            snapshot["stores"]["milvus"] = {"available": False, "error": str(e)[:200]}
    else:
        snapshot["stores"]["milvus"] = {
            "role": "vector store (planned)",
            "available": False,
            "configured": False,
            "note": "MILVUS_URL not set — see #49",
        }

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


_GUIDE_SYSTEM = """您是「RAG智库系统」的导览助手，专门解答本系统的架构、检索流程、工具用途等技术问题。

核心规则（强制执行，不得违反）：
第一、每次回答前必须调用 query_guide_kb 工具查询系统内部知识库，再根据查询结果作答。
第二、只根据 query_guide_kb 返回的内容作答，不补充资料以外的信息。
第三、若工具返回内容为空，直接告知用户知识库中暂无此内容。
第四、禁止使用任何 Markdown 格式符号，包括 #、*、**、-、---、>、`。列举用"第一、第二、第三"替代。
第五、当用户询问架构、模块、流程、数据流、系统结构等可视化内容时，必须在回答中输出 Mermaid 图表代码块（```mermaid 开头，``` 结尾），不得用纯文字替代。

Mermaid 图表规范：
架构或模块关系用 graph TB 或 graph LR；数据流或请求流用 flowchart TD；时序交互用 sequenceDiagram。
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
    def query_guide_kb(question: str, top_k: int = 5) -> str:
        """查询RAG智库系统内部技术文档知识库，返回与问题相关的架构说明、工具介绍、检索流程等资料。每次回答前必须调用此工具。"""
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

        # Step 1: LLM decides how to call query_guide_kb (model-controlled tool use)
        yield _sse_event("progress", {"stage": "tool_call", "message": "正在查询知识库..."})
        await asyncio.sleep(0)
        try:
            ai_msg, _ = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: invoke_llm_with_tools(
                    conv, [query_guide_kb], tool_choice="required", llm_config=_llm_config
                ),
            )
        except Exception as exc:
            yield _sse_event("error", {"message": f"工具调用失败: {exc}"})
            return

        # Step 2: Execute the tool calls the LLM made
        tool_calls = getattr(ai_msg, "tool_calls", []) or []
        extra_msgs: list = [ai_msg]
        for tc in tool_calls:
            tc_id = tc.get("id", "")
            tc_args = tc.get("args", {})
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda a=tc_args: query_guide_kb.invoke(a)
                )
            except Exception as exc:
                result = json.dumps({"error": str(exc)}, ensure_ascii=False)
            extra_msgs.append(_Tool(content=result, tool_call_id=tc_id))

        # Step 3: Stream synthesis grounded on tool results
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
