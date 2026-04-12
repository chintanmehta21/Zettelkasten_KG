"""HTTP client for the TEI reranker sidecar."""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from website.features.rag_pipeline.types import RetrievalCandidate


class TEIReranker:
    """Rerank retrieval candidates with a TEI-hosted cross-encoder."""

    def __init__(
        self,
        base_url: str = "http://reranker:8080",
        timeout: float = 3.0,
        client: httpx.AsyncClient | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=timeout)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=0.2, max=2))
    async def rerank(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
        top_k: int = 8,
    ) -> list[RetrievalCandidate]:
        if not candidates:
            return []
        try:
            response = await self._client.post(
                f"{self._base_url}/rerank",
                json={
                    "query": query,
                    "texts": [candidate.content[:4000] for candidate in candidates],
                    "truncate": True,
                    "raw_scores": False,
                },
            )
            response.raise_for_status()
            scored = response.json()
            for item in scored:
                candidates[item["index"]].rerank_score = item["score"]
            for candidate in candidates:
                candidate.final_score = (
                    0.60 * (candidate.rerank_score or 0.0)
                    + 0.25 * (candidate.graph_score or 0.0)
                    + 0.15 * (candidate.rrf_score or 0.0)
                )
            return sorted(
                candidates,
                key=lambda candidate: candidate.final_score or 0.0,
                reverse=True,
            )[:top_k]
        except httpx.HTTPError:
            for candidate in candidates:
                candidate.rerank_score = None
                candidate.final_score = candidate.rrf_score or 0.0
            return sorted(candidates, key=lambda candidate: candidate.rrf_score, reverse=True)[:top_k]

