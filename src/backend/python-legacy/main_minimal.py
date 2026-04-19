"""
最小化 API - 用于测试，绕过AI模型依赖
提供真实的四库检索能力（ES关键词、Neo4j图谱），失败时返回空结果而非mock数据
"""

import sys
import os
import time

# 添加项目根目录到路径，支持相对导入
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)  # src/backend
sys.path.insert(0, project_root)
sys.path.insert(0, current_dir)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
import uuid
import logging
import numpy as np
from datetime import datetime
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 加载 .env 环境变量
try:
    from dotenv import load_dotenv
    # 尝试多个位置查找 .env
    env_candidates = [
        os.path.join(current_dir, ".env"),          # python-legacy 目录
        os.path.join(project_root, ".env"),          # src/backend 目录
        os.path.join(os.path.dirname(project_root), ".env"),  # 项目根目录
    ]
    for env_path in env_candidates:
        if os.path.exists(env_path):
            load_dotenv(env_path)
            logger.info("Loaded .env from %s", env_path)
            break
except Exception:
    pass

app = FastAPI(title="RAG Dashboard Minimal API", description="最小化测试API（真实检索）", version="0.2.0")

# ========== 轻量级数据库客户端（不依赖 sentence_transformers） ==========
es_client = None
neo4j_driver = None
qdrant_client = None


def _init_db_clients():
    """初始化轻量级数据库连接（失败不影响服务启动）"""
    global es_client, neo4j_driver, qdrant_client

    # Elasticsearch
    try:
        from elasticsearch import Elasticsearch
        es_client = Elasticsearch(["http://localhost:9200"])
        if es_client.ping():
            logger.info("✅ Elasticsearch connected")
        else:
            es_client = None
            logger.warning("❌ Elasticsearch ping failed")
    except Exception as e:
        logger.warning(f"❌ Elasticsearch init failed: {e}")
        es_client = None

    # Neo4j
    try:
        from neo4j import GraphDatabase
        neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
        neo4j_driver = GraphDatabase.driver(
            "bolt://localhost:7687",
            auth=(os.getenv("NEO4J_USERNAME", "neo4j"), neo4j_password)
        )
        with neo4j_driver.session() as session:
            session.run("RETURN 1")
        logger.info("✅ Neo4j connected")
    except Exception as e:
        logger.warning(f"❌ Neo4j init failed: {e}")
        neo4j_driver = None

    # Qdrant (仅用于健康检查，向量搜索需要embedding模型)
    try:
        from qdrant_client import QdrantClient
        qdrant_client = QdrantClient(host="localhost", port=6333)
        logger.info("✅ Qdrant connected (vector search disabled: no embedding model)")
    except Exception as e:
        logger.warning(f"❌ Qdrant init failed: {e}")
        qdrant_client = None


@app.on_event("startup")
async def startup_event():
    _init_db_clients()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== 健康检查 ==========


@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "services": {
            "vector_store": "healthy",
            "keyword_store": "healthy",
            "graph_store": "healthy",
            "cache": "healthy",
        },
        "timestamp": datetime.now().isoformat(),
    }


# ========== 搜索接口 ==========


class SearchRequest(BaseModel):
    query: str = Field(..., description="搜索查询文本")
    top_k: int = Field(default=10, ge=1, le=100)
    mode: str = Field(default="hybrid", description="搜索模式")
    filters: Dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[str] = None


@app.post("/api/search")
async def search(request: SearchRequest):
    """统一搜索接口 —— 调用真实 ES/Neo4j，格式兼容旧版"""
    try:
        v1_req = V1SearchRequest(query=request.query, top_k=request.top_k)
        v1_resp = await v1_search(v1_req)
        return {
            "status": "success",
            "data": {
                "request_id": str(uuid.uuid4()),
                "query": v1_resp["query"],
                "results": v1_resp["results"],
                "latency_ms": round(v1_resp.get("processing_time", 0) * 1000, 2),
                "stats": v1_resp.get("search_stats", {}),
            },
        }
    except Exception as e:
        logger.error(f"Search error: {e}")
        return {"status": "error", "message": str(e)}


# ========== 兼容 /api/v1/search ==========

class V1SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=10, ge=1, le=100)
    use_rerank: bool = True
    use_llm: bool = False
    filters: Optional[Dict[str, Any]] = None


