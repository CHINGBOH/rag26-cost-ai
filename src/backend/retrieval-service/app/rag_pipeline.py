"""
LangGraph RAG Pipeline
替代 XState 编排：retrieve → rerank → generate
简单线性图，先跑通，后优化。
"""

import os
import logging
from typing import TypedDict, List, Optional, Any

import httpx
from langgraph.graph import StateGraph, END

from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parents[4] / ".env")

logger = logging.getLogger(__name__)

# ── State ─────────────────────────────────────────────────────────────────────

class RAGState(TypedDict):
    query: str
    chunks: List[dict]          # retrieved + reranked documents
    answer: str
    error: Optional[str]
    depth: int


# ── Nodes ─────────────────────────────────────────────────────────────────────

def make_retrieve_node(pipeline):
    """工厂函数：生成绑定 pipeline 的 retrieve_node"""
    def retrieve_node(state: RAGState) -> RAGState:
        """调用 UnifiedRetrievalPipeline 检索文档"""
        if pipeline is None:
            return {**state, "chunks": [], "error": "Pipeline not initialized"}

        try:
            from domain_models.retrieval import RetrievalRequest, RetrievalConfig

            req = RetrievalRequest(
                query=state["query"],
                config=RetrievalConfig(vector_top_k=30, keyword_top_k=20, graph_top_k=10),
            )
            resp = pipeline.retrieve(req)
            chunks = []
            for doc in resp.documents[:20]:
                chunk = {
                    "id": doc.chunk_id,
                    "content": doc.content,
                    "score": round(doc.score, 4),
                    "source": doc.doc_id,
                    "database": doc.metadata.get("source_db") if doc.metadata else "hybrid",
                    "source_db": doc.metadata.get("source_db") if doc.metadata else "hybrid",
                    "metadata": {
                        "page": doc.metadata.get("page_number") if doc.metadata else None,
                        "section": doc.metadata.get("section") if doc.metadata else None,
                    },
                }
                chunks.append(chunk)

            # 补充结构化表查询（fee_rates 等），确保精确查询不被向量阈值过滤
            try:
                from app.agent.tools import _query_structured_tables
                for sc in _query_structured_tables(state["query"]):
                    sc["id"] = sc.pop("chunk_id")
                    sc["source"] = sc.pop("doc_id")
                    sc["database"] = sc["source_db"]
                    chunks.append(sc)
            except Exception as se:
                logger.warning(f"[RAGPipeline] structured tables fallback failed: {se}")

            logger.info(f"[RAGPipeline] retrieved {len(chunks)} chunks")
            return {**state, "chunks": chunks}
        except Exception as e:
            logger.error(f"[RAGPipeline] retrieve error: {e}")
            return {**state, "chunks": [], "error": str(e)}
    return retrieve_node


def rerank_node(state: RAGState) -> RAGState:
    """调用 reranker_service 精排（可选）"""
    if not state["chunks"]:
        return state

    try:
        from infrastructure.reranker_service import get_reranker_service

        reranker = get_reranker_service()
        contents = [c["content"] for c in state["chunks"]]
        scores = reranker.rerank(state["query"], contents)

        reranked = sorted(
            [
                {**chunk, "score": float(score)}
                for chunk, score in zip(state["chunks"], scores)
            ],
            key=lambda x: x["score"],
            reverse=True,
        )
        logger.info(f"[RAGPipeline] reranked {len(reranked)} chunks")
        return {**state, "chunks": reranked[:10]}
    except Exception as e:
        logger.warning(f"[RAGPipeline] rerank skipped: {e}")
        return {**state, "chunks": state["chunks"][:10]}


def generate_node(state: RAGState) -> RAGState:
    """用 LLM API 生成答案；无配置时返回检索摘要"""
    api_key = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
    model = os.getenv("LLM_MODEL", "deepseek-chat")

    chunks = state["chunks"]
    context_text = "\n\n".join(
        f"[{i+1}] (score={c['score']:.3f})\n{c['content'][:400]}"
        for i, c in enumerate(chunks[:5])
    )

    if not api_key:
        # 无 LLM 配置 → 返回检索摘要，让前端可以看到结果
        answer = (
            f"[检索结果摘要，未配置 LLM]\n\n"
            f"找到 {len(chunks)} 条相关片段：\n\n{context_text}"
        )
        return {**state, "answer": answer}

    prompt_messages = [
        {
            "role": "system",
            "content": "你是一个知识库问答助手，根据检索到的文档片段回答用户问题，尽量引用原文，无法确定时说明不确定。",
        },
        {
            "role": "user",
            "content": f"问题：{state['query']}\n\n参考文档：\n{context_text}",
        },
    ]

    try:
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": prompt_messages, "max_tokens": 1024},
            )
            resp.raise_for_status()
            answer = resp.json()["choices"][0]["message"]["content"]
        logger.info(f"[RAGPipeline] generated answer ({len(answer)} chars)")
        return {**state, "answer": answer}
    except Exception as e:
        logger.error(f"[RAGPipeline] generate error: {e}")
        # 降级：返回检索摘要
        answer = f"[生成失败: {e}]\n\n检索摘要：\n{context_text}"
        return {**state, "answer": answer}


# ── Graph ──────────────────────────────────────────────────────────────────────

def build_rag_graph(pipeline=None):
    g = StateGraph(RAGState)
    g.add_node("retrieve", make_retrieve_node(pipeline))
    g.add_node("rerank", rerank_node)
    g.add_node("generate", generate_node)

    g.set_entry_point("retrieve")
    g.add_edge("retrieve", "rerank")
    g.add_edge("rerank", "generate")
    g.add_edge("generate", END)

    return g.compile()


# 模块级单例，首次调用时初始化
_graph = None


def get_rag_graph(pipeline=None):
    global _graph
    if _graph is None:
        _graph = build_rag_graph(pipeline)
    return _graph


def run_rag(query: str, pipeline=None) -> dict:
    """同步运行 RAG pipeline，返回结果字典"""
    graph = get_rag_graph(pipeline)
    initial: RAGState = {
        "query": query,
        "chunks": [],
        "answer": "",
        "error": None,
        "depth": 0,
    }
    result = graph.invoke(initial)
    return {
        "query": result["query"],
        "answer": result["answer"],
        "chunks": result["chunks"],
        "error": result.get("error"),
    }
