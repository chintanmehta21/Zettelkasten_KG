"""Backend selection between Gemini and Claude."""

from __future__ import annotations

from website.features.rag_pipeline.types import ChatQuery


class LLMRouter:
    def __init__(self, *, gemini, claude=None):
        self._gemini = gemini
        self._claude = claude

    async def generate_stream(self, *, query: ChatQuery, system_prompt: str, user_prompt: str):
        backend = self._pick_backend(query)
        async for token in backend.generate_stream(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            quality=query.quality,
        ):
            yield token

    async def generate(self, *, query: ChatQuery, system_prompt: str, user_prompt: str):
        backend = self._pick_backend(query)
        return await backend.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            quality=query.quality,
        )

    def _pick_backend(self, query: ChatQuery):
        if query.quality == "high" and self._claude is not None and self._claude.enabled:
            return self._claude
        return self._gemini

