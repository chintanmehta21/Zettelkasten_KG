"""Chonkie-compatible embeddings adapter backed by the shared Gemini pool."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Sequence

import numpy as np

try:
    from google.genai.types import EmbedContentConfig
except Exception:  # pragma: no cover - import fallback
    EmbedContentConfig = None

from website.features.rag_pipeline.adapters.pool_factory import get_gemini_pool
from website.features.rag_pipeline.errors import EmbeddingGenerationError

try:
    from chonkie.embeddings import BaseEmbeddings as _ChonkieBaseEmbeddings
except ImportError:
    class _ChonkieBaseEmbeddings(ABC):
        @property
        @abstractmethod
        def dimension(self) -> int:
            raise NotImplementedError

        @abstractmethod
        def embed(self, text: str | Sequence[str]) -> np.ndarray | list[np.ndarray]:
            raise NotImplementedError

        @abstractmethod
        def get_tokenizer(self) -> Any:
            raise NotImplementedError


class GeminiChonkieEmbeddings(_ChonkieBaseEmbeddings):
    """Expose the existing Gemini pool through Chonkie's embedding interface."""

    def __init__(self, *, output_dim: int = 768) -> None:
        self._pool = get_gemini_pool()
        self._output_dim = output_dim
        self._model_name_or_path = "gemini-embedding-001"

    @property
    def dimension(self) -> int:
        return self._output_dim

    def embed(self, texts: str | Sequence[str]) -> np.ndarray | list[np.ndarray]:
        text_batch = [texts] if isinstance(texts, str) else list(texts)
        response = self._pool.embed_content(
            contents=text_batch,
            config=self._build_config(),
        )
        embeddings = getattr(response, "embeddings", None) or []
        if len(embeddings) != len(text_batch):
            raise EmbeddingGenerationError("No embeddings returned by Gemini pool")

        vectors: list[np.ndarray] = []
        for embedding in embeddings:
            values = getattr(embedding, "values", None) or []
            if not values:
                raise EmbeddingGenerationError(
                    "No embeddings values returned by Gemini pool"
                )
            vectors.append(np.asarray(values[: self._output_dim], dtype=np.float32))
        return vectors[0] if isinstance(texts, str) else vectors

    def embed_query(self, text: str) -> np.ndarray:
        result = self.embed(text)
        assert isinstance(result, np.ndarray)
        return result

    def get_tokenizer(self) -> Any:
        return None

    def _build_config(self) -> Any:
        if EmbedContentConfig is None:
            return {
                "output_dimensionality": self._output_dim,
                "task_type": "RETRIEVAL_DOCUMENT",
            }
        return EmbedContentConfig(
            output_dimensionality=self._output_dim,
            task_type="RETRIEVAL_DOCUMENT",
        )

