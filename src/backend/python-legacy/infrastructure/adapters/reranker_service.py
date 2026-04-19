"""
Reranker 服务
使用Cross-Encoder对候选结果进行精排
"""

import os
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


class RerankerService:
    """Reranker服务 - 基于Cross-Encoder的精排"""

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3", device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self.model = None
        self._load_model()

    def _load_model(self):
        """加载Reranker模型"""
        try:
            from sentence_transformers import CrossEncoder

            # 设置离线环境变量
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"

            # 动态计算模型目录：优先使用环境变量，其次使用项目根目录下的models目录
            models_dir = os.environ.get("MODELS_DIR")
            if not models_dir:
                # 计算项目根目录：src/backend/python-legacy/infrastructure/adapters -> ../../../../../
                current_dir = os.path.dirname(os.path.abspath(__file__))
                project_root = os.path.abspath(os.path.join(current_dir, "../../../../.."))
                models_dir = os.path.join(project_root, "models")

            logger.info(f"Loading reranker model: {self.model_name}, cache_dir: {models_dir}")
            self.model = CrossEncoder(
                self.model_name,
                cache_folder=models_dir,
                local_files_only=True,
                device=self.device,
                max_length=512,
            )

            logger.info(f"✅ Reranker model loaded: {self.model_name}")

        except Exception as e:
            logger.error(f"❌ Failed to load reranker model: {e}")
            self.model = None

    def rerank(self, query: str, documents: List[str], batch_size: int = 8) -> List[float]:
        """
        对候选文档进行重排序

        Args:
            query: 查询文本
            documents: 候选文档列表
            batch_size: 批处理大小

        Returns:
            每个文档的相关性分数列表
        """
        if not documents:
            return []

        if self.model is None:
            logger.warning("Reranker model not loaded, returning uniform scores")
            return [1.0] * len(documents)

        try:
            # 构建query-doc pairs
            pairs = [[query, doc] for doc in documents]

            # 使用CrossEncoder评分
            scores = self.model.predict(
                pairs, batch_size=batch_size, show_progress_bar=False, convert_to_numpy=True
            )

            # 确保返回Python float列表
            if hasattr(scores, "tolist"):
                scores = scores.tolist()

            return scores

        except Exception as e:
            logger.error(f"Reranking error: {e}")
            return [1.0] * len(documents)

    def rerank_with_threshold(
        self, query: str, documents: List[str], threshold: float = -10.0, top_k: int = 10
    ) -> List[Tuple[int, float]]:
        """
        重排序并过滤低分结果

        Returns:
            List of (original_index, score) tuples
        """
        scores = self.rerank(query, documents)

        # 组合索引和分数
        indexed_scores = [(i, float(score)) for i, score in enumerate(scores)]

        # 按分数排序
        indexed_scores.sort(key=lambda x: x[1], reverse=True)

        # 过滤阈值并取Top-K
        filtered = [(idx, score) for idx, score in indexed_scores if score >= threshold]

        return filtered[:top_k]


# 全局实例
_reranker_service = None


def get_reranker_service() -> RerankerService:
    """获取全局Reranker服务实例"""
    global _reranker_service
    if _reranker_service is None:
        _reranker_service = RerankerService()
    return _reranker_service
