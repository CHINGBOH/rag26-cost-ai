"""
Embedding生成适配器
支持TEI、Ollama、Local(sentence-transformers)三种后端
"""

import logging
import json
from typing import List, Optional
import requests
import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingGenerator:
    """Embedding生成器"""

    def __init__(self, backend: str = "local", tei_url: str = "http://localhost:8003/embed",
                 ollama_url: str = "http://localhost:11434/api/embeddings",
                 ollama_model: str = "qwen2.5:7b-instruct",
                 local_model_path: str = "",
                 dimension: int = 1024, batch_size: int = 32):
        self.backend = backend
        self.tei_url = tei_url
        self.ollama_url = ollama_url
        self.ollama_model = ollama_model
        self.local_model_path = local_model_path
        self.dimension = dimension
        self.batch_size = batch_size
        self._local_model = None
        self._available = self._check_availability()

    def _check_availability(self) -> bool:
        """检查后端服务是否可用"""
        if self.backend == "tei":
            try:
                r = requests.get(self.tei_url.replace('/embed', '/health'), timeout=5)
                if r.status_code == 200:
                    logger.info("✅ TEI embedding service available")
                    return True
            except Exception as e:
                logger.warning(f"⚠️ TEI unavailable: {e}")
            return False
        
        elif self.backend == "ollama":
            try:
                r = requests.get(self.ollama_url.replace('/api/embeddings', '/api/tags'), timeout=5)
                if r.status_code == 200:
                    logger.info("✅ Ollama embedding service available")
                    return True
            except Exception as e:
                logger.warning(f"⚠️ Ollama unavailable: {e}")
            return False
        
        elif self.backend == "local":
            try:
                from sentence_transformers import SentenceTransformer
                # 尝试加载本地模型
                model_path = self.local_model_path
                if not model_path:
                    # 使用默认本地路径
                    import os
                    model_path = os.path.expanduser(
                        "~/rag-dashboard/models/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181"
                    )
                
                if not os.path.exists(model_path):
                    logger.warning(f"⚠️ Local model path not found: {model_path}, trying HuggingFace cache")
                    model_path = "BAAI/bge-m3"
                
                self._local_model = SentenceTransformer(model_path)
                self.dimension = self._local_model.get_sentence_embedding_dimension()
                logger.info(f"✅ Local embedding model loaded: {model_path}, dim={self.dimension}")
                return True
            except Exception as e:
                logger.warning(f"⚠️ Local model load failed: {e}")
                return False
        
        return False

    def encode(self, texts: List[str]) -> List[List[float]]:
        """编码文本为向量"""
        if not self._available:
            logger.warning("Embedding backend not available, returning zero vectors")
            return [[0.0] * self.dimension for _ in texts]
        
        if self.backend == "tei":
            return self._encode_tei(texts)
        elif self.backend == "ollama":
            return self._encode_ollama(texts)
        elif self.backend == "local":
            return self._encode_local(texts)
        else:
            return [[0.0] * self.dimension for _ in texts]

    def _encode_tei(self, texts: List[str]) -> List[List[float]]:
        """通过TEI服务生成embedding"""
        results = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i+self.batch_size]
            try:
                r = requests.post(
                    self.tei_url,
                    headers={"Content-Type": "application/json"},
                    json={"inputs": batch},
                    timeout=60
                )
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, list):
                        results.extend(data)
                    else:
                        logger.warning(f"TEI unexpected response: {data}")
                        results.extend([[0.0] * self.dimension for _ in batch])
                else:
                    logger.warning(f"TEI error {r.status_code}: {r.text[:200]}")
                    results.extend([[0.0] * self.dimension for _ in batch])
            except Exception as e:
                logger.error(f"TEI request error: {e}")
                results.extend([[0.0] * self.dimension for _ in batch])
        return results

    def _encode_ollama(self, texts: List[str]) -> List[List[float]]:
        """通过Ollama生成embedding"""
        results = []
        for text in texts:
            try:
                r = requests.post(
                    self.ollama_url,
                    json={"model": self.ollama_model, "prompt": text},
                    timeout=30
                )
                if r.status_code == 200:
                    data = r.json()
                    vec = data.get("embedding", [])
                    if len(vec) < self.dimension:
                        vec = vec + [0.0] * (self.dimension - len(vec))
                    elif len(vec) > self.dimension:
                        vec = vec[:self.dimension]
                    results.append(vec)
                else:
                    logger.warning(f"Ollama error {r.status_code}")
                    results.append([0.0] * self.dimension)
            except Exception as e:
                logger.error(f"Ollama request error: {e}")
                results.append([0.0] * self.dimension)
        return results

    def _encode_local(self, texts: List[str]) -> List[List[float]]:
        """使用本地sentence-transformers模型生成embedding"""
        if self._local_model is None:
            return [[0.0] * self.dimension for _ in texts]
        
        try:
            embeddings = self._local_model.encode(
                texts, batch_size=self.batch_size,
                show_progress_bar=False, convert_to_numpy=True
            )
            return embeddings.tolist()
        except Exception as e:
            logger.error(f"Local encoding error: {e}")
            return [[0.0] * self.dimension for _ in texts]

    def generate_for_records(self, records: List[dict], text_template: str = "{material_name} {spec}") -> List[tuple]:
        """
        为记录生成embedding
        
        Args:
            records: 记录列表
            text_template: 文本模板，支持{name}, {spec}等占位符
        
        Returns:
            [(record_id, vector), ...]
        """
        texts = []
        ids = []
        for rec in records:
            text = text_template.format(**rec)
            texts.append(text)
            ids.append(rec.get('id'))
        
        vectors = self.encode(texts)
        return list(zip(ids, vectors))
