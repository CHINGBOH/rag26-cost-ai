"""
Embedding 服务
管理文本向量化
"""

import os
import logging
from typing import List
import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Embedding 服务 - 支持多种模型"""

    def __init__(
        self, model_name: str = "BAAI/bge-m3", device: str = "cpu", use_mock: bool = False
    ):
        self.model_name = model_name
        self.device = device
        self.model = None
        self.dimension = 1024  # bge-m3 default dimension

        # 默认使用真实模型（模型已下载）
        if use_mock:
            logger.info("Using mock embedding service")
            self.model = None
        else:
            self._load_model()

    def _load_model(self):
        """加载模型"""
        try:
            # 尝试使用 sentence-transformers
            from sentence_transformers import SentenceTransformer

            # 设置缓存目录
            cache_dir = os.path.join(os.path.dirname(__file__), "../../../models")
            os.makedirs(cache_dir, exist_ok=True)

            logger.info(f"Loading embedding model: {self.model_name}")
            
            # 使用本地模型路径
            local_model_path = os.path.join(cache_dir, "models--BAAI--bge-m3", "snapshots", "5617a9f61b028005a4858fdac845db406aefb181")
            
            if os.path.exists(local_model_path):
                logger.info(f"Using local model: {local_model_path}")
                self.model = SentenceTransformer(local_model_path)
            else:
                logger.info(f"Loading from HuggingFace: {self.model_name}")
                self.model = SentenceTransformer(self.model_name, cache_folder=cache_dir)
            
            self.model.to(self.device)

            # 获取维度
            test_embedding = self.model.encode("test")
            self.dimension = len(test_embedding)

            logger.info(f"✅ Embedding model loaded: {self.model_name}, dim={self.dimension}")

        except ImportError:
            logger.warning("❌ sentence-transformers not available, using mock embedding")
            self.model = None
            self.dimension = 768
        except Exception as e:
            logger.error(f"❌ Failed to load embedding model: {e}")
            self.model = None
            self.dimension = 768

    def encode(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """编码文本为向量"""
        if not texts:
            return []

        if self.model:
            try:
                embeddings = self.model.encode(
                    texts, batch_size=batch_size, show_progress_bar=False, convert_to_numpy=True
                )
                return embeddings.tolist()
            except Exception as e:
                logger.error(f"Encoding error: {e}")
                return self._mock_encode(texts)
        else:
            return self._mock_encode(texts)

    def _mock_encode(self, texts: List[str]) -> List[List[float]]:
        """模拟编码（当模型不可用时）"""
        np.random.seed(42)
        return [np.random.randn(self.dimension).tolist() for _ in texts]

    def encode_single(self, text: str) -> List[float]:
        """编码单个文本"""
        results = self.encode([text])
        return results[0] if results else [0.0] * self.dimension


# 全局实例
_embedding_service = None


def get_embedding_service(use_mock: bool = True) -> EmbeddingService:
    """获取全局 Embedding 服务实例"""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService(use_mock=use_mock)
    return _embedding_service
