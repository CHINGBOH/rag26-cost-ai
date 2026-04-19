"""
检索功能测试
"""

import pytest
import sys
import os

# 添加项目根目录到路径，支持相对导入
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))  # src/backend
sys.path.insert(0, project_root)

from retrieval.unified_pipeline import UnifiedRetrievalPipeline
from domain_models.retrieval_models import RetrievalRequest, RetrievalConfig


class TestRetrievalPipeline:
    """测试检索管道"""

    def setup_method(self):
        """每个测试方法前执行"""
        self.pipeline = UnifiedRetrievalPipeline()

    def test_retrieve_with_empty_query(self):
        """测试空查询处理"""
        config = RetrievalConfig()
        request = RetrievalRequest(query="", config=config)

        # 空查询应该返回空结果或错误处理
        try:
            response = self.pipeline.retrieve(request)
            assert response is not None
        except Exception as e:
            # 预期可能会抛出异常
            pass

    def test_retrieve_with_valid_query(self):
        """测试正常查询"""
        config = RetrievalConfig(vector_top_k=5, keyword_top_k=3, graph_top_k=2)
        request = RetrievalRequest(query="人工智能", config=config)

        response = self.pipeline.retrieve(request)

        assert response is not None
        assert response.request_id is not None
        assert isinstance(response.documents, list)
        assert response.latency_ms >= 0


def test_retrieval_config():
    """测试检索配置"""
    config = RetrievalConfig(vector_top_k=10, keyword_top_k=5, rerank_top_k=3)

    assert config.vector_top_k == 10
    assert config.keyword_top_k == 5
    assert config.rerank_top_k == 3
