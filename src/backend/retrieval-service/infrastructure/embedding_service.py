"""
Embedding service.

Supports sentence-transformers by default and can be switched to a llama.cpp
OpenAI-compatible embeddings endpoint via environment variables.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from functools import lru_cache
from typing import List

import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Embedding service with pluggable backends."""

    def __init__(
        self, model_name: str = "BAAI/bge-m3", device: str = "cpu", use_mock: bool = False
    ):
        self.model_name = model_name
        self.device = device
        self.model = None
        self.dimension = 1024
        self.backend = os.environ.get("EMBEDDING_BACKEND", "sentence_transformers")
        self.llama_url = os.environ.get("LLAMA_CPP_EMBED_URL", "").rstrip("/")
        self.llama_model = os.environ.get("LLAMA_CPP_EMBED_MODEL", "llama.cpp-embedding")
        self.expected_dimension = int(os.environ.get("EMBEDDING_VECTOR_DIM", "0") or 0)

        if use_mock:
            logger.info("Using mock embedding service")
            self.backend = "mock"
            return

        self._load_model()
        self._validate_dimension()

    def _load_model(self):
        """Load the configured embedding backend."""
        if self.backend == "llama_cpp_http":
            self._load_llama_cpp_http()
            return

        self._load_sentence_transformers()

    def _load_llama_cpp_http(self) -> None:
        if not self.llama_url:
            raise ValueError("LLAMA_CPP_EMBED_URL is required when EMBEDDING_BACKEND=llama_cpp_http")

        started = time.perf_counter()
        logger.info("Using llama.cpp embedding endpoint: %s", self.llama_url)
        test_embedding = self._encode_llama_cpp(["test"])[0]
        self.dimension = len(test_embedding)
        logger.info(
            "✅ llama.cpp embedding endpoint ready: dim=%s elapsed_ms=%.2f",
            self.dimension,
            (time.perf_counter() - started) * 1000.0,
        )

    def _load_sentence_transformers(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
            import torch
        except ImportError:
            logger.warning("❌ sentence-transformers not available, using mock embedding")
            self.backend = "mock"
            self.dimension = 768
            return

        try:
            cache_dir = os.path.join(os.path.dirname(__file__), "../../../models")
            os.makedirs(cache_dir, exist_ok=True)

            logger.info("Loading embedding model: %s", self.model_name)

            local_model_path = os.path.join(
                cache_dir, "models--BAAI--bge-m3", "snapshots", "5617a9f61b028005a4858fdac845db406aefb181"
            )

            if os.path.exists(local_model_path):
                logger.info("Using local model: %s", local_model_path)
                self.model = SentenceTransformer(local_model_path, device=self.device)
            else:
                logger.info("Loading from HuggingFace: %s", self.model_name)
                self.model = SentenceTransformer(
                    self.model_name, cache_folder=cache_dir, device=self.device
                )

            self.model.to(self.device)
            torch.set_num_threads(max(1, os.cpu_count() // 2))
            test_embedding = self.model.encode("test")
            self.dimension = len(test_embedding)

            logger.info(
                "✅ Embedding model loaded: %s, dim=%s (threads=%s)",
                self.model_name,
                self.dimension,
                torch.get_num_threads(),
            )
        except Exception as exc:
            logger.error("❌ Failed to load embedding model: %s", exc)
            self.backend = "mock"
            self.model = None
            self.dimension = 768

    def _validate_dimension(self) -> None:
        if self.expected_dimension <= 0:
            return
        if self.dimension != self.expected_dimension:
            raise ValueError(
                f"Embedding dimension mismatch: actual={self.dimension}, "
                f"expected={self.expected_dimension}"
            )

    def runtime_info(self) -> dict:
        return {
            "backend": self.backend,
            "model_name": self.model_name,
            "dimension": self.dimension,
            "llama_url": self.llama_url,
            "llama_model": self.llama_model,
            "expected_dimension": self.expected_dimension,
        }

    def _encode_llama_cpp(self, texts: List[str]) -> List[List[float]]:
        started = time.perf_counter()
        request = urllib.request.Request(
            url=f"{self.llama_url}/v1/embeddings",
            data=json.dumps(
                {
                    "input": texts,
                    "model": self.llama_model,
                    "encoding_format": "float",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer no-key"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            logger.error(
                "[embedding] llama_cpp_http failed: http_error elapsed_ms=%.2f detail=%s",
                (time.perf_counter() - started) * 1000.0,
                detail[:300],
            )
            raise RuntimeError(f"llama.cpp embedding request failed: {detail}") from exc
        except urllib.error.URLError as exc:
            logger.error(
                "[embedding] llama_cpp_http failed: url_error elapsed_ms=%.2f detail=%s",
                (time.perf_counter() - started) * 1000.0,
                exc,
            )
            raise RuntimeError(f"llama.cpp endpoint unavailable: {exc}") from exc

        data = payload.get("data")
        if not isinstance(data, list):
            logger.error(
                "[embedding] llama_cpp_http failed: invalid_payload elapsed_ms=%.2f",
                (time.perf_counter() - started) * 1000.0,
            )
            raise RuntimeError(f"Unexpected llama.cpp embeddings payload: {payload}")

        ordered = sorted(data, key=lambda item: item["index"])
        logger.info(
            "[embedding] llama_cpp_http encoded batch=%s elapsed_ms=%.2f",
            len(texts),
            (time.perf_counter() - started) * 1000.0,
        )
        return [item["embedding"] for item in ordered]

    def encode(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """Encode text into vectors."""
        if not texts:
            return []

        started = time.perf_counter()
        if self.backend == "llama_cpp_http":
            return self._encode_llama_cpp(texts)

        if self.model:
            try:
                embeddings = self.model.encode(
                    texts, batch_size=batch_size, show_progress_bar=False, convert_to_numpy=True
                )
                logger.info(
                    "[embedding] sentence_transformers encoded batch=%s elapsed_ms=%.2f",
                    len(texts),
                    (time.perf_counter() - started) * 1000.0,
                )
                return embeddings.tolist()
            except Exception as exc:
                logger.error("Encoding error: %s", exc)
                return self._mock_encode(texts)

        return self._mock_encode(texts)

    def _mock_encode(self, texts: List[str]) -> List[List[float]]:
        """Fallback mock encoding for unavailable models."""
        np.random.seed(42)
        return [np.random.randn(self.dimension).tolist() for _ in texts]

    @lru_cache(maxsize=256)
    def _encode_cached(self, text: str) -> tuple:
        results = self.encode([text])
        return tuple(results[0]) if results else tuple([0.0] * self.dimension)

    def encode_single(self, text: str) -> List[float]:
        return list(self._encode_cached(text))

    def encode_query(self, text: str) -> List[float]:
        prefix = "Represent this sentence for searching relevant passages: "
        return list(self._encode_cached(prefix + text))


_embedding_service = None


def get_embedding_service(use_mock: bool = False) -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService(use_mock=use_mock)
    return _embedding_service
