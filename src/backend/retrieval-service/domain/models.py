"""
领域模型 - 契约定义
使用 Pydantic BaseModel 定义核心业务实体
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from enum import Enum


class QueryType(str, Enum):
    """查询类型枚举"""

    SEMANTIC = "semantic"
    KEYWORD = "keyword"
    ENTITY = "entity"
    HYBRID = "hybrid"


class Document(BaseModel):
    """
    文档实体

    召回精排系统中的核心文档对象
    """

    id: str = Field(..., description="文档唯一标识")
    content: str = Field(..., description="文档内容", min_length=1)
    doc_id: str = Field(..., description="所属文档ID")
    title: str = Field(default="", description="文档标题")
    page: int = Field(default=0, ge=0, description="页码")
    section: str = Field(default="", description="章节")
    chunk_type: str = Field(default="paragraph", description="片段类型")

    # 召回分数
    vector_score: float = Field(default=0.0, ge=-1.0, le=1.0, description="向量相似度")
    bm25_score: float = Field(default=0.0, ge=0.0, description="BM25分数")
    graph_score: float = Field(default=0.0, ge=0.0, le=1.0, description="图谱关联度")

    # 精排分数
    rerank_score: float = Field(default=0.0, description="Cross-Encoder分数")

    # 融合分数
    final_score: float = Field(default=0.0, ge=0.0, le=1.0, description="最终融合分数")

    # 元数据
    metadata: Dict[str, Any] = Field(default_factory=dict, description="附加元数据")
    publish_date: Optional[str] = Field(default=None, description="发布日期")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "doc_001_chunk_01",
                "content": "企业管理费包括管理人员工资、办公费...",
                "doc_id": "doc_001",
                "title": "建设工程计价标准",
                "page": 1,
                "section": "费用组成",
                "vector_score": 0.85,
                "final_score": 0.92,
            }
        }


class SearchRequest(BaseModel):
    """
    搜索请求

    RAG系统的查询输入
    """

    query: str = Field(
        ..., description="查询文本", min_length=1, max_length=1000, examples=["企业管理费怎么计算"]
    )
    top_k: int = Field(default=10, description="返回结果数量", ge=1, le=100)
    query_type: Optional[QueryType] = Field(default=None, description="查询类型(自动检测)")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="过滤条件")
    enable_rerank: bool = Field(default=True, description="是否启用精排")
    enable_fusion: bool = Field(default=True, description="是否启用分数融合")

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        """验证查询文本"""
        v = v.strip()
        if len(v) < 1:
            raise ValueError("查询文本不能为空")
        return v


class SearchResponse(BaseModel):
    """
    搜索响应

    RAG系统的查询输出
    """

    query: str = Field(..., description="原始查询")
    query_type: QueryType = Field(..., description="检测到的查询类型")
    documents: List[Document] = Field(..., description="检索结果文档")
    total_candidates: int = Field(..., ge=0, description="召回候选总数")
    retrieval_time_ms: float = Field(..., ge=0.0, description="检索耗时(毫秒)")
    total_time_ms: float = Field(..., ge=0.0, description="总耗时(毫秒)")

    # 各召回源统计
    vector_count: int = Field(default=0, ge=0, description="向量召回数量")
    keyword_count: int = Field(default=0, ge=0, description="关键词召回数量")
    graph_count: int = Field(default=0, ge=0, description="图谱召回数量")

    # 上下文
    context: Optional[str] = Field(default=None, description="生成的上下文")


class DocumentChunk(BaseModel):
    """文档片段"""

    id: str = Field(..., description="片段ID")
    content: str = Field(..., description="内容")
    doc_id: str = Field(..., description="所属文档ID")
    doc_title: str = Field(default="", description="文档标题")
    page: int = Field(default=0, ge=0)
    section: str = Field(default="")
    chunk_type: str = Field(default="paragraph")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class IndexRequest(BaseModel):
    """索引请求"""

    doc_id: str = Field(..., description="文档ID", min_length=1)
    title: str = Field(default="", description="文档标题")
    chunks: List[DocumentChunk] = Field(..., description="文档片段列表")
    build_graph: bool = Field(default=True, description="是否构建知识图谱")


class IndexResponse(BaseModel):
    """索引响应"""

    doc_id: str = Field(..., description="文档ID")
    chunks_indexed: int = Field(..., ge=0, description="索引的片段数")
    entities_extracted: int = Field(default=0, ge=0, description="提取的实体数")
    time_ms: float = Field(..., ge=0.0, description="耗时")
    success: bool = Field(..., description="是否成功")


class HealthResponse(BaseModel):
    """健康检查响应"""

    status: str = Field(..., description="状态")
    version: str = Field(..., description="版本")
    timestamp: datetime = Field(default_factory=datetime.now)
    services: Dict[str, bool] = Field(default_factory=dict, description="各服务状态")


class StatsResponse(BaseModel):
    """统计信息响应"""

    vector_store: Dict[str, Any] = Field(default_factory=dict)
    keyword_store: Dict[str, Any] = Field(default_factory=dict)
    graph_store: Dict[str, Any] = Field(default_factory=dict)


# 领域事件（用于异步处理）
class DocumentIndexedEvent(BaseModel):
    """文档索引完成事件"""

    doc_id: str
    chunks_count: int
    timestamp: datetime = Field(default_factory=datetime.now)


class SearchPerformedEvent(BaseModel):
    """搜索执行事件"""

    query: str
    query_type: QueryType
    results_count: int
    latency_ms: float
    timestamp: datetime = Field(default_factory=datetime.now)
