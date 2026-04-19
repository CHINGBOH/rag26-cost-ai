#!/usr/bin/env python3
"""
关键词检索客户端 - Elasticsearch 实现
支持 BM25 关键词匹配和布尔查询
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import json


@dataclass
class KeywordDocument:
    """关键词文档"""

    id: str
    content: str
    doc_id: str
    title: str = ""
    page: int = 0
    section: str = ""
    chunk_type: str = "paragraph"
    score: float = 0.0
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class ElasticsearchClient:
    """
    Elasticsearch 客户端

    功能:
    - BM25 关键词检索
    - 布尔查询
    - 高亮显示
    - 聚合统计
    """

    def __init__(
        self, hosts: List[str] = None, index_name: str = "documents", timeout: int = 30
    ):
        self.hosts = hosts or ["http://localhost:9200"]
        self.index_name = index_name
        self.timeout = timeout
        self._client = None
        self._connect()

    def _connect(self):
        """连接到 Elasticsearch"""
        try:
            from elasticsearch import Elasticsearch

            self._client = Elasticsearch(
                self.hosts, timeout=self.timeout, retry_on_timeout=True
            )

            # 检查连接
            if self._client.ping():
                print(f"✓ 连接到 Elasticsearch: {self.hosts}")
                self._ensure_index()
            else:
                raise ConnectionError("无法 ping 通 Elasticsearch")

        except ImportError:
            print("⚠ 未安装 elasticsearch，使用内存模式")
            self._client = None
            self._memory_store: Dict[str, KeywordDocument] = {}
        except Exception as e:
            print(f"⚠ ES 连接失败: {e}，使用内存模式")
            self._client = None
            self._memory_store: Dict[str, KeywordDocument] = {}

    def _ensure_index(self):
        """确保索引存在"""
        try:
            if not self._client.indices.exists(index=self.index_name):
                # 创建索引并配置中文分析器
                settings = {
                    "settings": {
                        "number_of_shards": 5,
                        "number_of_replicas": 1,
                        "analysis": {
                            "analyzer": {
                                "ik_smart": {"type": "custom", "tokenizer": "ik_smart"},
                                "ik_max_word": {
                                    "type": "custom",
                                    "tokenizer": "ik_max_word",
                                },
                            }
                        },
                    },
                    "mappings": {
                        "properties": {
                            "content": {
                                "type": "text",
                                "analyzer": "ik_max_word",
                                "search_analyzer": "ik_smart",
                                "fields": {"keyword": {"type": "keyword"}},
                            },
                            "title": {
                                "type": "text",
                                "analyzer": "ik_max_word",
                                "boost": 2.0,  # 标题权重更高
                            },
                            "doc_id": {"type": "keyword"},
                            "page": {"type": "integer"},
                            "section": {"type": "keyword"},
                            "chunk_type": {"type": "keyword"},
                            "publish_date": {"type": "date"},
                        }
                    },
                }

                self._client.indices.create(index=self.index_name, body=settings)
                print(f"✓ 创建索引: {self.index_name}")

        except Exception as e:
            print(f"创建索引失败: {e}")

    def is_connected(self) -> bool:
        """检查是否已连接"""
        if self._client is None:
            return False
        try:
            return self._client.ping()
        except Exception:
            return False

    def index(self, documents: List[KeywordDocument]) -> bool:
        """
        索引文档

        Args:
            documents: 文档列表

        Returns:
            是否成功
        """
        if not documents:
            return True

        if self._client is None:
            # 内存模式
            for doc in documents:
                self._memory_store[doc.id] = doc
            return True

        try:
            from elasticsearch.helpers import bulk

            actions = []
            for doc in documents:
                action = {
                    "_index": self.index_name,
                    "_id": doc.id,
                    "_source": {
                        "content": doc.content,
                        "doc_id": doc.doc_id,
                        "title": doc.title,
                        "page": doc.page,
                        "section": doc.section,
                        "chunk_type": doc.chunk_type,
                        **doc.metadata,
                    },
                }
                actions.append(action)

            success, errors = bulk(self._client, actions, raise_on_error=False)

            if errors:
                print(f"⚠ 部分文档索引失败: {len(errors)} 个错误")

            return success > 0

        except Exception as e:
            print(f"索引失败: {e}")
            return False

    def search(
        self,
        query: str,
        top_k: int = 20,
        min_score: float = 1.0,
        highlight: bool = True,
        filters: Optional[Dict] = None,
    ) -> List[KeywordDocument]:
        """
        BM25 关键词搜索

        BM25 公式:
        score(D,Q) = Σ IDF(q_i) × [f(q_i,D) × (k1+1)] / [f(q_i,D) + k1 × (1-b+b×|D|/avgdl)]

        其中:
        - IDF(q_i) = log((N - n(q_i) + 0.5) / (n(q_i) + 0.5))
        - f(q_i,D): 词项在文档中的频率
        - |D|: 文档长度
        - avgdl: 平均文档长度
        - k1=1.2, b=0.75 (默认参数)

        Args:
            query: 查询文本
            top_k: 返回结果数量
            min_score: 最小分数阈值
            highlight: 是否返回高亮
            filters: 过滤条件

        Returns:
            文档列表
        """
        if self._client is None:
            return self._memory_search(query, top_k, min_score)

        try:
            # 构建查询
            search_body = {
                "query": {
                    "bool": {
                        "must": [
                            {
                                "multi_match": {
                                    "query": query,
                                    "fields": ["title^2", "content"],  # 标题权重 2 倍
                                    "type": "best_fields",
                                    "operator": "or",
                                }
                            }
                        ]
                    }
                },
                "size": top_k,
                "min_score": min_score,
                "sort": [{"_score": "desc"}],
            }

            # 添加过滤条件
            if filters:
                search_body["query"]["bool"]["filter"] = self._build_filters(filters)

            # 添加高亮
            if highlight:
                search_body["highlight"] = {
                    "fields": {
                        "content": {
                            "fragment_size": 150,
                            "number_of_fragments": 3,
                            "pre_tags": ["**"],
                            "post_tags": ["**"],
                        },
                        "title": {
                            "fragment_size": 100,
                            "number_of_fragments": 1,
                            "pre_tags": ["**"],
                            "post_tags": ["**"],
                        },
                    }
                }

            response = self._client.search(index=self.index_name, body=search_body)

            documents = []
            for hit in response["hits"]["hits"]:
                source = hit["_source"]
                highlight_text = ""

                if highlight and "highlight" in hit:
                    if "content" in hit["highlight"]:
                        highlight_text = " ... ".join(hit["highlight"]["content"])
                    elif "title" in hit["highlight"]:
                        highlight_text = " ".join(hit["highlight"]["title"])

                doc = KeywordDocument(
                    id=hit["_id"],
                    content=highlight_text or source.get("content", ""),
                    doc_id=source.get("doc_id", ""),
                    title=source.get("title", ""),
                    page=source.get("page", 0),
                    section=source.get("section", ""),
                    chunk_type=source.get("chunk_type", "paragraph"),
                    score=hit["_score"],
                    metadata={
                        k: v
                        for k, v in source.items()
                        if k
                        not in [
                            "content",
                            "doc_id",
                            "title",
                            "page",
                            "section",
                            "chunk_type",
                        ]
                    },
                )
                documents.append(doc)

            return documents

        except Exception as e:
            print(f"搜索失败: {e}")
            return []

    def _memory_search(
        self, query: str, top_k: int, min_score: float
    ) -> List[KeywordDocument]:
        """内存模式搜索 - 简单关键词匹配"""
        query_terms = query.lower().split()
        results = []

        for doc in self._memory_store.values():
            content_lower = doc.content.lower()

            # 简单匹配分数
            score = 0
            for term in query_terms:
                if term in content_lower:
                    score += 1

            if score >= min_score:
                doc.score = score
                results.append(doc)

        # 按分数排序
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    def _build_filters(self, filters: Dict) -> List[Dict]:
        """构建过滤条件"""
        es_filters = []

        for key, value in filters.items():
            if isinstance(value, list):
                es_filters.append({"terms": {key: value}})
            elif isinstance(value, dict):
                # 范围查询
                if "gte" in value or "lte" in value:
                    es_filters.append({"range": {key: value}})
            else:
                es_filters.append({"term": {key: value}})

        return es_filters

    def boolean_search(
        self,
        must: List[str] = None,
        should: List[str] = None,
        must_not: List[str] = None,
        top_k: int = 20,
    ) -> List[KeywordDocument]:
        """
        布尔查询

        Args:
            must: 必须包含的词
            should: 应该包含的词
            must_not: 必须不包含的词
            top_k: 返回结果数量

        Returns:
            文档列表
        """
        if self._client is None:
            return []

        bool_query = {"bool": {}}

        if must:
            bool_query["bool"]["must"] = [{"match": {"content": term}} for term in must]
        if should:
            bool_query["bool"]["should"] = [
                {"match": {"content": term}} for term in should
            ]
            bool_query["bool"]["minimum_should_match"] = 1
        if must_not:
            bool_query["bool"]["must_not"] = [
                {"match": {"content": term}} for term in must_not
            ]

        try:
            response = self._client.search(
                index=self.index_name,
                body={"query": bool_query, "size": top_k, "sort": [{"_score": "desc"}]},
            )

            documents = []
            for hit in response["hits"]["hits"]:
                source = hit["_source"]
                doc = KeywordDocument(
                    id=hit["_id"],
                    content=source.get("content", ""),
                    doc_id=source.get("doc_id", ""),
                    title=source.get("title", ""),
                    page=source.get("page", 0),
                    section=source.get("section", ""),
                    chunk_type=source.get("chunk_type", "paragraph"),
                    score=hit["_score"],
                    metadata={},
                )
                documents.append(doc)

            return documents

        except Exception as e:
            print(f"布尔搜索失败: {e}")
            return []

    def delete(self, doc_ids: List[str]) -> bool:
        """删除文档"""
        if not doc_ids:
            return True

        if self._client is None:
            for doc_id in doc_ids:
                if doc_id in self._memory_store:
                    del self._memory_store[doc_id]
            return True

        try:
            from elasticsearch.helpers import bulk

            actions = [
                {"_op_type": "delete", "_index": self.index_name, "_id": doc_id}
                for doc_id in doc_ids
            ]

            bulk(self._client, actions)
            return True

        except Exception as e:
            print(f"删除失败: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """获取索引统计"""
        if self._client is None:
            return {
                "index": self.index_name,
                "docs_count": len(self._memory_store),
                "mode": "memory",
            }

        try:
            stats = self._client.indices.stats(index=self.index_name)
            return {
                "index": self.index_name,
                "docs_count": stats["indices"][self.index_name]["total"]["docs"][
                    "count"
                ],
                "store_size": stats["indices"][self.index_name]["total"]["store"][
                    "size_in_bytes"
                ],
            }
        except Exception as e:
            return {"error": str(e)}


class KeywordStorePipeline:
    """
    关键词存储管道

    整合文档处理和 Elasticsearch 存储
    """

    def __init__(self, es_client: Optional[ElasticsearchClient] = None):
        self.es = es_client or ElasticsearchClient()

    def index_documents(self, chunks: List[Dict[str, Any]]) -> bool:
        """
        索引文档片段

        Args:
            chunks: 文档片段列表

        Returns:
            是否成功
        """
        import hashlib

        documents = []
        for chunk in chunks:
            content = chunk["content"]
            doc_id = chunk.get("doc_id", "unknown")

            # 生成唯一 ID
            unique_id = hashlib.md5(f"{doc_id}:{content[:50]}".encode()).hexdigest()

            doc = KeywordDocument(
                id=unique_id,
                content=content,
                doc_id=doc_id,
                title=chunk.get("doc_title", ""),
                page=chunk.get("page", 0),
                section=chunk.get("section", ""),
                chunk_type=chunk.get("chunk_type", "paragraph"),
                metadata=chunk.get("metadata", {}),
            )
            documents.append(doc)

        return self.es.index(documents)

    def search(
        self,
        query: str,
        top_k: int = 20,
        min_score: float = 1.0,
        filters: Optional[Dict] = None,
    ) -> List[KeywordDocument]:
        """
        关键词搜索

        Args:
            query: 查询文本
            top_k: 返回结果数量
            min_score: 最小分数
            filters: 过滤条件

        Returns:
            文档列表
        """
        return self.es.search(query, top_k, min_score, filters=filters)


if __name__ == "__main__":
    # 测试代码
    print("=" * 60)
    print("关键词存储测试")
    print("=" * 60)

    # 创建服务
    es = ElasticsearchClient()
    pipeline = KeywordStorePipeline(es)

    # 测试数据
    test_chunks = [
        {
            "content": "深圳市建设工程计价费率标准规定了企业管理费的计算方法",
            "doc_id": "sz_flbz_2023",
            "doc_title": "深圳市建设工程计价费率标准",
            "page": 1,
            "section": "总则",
            "chunk_type": "paragraph",
        },
        {
            "content": "企业管理费包括管理人员工资、办公费、差旅交通费等",
            "doc_id": "sz_flbz_2023",
            "doc_title": "深圳市建设工程计价费率标准",
            "page": 2,
            "section": "费用组成",
            "chunk_type": "paragraph",
        },
        {
            "content": "分部分项工程费由人工费、材料费、机械费组成",
            "doc_id": "sz_flbz_2023",
            "doc_title": "深圳市建设工程计价费率标准",
            "page": 3,
            "section": "工程费用",
            "chunk_type": "paragraph",
        },
    ]

    # 索引
    print("\n1. 索引测试文档...")
    pipeline.index_documents(test_chunks)

    # 搜索
    print("\n2. 测试搜索...")
    query = "企业管理费"
    results = pipeline.search(query, top_k=5)

    print(f"\n查询: {query}")
    print(f"结果数: {len(results)}")

    for doc in results:
        print(f"\n  分数: {doc.score:.4f}")
        print(f"  内容: {doc.content[:50]}...")
        print(f"  来源: {doc.title} 第{doc.page}页")

    # 布尔搜索测试
    print("\n3. 测试布尔搜索...")
    bool_results = es.boolean_search(
        must=["企业管理费"], should=["计算", "方法"], top_k=5
    )
    print(f"布尔搜索结果: {len(bool_results)} 个")
