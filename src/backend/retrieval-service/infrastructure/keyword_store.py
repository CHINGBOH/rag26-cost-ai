"""
基础设施层 - 关键词存储适配器
实现 KeywordStorePort 接口
"""

from typing import List
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

from domain.models import Document, DocumentChunk
from domain.ports import KeywordStorePort
from config.settings import KeywordStoreConfig


class ElasticsearchKeywordStoreAdapter(KeywordStorePort):
    """
    Elasticsearch 关键词存储适配器

    使用 BM25 算法进行关键词检索
    """

    def __init__(self, config: KeywordStoreConfig):
        self.config = config
        self._client: Elasticsearch | None = None
        self._connect()

    def _connect(self) -> None:
        """连接到 Elasticsearch"""
        try:
            self._client = Elasticsearch(self.config.hosts, timeout=30, retry_on_timeout=True)

            # 确保索引存在
            if not self._client.indices.exists(index=self.config.index_name):
                self._create_index()

        except Exception as e:
            print(f"ES 连接失败: {e}")
            self._client = None

    def _create_index(self) -> None:
        """创建索引并配置中文分析器"""
        settings = {
            "settings": {
                "number_of_shards": 5,
                "number_of_replicas": 1,
                "analysis": {
                    "analyzer": {
                        "ik_smart": {"type": "custom", "tokenizer": "ik_smart"},
                        "ik_max_word": {"type": "custom", "tokenizer": "ik_max_word"},
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
                    "title": {"type": "text", "analyzer": "ik_max_word", "boost": 2.0},
                    "doc_id": {"type": "keyword"},
                    "page": {"type": "integer"},
                    "section": {"type": "keyword"},
                    "chunk_type": {"type": "keyword"},
                }
            },
        }

        self._client.indices.create(index=self.config.index_name, body=settings)

    def is_available(self) -> bool:
        """检查是否可用"""
        if self._client is None:
            return False
        try:
            return self._client.ping()
        except:
            return False

    async def search(self, query: str, top_k: int = 20, min_score: float = 1.0) -> List[Document]:
        """
        BM25 关键词搜索

        BM25公式: score(D,Q) = Σ IDF(q_i) × [f(q_i,D) × (k1+1)] / [f(q_i,D) + k1 × (1-b+b×|D|/avgdl)]
        """
        if not self.is_available():
            return []

        try:
            search_body = {
                "query": {
                    "multi_match": {
                        "query": query,
                        "fields": ["title^2", "content"],
                        "type": "best_fields",
                        "operator": "or",
                    }
                },
                "size": top_k,
                "min_score": min_score,
            }

            response = self._client.search(index=self.config.index_name, body=search_body)

            documents = []
            for hit in response["hits"]["hits"]:
                source = hit["_source"]
                doc = Document(
                    id=hit["_id"],
                    content=source.get("content", ""),
                    doc_id=source.get("doc_id", ""),
                    title=source.get("title", ""),
                    page=source.get("page", 0),
                    section=source.get("section", ""),
                    chunk_type=source.get("chunk_type", "paragraph"),
                    bm25_score=hit["_score"],
                    metadata={},
                )
                documents.append(doc)

            return documents

        except Exception as e:
            print(f"关键词搜索失败: {e}")
            return []

    async def index(self, documents: List[DocumentChunk]) -> bool:
        """索引文档"""
        if not self.is_available():
            return False

        try:
            actions = []
            for doc in documents:
                action = {
                    "_index": self.config.index_name,
                    "_id": doc.id,
                    "_source": {
                        "content": doc.content,
                        "doc_id": doc.doc_id,
                        "title": doc.doc_title,
                        "page": doc.page,
                        "section": doc.section,
                        "chunk_type": doc.chunk_type,
                        **doc.metadata,
                    },
                }
                actions.append(action)

            success, errors = bulk(self._client, actions, raise_on_error=False)
            return success > 0

        except Exception as e:
            print(f"索引失败: {e}")
            return False

    async def delete(self, doc_ids: List[str]) -> bool:
        """删除文档"""
        if not self.is_available():
            return False

        try:
            actions = [
                {"_op_type": "delete", "_index": self.config.index_name, "_id": doc_id}
                for doc_id in doc_ids
            ]
            bulk(self._client, actions)
            return True

        except Exception as e:
            print(f"删除失败: {e}")
            return False


class MemoryKeywordStoreAdapter(KeywordStorePort):
    """
    内存关键词存储适配器

    用于测试和开发环境
    """

    def __init__(self, config: KeywordStoreConfig | None = None):
        self._storage: dict[str, DocumentChunk] = {}

    def is_available(self) -> bool:
        return True

    async def search(self, query: str, top_k: int = 20, min_score: float = 1.0) -> List[Document]:
        """简单关键词匹配"""
        query_terms = query.lower().split()
        results = []

        for doc in self._storage.values():
            content_lower = doc.content.lower()

            # 简单匹配分数
            score = 0
            for term in query_terms:
                if term in content_lower:
                    score += 1

            if score >= min_score:
                document = Document(
                    id=doc.id,
                    content=doc.content,
                    doc_id=doc.doc_id,
                    title=doc.doc_title,
                    page=doc.page,
                    section=doc.section,
                    chunk_type=doc.chunk_type,
                    bm25_score=score,
                    metadata=doc.metadata,
                )
                results.append(document)

        # 按分数排序
        results.sort(key=lambda x: x.bm25_score, reverse=True)
        return results[:top_k]

    async def index(self, documents: List[DocumentChunk]) -> bool:
        """索引到内存"""
        for doc in documents:
            self._storage[doc.id] = doc
        return True

    async def delete(self, doc_ids: List[str]) -> bool:
        """从内存删除"""
        for doc_id in doc_ids:
            keys_to_delete = [k for k in self._storage.keys() if self._storage[k].doc_id == doc_id]
            for k in keys_to_delete:
                del self._storage[k]
        return True
