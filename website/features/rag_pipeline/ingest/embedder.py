"""Async embedding wrapper over the existing Gemini key pool."""

from __future__ import annotations

import asyncio
import hashlib
import os
from typing import Any

from cachetools import LRUCache

try:
    from google.genai.types import EmbedContentConfig
except Exception:  # pragma: no cover - import fallback
    EmbedContentConfig = None


DIM = 768


class ChunkEmbedder:
    """Embed content in batches without blocking the event loop."""

    def __init__(self, pool: Any, batch_size: int = 32, max_parallel: int = 4):
        self._pool = pool
        self._batch_size = batch_size
        self._sem = asyncio.Semaphore(max_parallel)
        # iter-03 mem-bounded §2.6: bounded LRU caps slow linear leak. Default
        # 256 entries × ~6 KB ≈ 1.5 MB. Override via RAG_QUERY_CACHE_MAX.
        self._query_cache: LRUCache[str, list[float]] = LRUCache(
            maxsize=int(os.environ.get("RAG_QUERY_CACHE_MAX", "256")),
        )

    async def embed(
        self,
        texts: list[str],
        *,
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> list[list[float]]:
        if not texts:
            return []

        batches = [
            texts[i : i + self._batch_size]
            for i in range(0, len(texts), self._batch_size)
        ]

        async def _one(batch: list[str]) -> list[list[float]]:
            async with self._sem:
                config = _build_config(task_type)
                response = await asyncio.to_thread(
                    self._pool.embed_content,
                    contents=batch,
                    config=config,
                )
                embeddings = getattr(response, "embeddings", None) or []
                return [list(embedding.values) for embedding in embeddings]

        results = await asyncio.gather(*[_one(batch) for batch in batches])
        return [vector for batch in results for vector in batch]

    async def embed_query_with_cache(self, query: str) -> list[float]:
        if query in self._query_cache:
            return self._query_cache[query]
        vector = (await self.embed([query], task_type="RETRIEVAL_QUERY"))[0]
        self._query_cache[query] = vector
        return vector

    @staticmethod
    def content_hash(text: str) -> bytes:
        return hashlib.sha256(text.encode("utf-8")).digest()


def _build_config(task_type: str) -> Any:
    if EmbedContentConfig is None:
        return {
            "output_dimensionality": DIM,
            "task_type": task_type,
        }
    return EmbedContentConfig(
        output_dimensionality=DIM,
        task_type=task_type,
    )
