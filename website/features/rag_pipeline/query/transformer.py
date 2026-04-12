"""Query expansion helpers for the retrieval pipeline."""

from __future__ import annotations

from typing import Any

from website.features.rag_pipeline.adapters.pool_factory import get_generation_pool
from website.features.rag_pipeline.types import QueryClass


class QueryTransformer:
    """Generate retrieval variants based on the routed query class."""

    def __init__(self, pool: Any | None = None):
        self._pool = pool

    async def transform(self, query: str, cls: QueryClass) -> list[str]:
        if cls is QueryClass.LOOKUP:
            return [query]
        if cls is QueryClass.VAGUE:
            return _dedupe([query, await self._hyde(query)])
        if cls is QueryClass.MULTI_HOP:
            return _dedupe([query, *await self._decompose(query, n=3)])
        if cls is QueryClass.THEMATIC:
            return _dedupe([query, *await self._multi_query(query, n=3)])
        if cls is QueryClass.STEP_BACK:
            return _dedupe([query, await self._step_back(query)])
        return [query]

    async def _hyde(self, query: str) -> str:
        return await self._single_variant(
            "Write a short hypothetical answer passage that would likely contain the information needed to answer this query:\n"
            f"{query}"
        )

    async def _decompose(self, query: str, n: int) -> list[str]:
        return await self._multi_variant(
            f"Break this question into {n} short sub-questions, one per line:\n{query}",
            n,
        )

    async def _multi_query(self, query: str, n: int) -> list[str]:
        return await self._multi_variant(
            f"Generate {n} alternative search reformulations for this question, one per line:\n{query}",
            n,
        )

    async def _step_back(self, query: str) -> str:
        return await self._single_variant(
            "Rewrite this question into a broader, more general framing that still preserves the user's intent:\n"
            f"{query}"
        )

    async def _single_variant(self, prompt: str) -> str:
        try:
            response = await self._get_pool().generate_content(
                prompt,
                config={"temperature": 0.2, "max_output_tokens": 200},
                starting_model="gemini-2.5-flash-lite",
                label="RAG QueryTransformer",
            )
            return _coerce_text(response).strip()
        except Exception:
            return ""

    async def _multi_variant(self, prompt: str, n: int) -> list[str]:
        try:
            response = await self._get_pool().generate_content(
                prompt,
                config={"temperature": 0.2, "max_output_tokens": 300},
                starting_model="gemini-2.5-flash-lite",
                label="RAG QueryTransformer",
            )
            lines = [line.strip(" -*\t") for line in _coerce_text(response).splitlines()]
            return [line for line in lines if line][:n]
        except Exception:
            return []

    def _get_pool(self) -> Any:
        if self._pool is None:
            self._pool = get_generation_pool()
        return self._pool


def _coerce_text(response: Any) -> str:
    payload = response[0] if isinstance(response, tuple) else response
    if isinstance(payload, str):
        return payload
    text = getattr(payload, "text", None)
    if text is not None:
        return text
    return str(payload)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in seen:
            deduped.append(cleaned)
            seen.add(cleaned)
    return deduped

