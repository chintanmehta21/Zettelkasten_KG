"""Gemini generation backend for grounded answers."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from website.features.rag_pipeline.adapters.pool_factory import get_generation_pool
from website.features.rag_pipeline.errors import LLMUnavailable
from website.features.api_key_switching.key_pool import _is_rate_limited

_TIER_CHAIN = {
    "fast": ["gemini-2.5-flash", "gemini-2.5-flash-lite"],
    "high": ["gemini-2.5-pro", "gemini-2.5-flash"],
}


@dataclass
class GenerationResult:
    content: str
    model: str
    token_counts: dict
    latency_ms: int
    finish_reason: str


class GeminiBackend:
    def __init__(self, pool: Any | None = None):
        self._pool = pool or get_generation_pool()

    async def generate(self, *, system_prompt: str, user_prompt: str, quality: str, stop_sequences=None) -> GenerationResult:
        config = {
            "system_instruction": system_prompt,
            "temperature": 0.2,
            "top_p": 0.95,
            "max_output_tokens": 2048,
            "stop_sequences": stop_sequences or [],
        }
        t0 = time.monotonic()
        for model in _TIER_CHAIN[quality]:
            try:
                response, model_used, _key_index = await self._pool.generate_content(
                    user_prompt,
                    config=config,
                    starting_model=model,
                    label="rag_generate",
                )
                usage = getattr(response, "usage_metadata", None)
                prompt_tokens = getattr(usage, "prompt_token_count", 0)
                completion_tokens = getattr(usage, "candidates_token_count", 0)
                total_tokens = getattr(usage, "total_token_count", prompt_tokens + completion_tokens)
                finish_reason = ""
                candidates = getattr(response, "candidates", None) or []
                if candidates:
                    finish_reason = str(getattr(candidates[0], "finish_reason", ""))
                return GenerationResult(
                    content=getattr(response, "text", ""),
                    model=model_used,
                    token_counts={
                        "prompt": prompt_tokens,
                        "completion": completion_tokens,
                        "total": total_tokens,
                    },
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    finish_reason=finish_reason,
                )
            except Exception as exc:
                if _is_rate_limited(exc):
                    continue
                raise
        raise LLMUnavailable("All Gemini tiers exhausted")

    async def generate_stream(self, *, system_prompt: str, user_prompt: str, quality: str, stop_sequences=None):
        result = await self.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            quality=quality,
            stop_sequences=stop_sequences,
        )
        yield result.content, {
            "model": result.model,
            "token_counts": result.token_counts,
            "finish_reason": result.finish_reason,
        }

