"""
API路由测试
"""

import pytest
from fastapi.testclient import TestClient
import sys
import os
from types import SimpleNamespace

# 添加项目根目录到路径，支持相对导入
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))  # src/backend
sys.path.insert(0, project_root)

from api import unified_api

app = unified_api.app
client = TestClient(app)


def _build_fake_retrieval_response():
    return SimpleNamespace(
        request_id="test-request",
        documents=[
            SimpleNamespace(
                chunk_id="chunk-1",
                doc_id="doc-1",
                content="测试检索结果",
                score=0.95,
                metadata={"source": "test"},
            )
        ],
        latency_ms=12.5,
        stats={"total": 1},
    )


@pytest.fixture()
def fake_search_pipeline(monkeypatch):
    pipeline = SimpleNamespace(retrieve=lambda request: _build_fake_retrieval_response())
    monkeypatch.setattr(unified_api, "pipeline", pipeline)
    return pipeline


def test_health_check():
    """测试健康检查接口"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data


@pytest.mark.usefixtures("fake_search_pipeline")
def test_search_api():
    """测试搜索接口"""
    response = client.post("/api/search", json={"query": "测试查询", "top_k": 5, "mode": "hybrid"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "results" in data["data"]


def test_rerank_api():
    """测试重排序接口"""
    response = client.post(
        "/api/v1/rerank",
        json={
            "query": "测试查询",
            "documents": [{"id": "1", "content": "文档1内容"}, {"id": "2", "content": "文档2内容"}],
            "top_k": 2,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "results" in data


def test_evaluate_api():
    """测试评估接口"""
    response = client.post(
        "/api/v1/evaluate",
        json={
            "query": "测试查询",
            "retrieved_chunks": [
                {"id": "1", "content": "内容1", "source": "doc1", "score": 0.9},
                {"id": "2", "content": "内容2", "source": "doc2", "score": 0.8},
            ],
            "generated_answer": "这是生成的答案",
            "history_rounds": 0,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "confidence" in data
    assert "completeness" in data


def test_decompose_api():
    """测试查询分解接口"""
    response = client.post("/api/v1/decompose", json={"query": "如何实现RAG系统"})
    assert response.status_code == 200
    data = response.json()
    assert "sub_queries" in data
    assert len(data["sub_queries"]) > 0
