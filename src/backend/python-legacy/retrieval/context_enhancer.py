#!/usr/bin/env python3
"""
上下文增强模块
为检索结果添加上下文信息，提升生成质量
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum


class ContextStrategy(Enum):
    """上下文增强策略"""

    NONE = "none"  # 不增强
    SURROUNDING = "surrounding"  # 添加前后段落
    SECTION = "section"  # 添加整个章节
    HIERARCHY = "hierarchy"  # 添加层级结构
    ENTITY_LINK = "entity_link"  # 添加实体链接
    FULL = "full"  # 全部增强


@dataclass
class ContextChunk:
    """上下文片段"""

    content: str
    chunk_type: str  # 'before', 'current', 'after', 'parent', 'related'
    doc_id: str
    page: int
    section: str
    relevance_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EnhancedResult:
    """增强后的检索结果"""

    original_content: str
    context_chunks: List[ContextChunk]
    entities: List[Dict[str, Any]]
    related_documents: List[Dict[str, Any]]
    full_context: str = ""  # 拼接后的完整上下文


class ContextEnhancer:
    """
    上下文增强器

    功能:
    - 添加前后段落
    - 添加章节上下文
    - 添加实体链接
    - 添加相关文档
    """

    def __init__(
        self,
        vector_store=None,
        graph_store=None,
        max_context_length: int = 2000,
        surrounding_window: int = 2,
    ):
        self.vector_store = vector_store
        self.graph_store = graph_store
        self.max_context_length = max_context_length
        self.surrounding_window = surrounding_window

    def enhance(
        self,
        doc_id: str,
        chunk_id: str,
        content: str,
        strategy: ContextStrategy = ContextStrategy.SURROUNDING,
        query: str = "",
    ) -> EnhancedResult:
        """
        增强检索结果上下文

        Args:
            doc_id: 文档 ID
            chunk_id: 片段 ID
            content: 当前内容
            strategy: 增强策略
            query: 原始查询（用于相关性排序）

        Returns:
            增强后的结果
        """
        context_chunks = []
        entities = []
        related_docs = []

        # 1. 添加前后段落
        if strategy in [ContextStrategy.SURROUNDING, ContextStrategy.FULL]:
            surrounding = self._get_surrounding_chunks(doc_id, chunk_id)
            context_chunks.extend(surrounding)

        # 2. 添加章节上下文
        if strategy in [ContextStrategy.SECTION, ContextStrategy.FULL]:
            section_context = self._get_section_context(doc_id, chunk_id)
            context_chunks.extend(section_context)

        # 3. 添加层级结构
        if strategy in [ContextStrategy.HIERARCHY, ContextStrategy.FULL]:
            hierarchy = self._get_hierarchy_context(doc_id, chunk_id)
            context_chunks.extend(hierarchy)

        # 4. 提取和链接实体
        if strategy in [ContextStrategy.ENTITY_LINK, ContextStrategy.FULL]:
            entities = self._extract_and_link_entities(content)
            related_docs = self._get_entity_related_docs(entities)

        # 5. 构建完整上下文
        full_context = self._build_full_context(content, context_chunks)

        return EnhancedResult(
            original_content=content,
            context_chunks=context_chunks,
            entities=entities,
            related_documents=related_docs,
            full_context=full_context,
        )

    def _get_surrounding_chunks(self, doc_id: str, chunk_id: str) -> List[ContextChunk]:
        """
        获取前后相邻的段落

        例如: 如果 window=2，获取前2段和后2段
        """
        chunks = []

        # 解析 chunk_id 获取页码和序号
        # 格式: chunk_{page_num}_{chunk_num}
        try:
            parts = chunk_id.split("_")
            if len(parts) >= 3:
                page_num = int(parts[1])
                chunk_num = int(parts[2])
            else:
                return chunks
        except Exception:
            return chunks

        # 从向量存储获取相邻片段
        if self.vector_store:
            for offset in range(-self.surrounding_window, self.surrounding_window + 1):
                if offset == 0:
                    continue

                neighbor_page = page_num
                neighbor_chunk = chunk_num + offset

                # 处理跨页情况（简化处理）
                if neighbor_chunk < 1:
                    neighbor_page -= 1
                    neighbor_chunk = 10  # 假设每页最多10个片段

                neighbor_id = f"chunk_{neighbor_page}_{neighbor_chunk}"

                # 这里应该查询实际存储
                # 模拟数据
                chunk = ContextChunk(
                    content=f"[相邻片段 {neighbor_id} 的内容]",
                    chunk_type="before" if offset < 0 else "after",
                    doc_id=doc_id,
                    page=neighbor_page,
                    section="",
                    relevance_score=0.5,
                )
                chunks.append(chunk)

        return chunks

    def _get_section_context(self, doc_id: str, chunk_id: str) -> List[ContextChunk]:
        """获取同一章节的其它片段"""
        chunks = []

        # 从存储获取章节信息
        # 这里简化处理
        section_chunk = ContextChunk(
            content="[章节概述信息]",
            chunk_type="section_summary",
            doc_id=doc_id,
            page=0,
            section="当前章节",
            relevance_score=0.7,
        )
        chunks.append(section_chunk)

        return chunks

    def _get_hierarchy_context(self, doc_id: str, chunk_id: str) -> List[ContextChunk]:
        """获取层级结构上下文（父章节、子章节）"""
        chunks = []

        # 父章节
        parent_chunk = ContextChunk(
            content="[父章节标题和内容概述]",
            chunk_type="parent",
            doc_id=doc_id,
            page=0,
            section="父章节",
            relevance_score=0.6,
        )
        chunks.append(parent_chunk)

        return chunks

    def _extract_and_link_entities(self, content: str) -> List[Dict[str, Any]]:
        """
        提取实体并链接到知识图谱

        返回实体列表，包含名称、类型、相关文档等
        """
        entities = []

        # 简单的实体提取（实际应使用 NER 模型）
        import re

        patterns = [
            (r"[\u4e00-\u9fa5]{2,10}(?:公司|集团|企业)", "company"),
            (r"[\u4e00-\u9fa5]{2,8}(?:标准|规范|规定)", "standard"),
            (r"HJ\d+(?:\.\d+)?", "standard_code"),
            (r"(?:人工费|材料费|机械费|企业管理费)", "cost_concept"),
        ]

        for pattern, entity_type in patterns:
            matches = re.finditer(pattern, content)
            for match in matches:
                entity = {
                    "name": match.group(),
                    "type": entity_type,
                    "position": match.span(),
                    "related_docs": [],
                }
                entities.append(entity)

        # 从图谱获取实体信息
        if self.graph_store:
            for entity in entities:
                graph_entities = self.graph_store.search_entities(
                    entity["name"], entity_type=entity["type"], top_k=1
                )
                if graph_entities:
                    graph_entity = graph_entities[0]
                    entity["id"] = graph_entity.id
                    entity["properties"] = graph_entity.properties

                    # 获取相关文档
                    neighbors = self.graph_store.get_entity_neighbors(
                        graph_entity.name, rel_types=["MENTIONED_IN"]
                    )
                    entity["related_entities"] = [
                        {"name": n.name, "type": n.entity_type} for n in neighbors[:5]
                    ]

        return entities

    def _get_entity_related_docs(
        self, entities: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """获取与实体相关的其它文档"""
        related_docs = []

        if not self.graph_store or not entities:
            return related_docs

        # 获取实体名称列表
        entity_names = [e["name"] for e in entities]

        # 从图谱扩展
        graph_docs = self.graph_store.expand_entities(entity_names, depth=2, top_k=5)

        for doc in graph_docs:
            related_docs.append(
                {
                    "doc_id": doc.doc_id,
                    "title": doc.title,
                    "relevance": doc.relevance_score,
                    "related_entities": doc.related_entities,
                }
            )

        return related_docs

    def _build_full_context(
        self, original_content: str, context_chunks: List[ContextChunk]
    ) -> str:
        """
        构建完整上下文字符串

        按优先级排序并截断到最大长度
        """
        # 按相关性排序
        sorted_chunks = sorted(
            context_chunks, key=lambda x: x.relevance_score, reverse=True
        )

        parts = []
        current_length = len(original_content)

        # 添加原始内容
        parts.append(f"[当前片段]\n{original_content}\n")

        # 添加上下文（直到达到最大长度）
        for chunk in sorted_chunks:
            chunk_text = f"[{chunk.chunk_type}]\n{chunk.content}\n"
            chunk_length = len(chunk_text)

            if current_length + chunk_length > self.max_context_length:
                break

            parts.append(chunk_text)
            current_length += chunk_length

        return "\n---\n".join(parts)

    def enhance_batch(
        self,
        results: List[Dict[str, Any]],
        strategy: ContextStrategy = ContextStrategy.SURROUNDING,
        query: str = "",
    ) -> List[EnhancedResult]:
        """
        批量增强检索结果

        Args:
            results: 检索结果列表
            strategy: 增强策略
            query: 原始查询

        Returns:
            增强后的结果列表
        """
        enhanced = []

        for result in results:
            enhanced_result = self.enhance(
                doc_id=result.get("doc_id", ""),
                chunk_id=result.get("id", ""),
                content=result.get("content", ""),
                strategy=strategy,
                query=query,
            )
            enhanced.append(enhanced_result)

        return enhanced


class RAGContextBuilder:
    """
    RAG 上下文构建器

    整合多个检索结果的上下文，构建最终输入给 LLM 的上下文
    """

    def __init__(self, max_total_length: int = 4000, max_chunks_per_doc: int = 3):
        self.max_total_length = max_total_length
        self.max_chunks_per_doc = max_chunks_per_doc

    def build(self, enhanced_results: List[EnhancedResult], query: str) -> str:
        """
        构建 RAG 上下文

        Args:
            enhanced_results: 增强后的检索结果
            query: 用户查询

        Returns:
            构建好的上下文字符串
        """
        if not enhanced_results:
            return ""

        sections = []
        sections.append(f"用户查询: {query}\n")
        sections.append("=" * 50)

        # 按文档分组
        doc_groups = {}
        for result in enhanced_results:
            doc_id = (
                result.context_chunks[0].doc_id if result.context_chunks else "unknown"
            )
            if doc_id not in doc_groups:
                doc_groups[doc_id] = []
            doc_groups[doc_id].append(result)

        # 构建上下文
        total_length = 0

        for doc_id, results in doc_groups.items():
            doc_section = f"\n[来源文档: {doc_id}]\n"
            doc_section += "-" * 40 + "\n"

            # 限制每个文档的片段数
            for i, result in enumerate(results[: self.max_chunks_per_doc]):
                chunk_text = f"\n片段 {i + 1}:\n{result.full_context}\n"

                if total_length + len(chunk_text) > self.max_total_length:
                    doc_section += "\n[更多内容省略...]\n"
                    break

                doc_section += chunk_text
                total_length += len(chunk_text)

            sections.append(doc_section)

            if total_length >= self.max_total_length:
                break

        # 添加引用信息
        sections.append("\n" + "=" * 50)
        sections.append("引用来源:")
        for doc_id in list(doc_groups.keys())[:5]:
            sections.append(f"  - {doc_id}")

        return "\n".join(sections)


if __name__ == "__main__":
    # 测试代码
    print("=" * 60)
    print("上下文增强测试")
    print("=" * 60)

    enhancer = ContextEnhancer()

    # 测试数据
    test_doc_id = "sz_flbz_2023"
    test_chunk_id = "chunk_2_5"
    test_content = "企业管理费包括管理人员工资、办公费、差旅交通费等"

    # 测试不同策略
    for strategy in ContextStrategy:
        print(f"\n策略: {strategy.value}")
        print("-" * 40)

        result = enhancer.enhance(
            doc_id=test_doc_id,
            chunk_id=test_chunk_id,
            content=test_content,
            strategy=strategy,
            query="企业管理费怎么计算",
        )

        print(f"原始内容: {result.original_content[:50]}...")
        print(f"上下文片段数: {len(result.context_chunks)}")
        print(f"提取实体数: {len(result.entities)}")
        print(f"相关文档数: {len(result.related_documents)}")

        if result.full_context:
            print(f"\n完整上下文预览:")
            print(result.full_context[:200] + "...")

    # 测试 RAG 上下文构建
    print("\n" + "=" * 60)
    print("RAG 上下文构建测试")
    print("=" * 60)

    builder = RAGContextBuilder()

    # 模拟多个增强结果
    mock_results = [
        EnhancedResult(
            original_content="企业管理费包括管理人员工资、办公费",
            context_chunks=[
                ContextChunk(
                    content="前一段内容...",
                    chunk_type="before",
                    doc_id="sz_flbz_2023",
                    page=1,
                    section="费用组成",
                )
            ],
            entities=[{"name": "企业管理费", "type": "cost_concept"}],
            related_documents=[],
            full_context="[当前片段]\n企业管理费包括管理人员工资、办公费\n\n[before]\n前一段内容...",
        ),
        EnhancedResult(
            original_content="企业管理费计算公式为：人工费×费率",
            context_chunks=[],
            entities=[],
            related_documents=[],
            full_context="[当前片段]\n企业管理费计算公式为：人工费×费率",
        ),
    ]

    rag_context = builder.build(mock_results, "企业管理费怎么计算")
    print("\n生成的 RAG 上下文:")
    print(rag_context[:500] + "...")
