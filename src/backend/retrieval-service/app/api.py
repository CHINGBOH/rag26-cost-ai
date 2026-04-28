"""
FastAPI 路由定义
/api/v1/search, /rerank, /evaluate, /decompose, /health, /rag
"""

import uuid
import re
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
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
        "llama_server": "http://localhost:8080/health",  # actual llama-server
        "ocr": "http://localhost:8001/health",
        "qdrant": "http://localhost:6333/healthz",
        "go_gateway": "http://localhost:8090/health",
        "nodejs": "http://localhost:3001/health",
    }
    results = {}
    async with httpx.AsyncClient(timeout=2.0) as client:
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
