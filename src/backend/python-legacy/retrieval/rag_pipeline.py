#!/usr/bin/env python3
"""
端到端检索 Pipeline
整合多路召回、精排、分数融合和上下文增强
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
import json
import time

from multi_stage_retriever import (
    MultiStageRetriever,
    VectorRetriever,
    KeywordRetriever,
    GraphRetriever,
    Reranker,
    FusionScorer,
    Document,
    RetrievalResult,
    QueryType,
)
from vector_store import QdrantClient, EmbeddingService, VectorStorePipeline
from keyword_store import ElasticsearchClient, KeywordStorePipeline
from graph_store import Neo4jClient, GraphBuilder
from context_enhancer import ContextEnhancer, ContextStrategy, RAGContextBuilder


@dataclass
class RAGResponse:
    """RAG 响应"""

    query: str
    answer: str = ""
    documents: List[Document] = field(default_factory=list)
    context: str = ""
    retrieval_time_ms: float = 0.0
    total_time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class RAGPipeline:
    """
    端到端 RAG Pipeline

    完整流程:
    1. 查询理解（分类、嵌入）
    2. 多路召回（向量、关键词、图谱）
    3. 候选池合并（去重、粗排）
    4. 精排（Cross-Encoder）
    5. 分数融合（加权排序）
    6. 上下文增强（前后段落、实体链接）
    7. 生成回答（LLM）
    """

    def __init__(
        self,
        vector_store: Optional[QdrantClient] = None,
        keyword_store: Optional[ElasticsearchClient] = None,
        graph_store: Optional[Neo4jClient] = None,
        embedding_service: Optional[EmbeddingService] = None,
        reranker: Optional[Reranker] = None,
        fusion_scorer: Optional[FusionScorer] = None,
        context_enhancer: Optional[ContextEnhancer] = None,
    ):
        # 初始化存储
        self.vector_store = vector_store or QdrantClient()
        self.keyword_store = keyword_store or ElasticsearchClient()
        self.graph_store = graph_store or Neo4jClient()

        # 初始化嵌入服务
        self.embedding = embedding_service or EmbeddingService()

        # 初始化召回器
        self.vector_retriever = VectorRetriever(self.vector_store)
        self.keyword_retriever = KeywordRetriever(self.keyword_store)
        self.graph_retriever = GraphRetriever(self.graph_store)

        # 初始化精排和融合
        self.reranker = reranker or Reranker()
        self.fusion_scorer = fusion_scorer or FusionScorer()

        # 初始化上下文增强
        self.context_enhancer = context_enhancer or ContextEnhancer(
            vector_store=self.vector_store, graph_store=self.graph_store
        )

        # 构建多阶段召回器
        self.retriever = MultiStageRetriever(
            vector_retriever=self.vector_retriever,
            keyword_retriever=self.keyword_retriever,
            graph_retriever=self.graph_retriever,
            reranker=self.reranker,
            fusion_scorer=self.fusion_scorer,
            embedding_model=self.embedding,
            vector_store=self.vector_store,
            keyword_store=self.keyword_store,
            graph_store=self.graph_store,
        )

        # RAG 上下文构建器
        self.context_builder = RAGContextBuilder()

    def index_document(
        self, doc_id: str, chunks: List[Dict[str, Any]], build_graph: bool = True
    ) -> bool:
        """
        索引文档到所有存储

        Args:
            doc_id: 文档 ID
            chunks: 文档片段列表
            build_graph: 是否构建知识图谱

        Returns:
            是否成功
        """
        print(f"\n索引文档: {doc_id}")
        print("=" * 60)

        success = True

        # 1. 索引到向量存储
        print("\n1. 索引到向量存储 (Qdrant)...")
        try:
            vector_pipeline = VectorStorePipeline(self.vector_store, self.embedding)
            vector_pipeline.index_documents(chunks)
            print("   ✓ 向量索引完成")
        except Exception as e:
            print(f"   ✗ 向量索引失败: {e}")
            success = False

        # 2. 索引到关键词存储
        print("\n2. 索引到关键词存储 (Elasticsearch)...")
        try:
            keyword_pipeline = KeywordStorePipeline(self.keyword_store)
            keyword_pipeline.index_documents(chunks)
            print("   ✓ 关键词索引完成")
        except Exception as e:
            print(f"   ✗ 关键词索引失败: {e}")
            success = False

        # 3. 构建知识图谱
        if build_graph:
            print("\n3. 构建知识图谱 (Neo4j)...")
            try:
                graph_builder = GraphBuilder(self.graph_store)
                graph_builder.build_from_document(doc_id, chunks)
                print("   ✓ 图谱构建完成")
            except Exception as e:
                print(f"   ✗ 图谱构建失败: {e}")
                # 图谱失败不影响整体成功

        print("\n" + "=" * 60)
        print(f"文档索引{'完成' if success else '部分失败'}")

        return success

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        enable_rerank: bool = True,
        enable_fusion: bool = True,
    ) -> RetrievalResult:
        """
        执行检索

        Args:
            query: 查询文本
            top_k: 返回结果数量
            enable_rerank: 是否启用精排
            enable_fusion: 是否启用分数融合

        Returns:
            检索结果
        """
        return self.retriever.retrieve(
            query=query,
            top_k=top_k,
            enable_rerank=enable_rerank,
            enable_fusion=enable_fusion,
        )

    def query(
        self,
        query: str,
        top_k: int = 10,
        context_strategy: ContextStrategy = ContextStrategy.SURROUNDING,
        generate_answer: bool = False,
    ) -> RAGResponse:
        """
        执行完整 RAG 查询

        Args:
            query: 查询文本
            top_k: 检索结果数量
            context_strategy: 上下文增强策略
            generate_answer: 是否生成回答（需要 LLM）

        Returns:
            RAG 响应
        """
        start_time = time.time()

        # 1. 检索
        print(f"\n执行查询: {query}")
        print("=" * 60)

        retrieval_result = self.retrieve(query, top_k)
        retrieval_time = retrieval_result.retrieval_time_ms

        print(f"\n检索完成:")
        print(f"  查询类型: {retrieval_result.query_type.value}")
        print(f"  召回候选: {retrieval_result.total_candidates}")
        print(f"  最终结果: {len(retrieval_result.documents)}")
        print(f"  检索耗时: {retrieval_time:.2f}ms")

        if retrieval_result.vector_count:
            print(f"  向量召回: {retrieval_result.vector_count}")
        if retrieval_result.keyword_count:
            print(f"  关键词召回: {retrieval_result.keyword_count}")
        if retrieval_result.graph_count:
            print(f"  图谱召回: {retrieval_result.graph_count}")

        # 2. 上下文增强
        print("\n2. 上下文增强...")
        enhanced_results = []

        for doc in retrieval_result.documents:
            enhanced = self.context_enhancer.enhance(
                doc_id=doc.doc_id,
                chunk_id=doc.id,
                content=doc.content,
                strategy=context_strategy,
                query=query,
            )
            enhanced_results.append(enhanced)

        print(f"   ✓ 增强完成: {len(enhanced_results)} 个结果")

        # 3. 构建 RAG 上下文
        print("\n3. 构建 RAG 上下文...")
        rag_context = self.context_builder.build(enhanced_results, query)
        print(f"   ✓ 上下文长度: {len(rag_context)} 字符")

        # 4. 生成回答（可选）
        answer = ""
        if generate_answer:
            print("\n4. 生成回答...")
            answer = self._generate_answer(query, rag_context)
            print(f"   ✓ 回答生成完成")

        total_time = (time.time() - start_time) * 1000

        return RAGResponse(
            query=query,
            answer=answer,
            documents=retrieval_result.documents,
            context=rag_context,
            retrieval_time_ms=retrieval_time,
            total_time_ms=total_time,
            metadata={
                "query_type": retrieval_result.query_type.value,
                "total_candidates": retrieval_result.total_candidates,
                "vector_count": retrieval_result.vector_count,
                "keyword_count": retrieval_result.keyword_count,
                "graph_count": retrieval_result.graph_count,
                "context_chunks": len(enhanced_results),
            },
        )

    def _generate_answer(self, query: str, context: str) -> str:
        """
        生成回答（需要接入 LLM）

        这里预留接口，实际应接入 OpenAI、Claude 或本地 LLM
        """
        # 模拟生成
        return f"[基于检索到的 {len(context)} 字符上下文生成回答]\n\n查询: {query}\n\n[LLM 回答将在这里生成...]"

    def get_stats(self) -> Dict[str, Any]:
        """获取各存储统计信息"""
        return {
            "vector_store": self.vector_store.get_collection_info()
            if hasattr(self.vector_store, "get_collection_info")
            else {},
            "keyword_store": self.keyword_store.get_stats()
            if hasattr(self.keyword_store, "get_stats")
            else {},
            "graph_store": self.graph_store.get_stats()
            if hasattr(self.graph_store, "get_stats")
            else {},
        }


def test_pipeline():
    """测试完整 Pipeline"""
    print("=" * 70)
    print("端到端 RAG Pipeline 测试")
    print("=" * 70)

    # 创建 Pipeline
    pipeline = RAGPipeline()

    # 测试数据
    test_chunks = [
        {
            "content": "深圳市建设工程计价费率标准规定了企业管理费的计算方法。企业管理费是指建筑安装企业组织施工生产和经营管理所需的费用。",
            "doc_id": "sz_flbz_2023",
            "doc_title": "深圳市建设工程计价费率标准（2023）",
            "page": 1,
            "section": "总则",
            "chunk_type": "paragraph",
        },
        {
            "content": "企业管理费包括：1.管理人员工资；2.办公费；3.差旅交通费；4.固定资产使用费；5.工具用具使用费；6.劳动保险和职工福利费；7.劳动保护费；8.工会经费；9.职工教育经费；10.财产保险费；11.财务费；12.税金；13.其他。",
            "doc_id": "sz_flbz_2023",
            "doc_title": "深圳市建设工程计价费率标准（2023）",
            "page": 2,
            "section": "费用组成",
            "chunk_type": "list",
        },
        {
            "content": "企业管理费计算公式：企业管理费 = 计算基数 × 企业管理费费率。计算基数可以是人工费、人工费加机械费，或分部分项工程费。",
            "doc_id": "sz_flbz_2023",
            "doc_title": "深圳市建设工程计价费率标准（2023）",
            "page": 3,
            "section": "计算方法",
            "chunk_type": "paragraph",
        },
        {
            "content": "根据 HJ 2023 标准，环境保护费是指施工现场为达到环保部门要求所需要的各项费用。",
            "doc_id": "hj2023",
            "doc_title": "HJ 2023 环境保护标准",
            "page": 1,
            "section": "术语定义",
            "chunk_type": "paragraph",
        },
        {
            "content": "分部分项工程费是指各专业工程的分部分项工程应予列支的各项费用，由人工费、材料费、施工机具使用费、企业管理费和利润组成。",
            "doc_id": "sz_flbz_2023",
            "doc_title": "深圳市建设工程计价费率标准（2023）",
            "page": 4,
            "section": "工程费用",
            "chunk_type": "paragraph",
        },
    ]

    # 索引文档
    print("\n" + "=" * 70)
    print("阶段 1: 索引文档")
    print("=" * 70)

    pipeline.index_document("sz_flbz_2023", test_chunks[:3], build_graph=True)
    pipeline.index_document("hj2023", test_chunks[3:], build_graph=False)

    # 显示统计
    print("\n" + "=" * 70)
    print("存储统计")
    print("=" * 70)
    stats = pipeline.get_stats()
    print(json.dumps(stats, indent=2, ensure_ascii=False))

    # 测试查询
    print("\n" + "=" * 70)
    print("阶段 2: 执行查询")
    print("=" * 70)

    test_queries = [
        "企业管理费包括哪些内容",
        "企业管理费怎么计算",
        "HJ 2023 是什么标准",
        "分部分项工程费由什么组成",
    ]

    for query in test_queries:
        print(f"\n{'=' * 70}")
        response = pipeline.query(
            query=query, top_k=3, context_strategy=ContextStrategy.SURROUNDING
        )

        print(f"\n查询: {response.query}")
        print(f"总耗时: {response.total_time_ms:.2f}ms")
        print(f"\n检索结果:")

        for i, doc in enumerate(response.documents, 1):
            print(f"\n  [{i}] 分数: {doc.final_score:.4f}")
            print(f"      来源: {doc.title} 第{doc.page}页")
            print(f"      内容: {doc.content[:80]}...")
            print(
                f"      精排分: {doc.rerank_score:.4f}, 向量分: {doc.vector_score:.4f}"
            )

        print(f"\n上下文预览:")
        print(response.context[:300] + "...")

    print("\n" + "=" * 70)
    print("测试完成!")
    print("=" * 70)


if __name__ == "__main__":
    test_pipeline()
