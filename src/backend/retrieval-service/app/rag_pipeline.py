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


def _strip_latex(text: str) -> str:
    """
    Deterministically convert LaTeX math notation to readable plain text.
    LLMs frequently ignore format instructions; this post-processing is the
    reliable fallback that never depends on LLM compliance.
    """
    import re

    # Replace LaTeX symbol commands with Unicode/text equivalents
    replacements = [
        (r'\\times', '×'),
        (r'\\div',   '÷'),
        (r'\\cdot',  '·'),
        (r'\\leq',   '≤'),
        (r'\\geq',   '≥'),
        (r'\\neq',   '≠'),
        (r'\\approx','≈'),
        (r'\\%',     '%'),
        (r'\\,',     ' '),
        (r'\\ ',     ' '),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)

    # \text{...} → just the inner text
    text = re.sub(r'\\text\{([^}]*)\}', r'\1', text)
    # \mathbf{...} / \textbf{...} → **...**
    text = re.sub(r'\\(?:mathbf|textbf)\{([^}]*)\}', r'**\1**', text)
    # \frac{a}{b} → a/b
    text = re.sub(r'\\frac\{([^}]*)\}\{([^}]*)\}', r'\1/\2', text)

    # Block math \[ ... \] → strip delimiters, keep content indented
    def _block_math(m: re.Match) -> str:
        inner = m.group(1).strip()
        # Each line of a multi-line block math becomes an indented plain line
        lines = [l.strip() for l in inner.split(r'\\') if l.strip()]
        return '\n' + '\n'.join(f'  {l}' for l in lines) + '\n'

    text = re.sub(r'\\\[\s*(.*?)\s*\\\]', _block_math, text, flags=re.DOTALL)

    # Inline math \( ... \) → strip delimiters
    text = re.sub(r'\\\(\s*(.*?)\s*\\\)', r'\1', text, flags=re.DOTALL)

    # Clean up any remaining lone backslash-commands like \quad \; \!
    text = re.sub(r'\\[a-zA-Z]+\b', '', text)

    return text


