"""
基础设施层 - AI模型适配器
实现 EmbeddingModelPort 和 RerankModelPort 接口
"""

from typing import List
import numpy as np
import os
from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch
import os

from domain.models import Document
from domain.ports import EmbeddingModelPort, RerankModelPort
from config.settings import EmbeddingModelConfig, RerankModelConfig


class EmbeddingModelAdapter(EmbeddingModelPort):
    """
    Embedding模型适配器

    使用 sentence-transformers 实现文本嵌入
    """

    def __init__(self, config: EmbeddingModelConfig):
        self.config = config
        self._model: SentenceTransformer | None = None
        self._load_model()

    def _load_model(self) -> None:
        """加载模型"""
        try:
            # 设置模型缓存路径
            cache_dir = os.environ.get("SENTENCE_TRANSFORMERS_HOME", "/home/l/models")

            self._model = SentenceTransformer(
                self.config.name, device=self.config.device, cache_folder=cache_dir
            )
            torch.set_num_threads(max(1, os.cpu_count() // 2))
            print(f"✓ Embedding模型加载完成: {self.config.name} (threads={torch.get_num_threads()})")
        except Exception as e:
            print(f"✗ Embedding模型加载失败: {e}")
            self._model = None

    @property
    def dimension(self) -> int:
        """向量维度"""
        if self._model:
            return self._model.get_sentence_embedding_dimension()
        return 1024  # 默认值

    def encode(self, texts: str | List[str]) -> np.ndarray:
        """
        编码文本为向量

        Args:
            texts: 文本或文本列表

        Returns:
            向量数组
        """
        if self._model is None:
            # 模拟嵌入
            if isinstance(texts, str):
                return np.random.randn(self.dimension).astype(np.float32)
            else:
                return np.random.randn(len(texts), self.dimension).astype(np.float32)

        try:
            embeddings = self._model.encode(
                texts,
                normalize_embeddings=self.config.normalize_embeddings,
                show_progress_bar=False,
                batch_size=self.config.batch_size,
            )
            return embeddings

        except Exception as e:
            print(f"编码失败: {e}")
            if isinstance(texts, str):
                return np.random.randn(self.dimension).astype(np.float32)
            else:
                return np.random.randn(len(texts), self.dimension).astype(np.float32)

    def encode_queries(self, queries: str | List[str]) -> np.ndarray:
        """
        编码查询（添加指令前缀）

        BGE模型推荐为查询添加指令
        """
        instruction = "Represent this sentence for searching relevant passages:"

        if isinstance(queries, str):
            texts = f"{instruction} {queries}"
        else:
            texts = [f"{instruction} {q}" for q in queries]

        return self.encode(texts)


class RerankModelAdapter(RerankModelPort):
    """
    Rerank模型适配器

    使用 Cross-Encoder 实现精排
    """

    def __init__(self, config: RerankModelConfig):
        self.config = config
        self._tokenizer = None
        self._model = None
        self._load_model()

    def _load_model(self) -> None:
        """加载模型"""
        try:
            cache_dir = os.environ.get("HF_HOME", "/home/l/models")

            self._tokenizer = AutoTokenizer.from_pretrained(self.config.name, cache_dir=cache_dir)
            self._model = AutoModelForSequenceClassification.from_pretrained(
                self.config.name, cache_dir=cache_dir
            )
            self._model.to(self.config.device)
            self._model.eval()

            print(f"✓ Rerank模型加载完成: {self.config.name}")

        except Exception as e:
            print(f"✗ Rerank模型加载失败: {e}")
            self._tokenizer = None
            self._model = None

    def is_loaded(self) -> bool:
        """检查模型是否加载"""
        return self._model is not None and self._tokenizer is not None

    def rerank(self, query: str, candidates: List[Document]) -> List[Document]:
        """
        精排候选文档

        Args:
            query: 查询文本
            candidates: 候选文档列表

        Returns:
            按精排分数排序的文档列表
        """
        if not candidates:
            return []

        if not self.is_loaded():
            # 模型未加载，返回原始顺序
            return candidates

        try:
            # 构造 (query, doc) 对
            pairs = [[query, doc.content] for doc in candidates]

            # 批量推理
            all_scores = []
            batch_size = self.config.batch_size

            for i in range(0, len(pairs), batch_size):
                batch = pairs[i : i + batch_size]

                inputs = self._tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    return_tensors="pt",
                    max_length=self.config.max_length,
                )
                inputs = {k: v.to(self.config.device) for k, v in inputs.items()}

                with torch.no_grad():
                    outputs = self._model(**inputs)
                    scores = outputs.logits.squeeze(-1)
                    all_scores.extend(scores.cpu().tolist())

            # 设置精排分数
            for doc, score in zip(candidates, all_scores):
                doc.rerank_score = score

            # 按精排分数排序
            return sorted(candidates, key=lambda x: x.rerank_score, reverse=True)

        except Exception as e:
            print(f"精排失败: {e}")
            return candidates
