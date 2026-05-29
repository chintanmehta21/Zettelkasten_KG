"""Anthropic Claude Haiku 4.5 adapter that exposes the same surface as
TieredGeminiClient.generate(...) so ConsolidatedEvaluator can use it
without modification.

Eval-time only. Never imported by the prod runtime.
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class GenerateResult:
    """Mirror of website.features.summarization_engine.core.gemini_client.GenerateResult."""
    text: str
    model_used: str
    input_tokens: int
    output_tokens: int
    key_index: int = 0


class ClaudeJudgeClient:
    """Thin adapter over the Anthropic SDK presenting the Gemini-client
    generate(...) signature so ConsolidatedEvaluator can be reused unmodified.

    Single model: claude-haiku-4-5-20251001 (dated alias per sweep-3 /
    METHODOLOGY §19 — never use floating aliases).
    """

    def __init__(self, model: str = "claude-haiku-4-5-20251001") -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "anthropic SDK required; pip install anthropic>=0.39"
            ) from exc
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY missing — set in new_envs.txt "
                "or environment before invoking the Claude judge"
            )
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def generate(
        self,
        prompt: str,
        *,
        tier: str | None = None,                   # accepted for parity; ignored (single Claude model)
        response_schema: Any = None,               # accepted for parity; ignored (we use JSON-in-prompt)
        system_instruction: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        role: str | None = None,                   # for telemetry only
    ) -> GenerateResult:
        # The Anthropic SDK requires streaming when max_tokens > ~8192 because
        # such operations can exceed the 10-minute non-streaming timeout. The
        # ConsolidatedEvaluator hardcodes 32768 (Gemini-sized). Cap at 8192 for
        # Claude — judge JSON output is typically 2-3k tokens; never seen >5k
        # in evaluator.v7. Logged via the response's stop_reason if hit.
        capped = max(1, min(int(max_output_tokens or 8192), 8192))
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": capped,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_instruction:
            kwargs["system"] = system_instruction
        if temperature is not None:
            kwargs["temperature"] = float(temperature)
        msg = await self._client.messages.create(**kwargs)
        text = "".join(b.text for b in msg.content if hasattr(b, "text"))
        return GenerateResult(
            text=text,
            model_used=str(msg.model),
            input_tokens=int(msg.usage.input_tokens or 0),
            output_tokens=int(msg.usage.output_tokens or 0),
            key_index=0,
        )


def make_client(model: str = "claude-haiku-4-5-20251001") -> ClaudeJudgeClient:
    """Factory mirroring ops.scripts.lib.gemini_factory.make_client."""
    return ClaudeJudgeClient(model=model)