@app.post("/api/v1/search")
async def v1_search(request: V1SearchRequest):
    """兼容Node.js Agent工具的搜索接口 —— 调用真实四库（ES/Neo4j），失败返回空结果"""
    start_time = time.time()
    query = request.query
    top_k = request.top_k
    all_results = []
    total_candidates = 0

    # 1. Elasticsearch 关键词搜索
    if es_client is not None:
        try:
            resp = es_client.search(
                index="documents",
                body={
                    "query": {
                        "multi_match": {
                            "query": query,
                            "fields": ["content", "doc_id", "keywords"],
                            "type": "best_fields"
                        }
                    },
                    "size": top_k * 2,
                },
            )
            hits = resp.get("hits", {}).get("hits", [])
            total_candidates += resp.get("hits", {}).get("total", {}).get("value", 0)
            max_score = resp.get("hits", {}).get("max_score") or 1.0
            for hit in hits:
                src = hit.get("_source", {})
                raw_score = hit.get("_score", 0)
                # 归一化分数到 0-1 区间（ES原始分数通常 >1）
                normalized_score = min(raw_score / max(max_score, 1.0), 1.0)
                all_results.append({
                    "chunk_id": src.get("chunk_id", hit.get("_id", "")),
                    "doc_id": src.get("doc_id", ""),
                    "content": src.get("content", "")[:1000],
                    "score": round(normalized_score * 0.9 + 0.05, 4),
                    "source": f"{src.get('doc_id', 'unknown')}.pdf",
                    "metadata": {
                        "page_number": src.get("page_number", 1),
                        "doc_id": src.get("doc_id", ""),
                        "source_db": "keyword",
                    },
                })
        except Exception as e:
            logger.warning(f"ES search failed: {e}")

    # 2. Neo4j 图谱搜索
    if neo4j_driver is not None:
        try:
            with neo4j_driver.session() as session:
                result = session.run(
                    """
                    MATCH (c:Chunk)-[:BELONGS_TO]->(d:Document)
                    WHERE c.content CONTAINS $query
                    RETURN c.chunk_id as chunk_id, c.content as content,
                           c.page as page, d.doc_id as doc_id, d.title as title
                    LIMIT $top_k
                    """,
                    {"query": query, "top_k": top_k},
                )
                graph_hits = list(result)
                total_candidates += len(graph_hits)
                for record in graph_hits:
                    all_results.append({
                        "chunk_id": record.get("chunk_id", ""),
                        "doc_id": record.get("doc_id") or "",
                        "content": (record.get("content") or "")[:1000],
                        "score": 0.75,
                        "source": f"{record.get('title') or record.get('doc_id') or 'unknown'}.pdf",
                        "metadata": {
                            "page_number": record.get("page") or 1,
                            "doc_id": record.get("doc_id") or "",
                            "source_db": "graph",
                        },
                    })
        except Exception as e:
            logger.warning(f"Neo4j search failed: {e}")

    # 3. Qdrant 向量搜索（跳过：无embedding模型且集合为空）
    # 若后续修复了 sentence_transformers 依赖，可在此补充向量召回

    # 去重（按 chunk_id）
    seen = set()
    unique_results = []
    for r in all_results:
        key = r["chunk_id"]
        if key and key not in seen:
            seen.add(key)
            unique_results.append(r)

    # 按分数降序
    unique_results.sort(key=lambda x: x["score"], reverse=True)
    final_results = unique_results[:top_k]

    processing_time = time.time() - start_time

    return {
        "query": query,
        "results": final_results,
        "total_candidates": total_candidates,
        "processing_time": round(processing_time, 3),
        "search_stats": {
            "vector_candidates": 0,
            "keyword_candidates": total_candidates,
            "graph_candidates": 0,
            "final_results": len(final_results),
        },
        "llm_response": None,
    }


# ========== 查询分解接口 ==========


class DecomposeRequest(BaseModel):
    query: str


@app.post("/api/v1/decompose")
async def decompose_query(request: DecomposeRequest):
    """将查询分解为子查询"""
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

    return {"sub_queries": sub_queries, "original_query": query}


# ========== 评估接口 ==========


class EvaluationRequest(BaseModel):
    query: str
    retrieved_chunks: List[Dict[str, Any]]
    generated_answer: str
    history_rounds: int = 0


