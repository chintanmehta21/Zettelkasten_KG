"""Flag-gated Claude backend stub."""

from __future__ import annotations

import os

from website.features.rag_pipeline.errors import LLMUnavailable


class ClaudeBackend:
    def __init__(self):
        self._api_key = os.environ.get("ANTHROPIC_API_KEY")
        self._model = "claude-3-5-sonnet-latest"

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    async def generate(self, *, system_prompt: str, user_prompt: str, quality: str, stop_sequences=None):
        del system_prompt, user_prompt, quality, stop_sequences
        if not self.enabled:
            raise LLMUnavailable("Claude backend is disabled")
        raise NotImplementedError("Claude backend is stubbed in v1")

    async def generate_stream(self, *, system_prompt: str, user_prompt: str, quality: str, stop_sequences=None):
        del system_prompt, user_prompt, quality, stop_sequences
        if not self.enabled:
            raise LLMUnavailable("Claude backend is disabled")
        raise NotImplementedError("Claude backend is stubbed in v1")