def _inject_calc_code(query: str, answer: str) -> str:
    """
    If the query is a cost-calculation question and the answer already contains
    a result, append a runnable Python verification block.
    Skips injection if a ```python block is already present.
    """
    import re

    calc_keywords = ['利润', '管理费', '人工费', '机械费', '材料费', '造价', '费用']
    is_calc = sum(1 for kw in calc_keywords if kw in query) >= 2
    if not is_calc or '```python' in answer:
        return answer

    # Extract numbers from the query (万 amounts)
    nums = re.findall(r'(\d+(?:\.\d+)?)\s*万', query)
    # Try to identify 人工费, 材料费, 机械费 by position in query
    labor = mat = mech = None
    for pattern, var in [
        (r'人工费[^\d]*(\d+(?:\.\d+)?)', 'labor'),
        (r'材料费[^\d]*(\d+(?:\.\d+)?)', 'mat'),
        (r'机械费[^\d]*(\d+(?:\.\d+)?)', 'mech'),
    ]:
        m = re.search(pattern, query)
        if m:
            if var == 'labor': labor = float(m.group(1))
            elif var == 'mat':  mat   = float(m.group(1))
            elif var == 'mech': mech  = float(m.group(1))

    if labor is None or mat is None or mech is None:
        return answer  # can't parse inputs, skip

    # Detect year from query/answer
    year = '2025' if '2025' in query or '2025' in answer else '2023'
    mgmt_rate = 0.2044  # 2025 推荐值
    profit_rate = 0.026  # 建筑工程 2025 推荐值

    code = f"""\
# 深圳市建设工程计价费率标准（{year}版）验证计算
人工费   = {labor}   # 万元
材料费   = {mat}   # 万元
机械费   = {mech}   # 万元
管理费率 = {mgmt_rate}    # 推荐值 {mgmt_rate*100:.2f}%
利润率   = {profit_rate}    # 建筑工程推荐值 {profit_rate*100:.2f}%

企业管理费 = (人工费 + 机械费 * 0.1) * 管理费率
利润基数   = 人工费 + 材料费 + 机械费 + 企业管理费
利润       = 利润基数 * 利润率

result = round(利润, 2)
print(f"企业管理费: {{企业管理费:.4f}} 万元")
print(f"利润基数:   {{利润基数:.4f}} 万元")
print(f"利润:       {{利润:.4f}} 万元")
"""

    return answer + f"\n\n---\n\n**📐 Python 验证（点击在沙箱中运行）**\n\n```python\n{code}```"


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
            "content": (
                "你是深圳市建设工程计价专业助手，根据检索到的文档片段回答问题，尽量引用原文，无法确定时说明不确定。\n\n"
                "【深圳市建设工程计价费率标准（2025版）核心公式——必须严格遵守】\n\n"
                "1. 企业管理费 = （人工费 + 机械费 × 0.1）× 企业管理费费率\n"
                "   推荐费率：20.44%（0.2044），参考范围：14%～26%，不区分专业工程\n\n"
                "2. 利润 = （人工费 + 材料费 + 机械费 + 企业管理费）× 利润率\n"
                "   建筑工程/装饰工程推荐利润率：2.60%（0.026），参考范围：1.90%～4.94%\n"
                "   注意：rate_recommended 单位是 %，2.60 表示 2.60%，不是倍数！\n\n"
                "【回答格式要求——必须按此格式输出，禁止使用 LaTeX \\[ \\] 格式】\n\n"
                "涉及数值计算时，输出结构如下（严格使用 Markdown）：\n\n"
                "## 计算过程\n\n"
                "### 第一步：企业管理费\n"
                "企业管理费 = (人工费 + 机械费×0.1) × 20.44%\n\n"
                "| 项目 | 计算 | 结果 |\n"
                "|------|------|------|\n"
                "| 管理费基数 | 人工费 + 机械费×0.1 | 105万 |\n"
                "| 企业管理费 | 105 × 20.44% | 21.46万 |\n\n"
                "### 第二步：利润\n"
                "利润 = (人工费 + 材料费 + 机械费 + 企业管理费) × 2.60%\n\n"
                "| 项目 | 计算 | 结果 |\n"
                "|------|------|------|\n"
                "| 利润基数 | 350 + 21.46 | 371.46万 |\n"
                "| 利润 | 371.46 × 2.60% | 9.66万 |\n\n"
                "## 汇总\n\n"
                "| 费用项目 | 金额（万元） |\n"
                "|----------|-------------|\n"
                "| 人工费 | 100 |\n"
                "| 材料费 | 200 |\n"
                "| 机械费 | 50 |\n"
                "| 企业管理费 | 21.46 |\n"
                "| **利润** | **9.66** |\n\n"
                "最后附上 Python 验证代码块（用 ```python 标记，包含 result = 最终结果 这一行）：\n"
                "```python\n"
                "人工费 = 100\n"
                "材料费 = 200\n"
                "机械费 = 50\n"
                "管理费率 = 0.2044\n"
                "利润率 = 0.026\n"
                "企业管理费 = (人工费 + 机械费 * 0.1) * 管理费率\n"
                "利润基数 = 人工费 + 材料费 + 机械费 + 企业管理费\n"
                "利润 = 利润基数 * 利润率\n"
                "result = round(利润, 2)\n"
                "print(f'企业管理费: {企业管理费:.2f}万元  利润: {利润:.2f}万元')\n"
                "```\n\n"
                "实际回答时，表格和代码中的数值用用户给出的真实数据替换，不要照抄示例数字。\n"
            ),
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
            raw = resp.json()["choices"][0]["message"]["content"]
            answer = _inject_calc_code(state["query"], _strip_latex(raw))
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