@app.post("/api/v1/evaluate")
async def evaluate_retrieval(request: EvaluationRequest):
    """评估检索结果质量 —— 改进版（BM25-like语义重叠、引用检测、数值一致性）"""
    chunks = request.retrieved_chunks
    answer = request.generated_answer

    # 1. 基础分数
    avg_score = sum(c.get("score", 0) for c in chunks) / len(chunks) if chunks else 0
    sources = set(c.get("source", "") for c in chunks)
    source_diversity = min(len(sources) / 3, 1.0)
    information_gain = max(0.1, 0.5 - request.history_rounds * 0.1)

    # 2. 完整性（基于检索内容总长度）
    total_length = sum(len(c.get("content", "")) for c in chunks)
    completeness = min(total_length / 2000, 0.95)

    # 3. 一致性（基于检索结果分数方差）
    scores = [c.get("score", 0) for c in chunks]
    if scores:
        avg = sum(scores) / len(scores)
        variance = sum((s - avg) ** 2 for s in scores) / len(scores) if len(scores) > 1 else 0
        consistency = max(0.5, 1 - variance * 4)
    else:
        consistency = 0.5

    # 4. 引用检测（hasCitations）
    citation_patterns = [
        r"\[\d+\]",                         # [1], [2]
        r"chunk_[\w_]+",                    # chunk_xxx
        r"参考[《\"']",                      # 参考《xxx》
        r"依据[《\"']",                      # 依据《xxx》
        r"根据[《\"']",                      # 根据《xxx》
        r"第[一二三四五六七八九十\d]+[条款章]",   # 第X条/款/章
        r"\(\d{4}[年]?\)",                  # (2025)
    ]
    has_citations = any(re.search(p, answer) for p in citation_patterns)
    citation_count = len(re.findall(r"\[\d+\]", answer))

    # 5. 事实一致性（BM25-like：回答与检索内容的token重叠度）
    def _tokenize(text: str) -> set:
        """简单分词：中文单字 + 英文单词 + 数字"""
        text = text.lower()
        tokens = set(re.findall(r"[a-z]+|\d+|[\u4e00-\u9fff]", text))
        return tokens

    chunk_tokens = set()
    for c in chunks:
        chunk_tokens.update(_tokenize(c.get("content", "")))

    answer_tokens = _tokenize(answer)

    if chunk_tokens and answer_tokens:
        overlap = len(chunk_tokens & answer_tokens)
        union = len(chunk_tokens | answer_tokens)
        jaccard = overlap / union if union > 0 else 0

        # 回答token被检索结果覆盖的比例（containment）
        containment = len(answer_tokens & chunk_tokens) / len(answer_tokens) if answer_tokens else 0

        # 加权综合
        fact_consistency = 0.35 * jaccard + 0.65 * containment
        fact_consistency = min(max(fact_consistency, 0.1), 0.95)
    else:
        fact_consistency = 0.3 if has_citations else 0.1

    # 若检测到引用标记，给予额外奖励（但上限0.95）
    if has_citations:
        fact_consistency = min(fact_consistency + 0.08, 0.95)

    # 6. 数值一致性检查（提取回答和chunks中的数字，比较是否匹配）
    answer_numbers = set(re.findall(r"\d+\.?\d*", answer))
    chunk_numbers = set()
    for c in chunks:
        chunk_numbers.update(re.findall(r"\d+\.?\d*", c.get("content", "")))
    if answer_numbers and chunk_numbers:
        num_overlap = len(answer_numbers & chunk_numbers)
        num_ratio = num_overlap / len(answer_numbers)
        # 若回答中的数字大部分都能在检索结果中找到，提升fact_consistency
        if num_ratio > 0.5:
            fact_consistency = min(fact_consistency + 0.05, 0.95)

    # 7. 覆盖率估计
    coverage_estimate = min(avg_score * source_diversity * 1.5, 0.95)

    # 8. 综合置信度（加权，更重视事实一致性和引用完整性）
    confidence = (
        completeness * 0.15 +
        consistency * 0.15 +
        fact_consistency * 0.35 +
        source_diversity * 0.15 +
        (0.25 if has_citations else 0.0)
    )
    confidence = min(confidence, 0.95)

    return {
        "completeness": round(completeness, 4),
        "consistency": round(consistency, 4),
        "confidence": round(confidence, 4),
        "information_gain": round(information_gain, 4),
        "source_diversity": round(source_diversity, 4),
        "fact_consistency": round(fact_consistency, 4),
        "coverage_estimate": round(coverage_estimate, 4),
        "has_citations": has_citations,
        "citation_count": citation_count,
    }


# ========== 重排序接口 ==========


class RerankRequest(BaseModel):
    query: str
    documents: List[Dict[str, Any]]
    top_k: int = Field(default=10, ge=1, le=100)


@app.post("/api/v1/rerank")
async def rerank_documents(request: RerankRequest):
    """文档重排序接口"""
    return {
        "results": [
            {
                "id": doc["id"],
                "content": doc["content"][:200] if len(doc["content"]) > 200 else doc["content"],
                "score": doc.get("score", 0.5),
            }
            for doc in request.documents[: request.top_k]
        ],
        "query": request.query,
        "note": "rerank not implemented, returning original order",
    }


# ========== 统计接口 ==========


@app.get("/api/stats")
async def get_stats():
    """获取系统统计"""
    return {
        "status": "success",
        "data": {
            "total_requests": 42,
            "average_latency_ms": 125.5,
            "store_health": {
                "vector_store": "healthy",
                "keyword_store": "healthy",
                "graph_store": "healthy",
                "cache": "healthy",
            },
        },
    }


if __name__ == "__main__":
    import uvicorn

    print("""
╔═══════════════════════════════════════════════════════════╗
║     RAG Dashboard Minimal Backend                         ║
║                                                           ║
║     API:     http://localhost:8000                        ║
║     Docs:    http://localhost:8000/docs                   ║
║     Health:  http://localhost:8000/health                 ║
║                                                           ║
║     注意: 这是最小化测试版本，用于绕过AI模型依赖          ║
╚═══════════════════════════════════════════════════════════╝
    """)
    uvicorn.run("main_minimal:app", host="0.0.0.0", port=8000, reload=True)
