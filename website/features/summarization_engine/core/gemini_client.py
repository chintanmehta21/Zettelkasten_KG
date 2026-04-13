"""Tiered Gemini client wrapping the existing key pool."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from website.features.summarization_engine.core.config import EngineConfig
from website.features.summarization_engine.core.errors import GeminiError

Tier = Literal["pro", "flash"]


@dataclass(frozen=True)
class GenerateResult:
    """Result of a single Gemini generate call."""

    text: str
    model_used: str
    input_tokens: int
    output_tokens: int
    key_index: int = 0


class TieredGeminiClient:
    """Add Pro/Flash tier selection on top of GeminiKeyPool."""

    def __init__(self, key_pool: Any, config: EngineConfig):
        self._pool = key_pool
        self._config = config

    async def generate_multimodal(
        self,
        contents: list,
        *,
        starting_model: str | None = None,
        label: str = "multimodal",
    ) -> GenerateResult:
        """Generate from multimodal content (e.g. video Part + text prompt).

        Unlike ``generate()``, this accepts arbitrary ``contents`` lists
        (Parts, strings, etc.) and passes them directly to the key pool.
        """
        config: dict[str, Any] = {
            "temperature": self._config.gemini.temperature,
            "max_output_tokens": self._config.gemini.max_output_tokens,
        }
        flash_chain = self._config.gemini.model_chains.get("flash", [])
        model = starting_model or (flash_chain[0] if flash_chain else "gemini-2.5-flash")

        response, model_used, key_index = await self._pool.generate_content(
            contents=contents,
            config=config,
            starting_model=model,
            label=label,
        )

        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
        output_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0

        return GenerateResult(
            text=getattr(response, "text", "") or "",
            model_used=model_used,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            key_index=key_index,
        )

    async def generate(
        self,
        prompt: str,
        *,
        tier: Tier = "pro",
        response_schema: type[BaseModel] | None = None,
        system_instruction: str | None = None,
        temperature: float | None = None,
    ) -> GenerateResult:
        chain = self._config.gemini.model_chains.get(tier)
        if not chain:
            raise GeminiError(f"No model chain configured for tier={tier!r}")

        call_config: dict[str, Any] = {
            "temperature": temperature
            if temperature is not None
            else self._config.gemini.temperature,
            "max_output_tokens": self._config.gemini.max_output_tokens,
        }
        if response_schema is not None:
            call_config["response_mime_type"] = "application/json"
            # Don't pass response_schema to Gemini — Pydantic v2 emits
            # additionalProperties which Gemini rejects.  JSON mode +
            # prompt-based structure + parse_json_object is reliable enough.

        if system_instruction:
            call_config["system_instruction"] = system_instruction

        response, model_used, key_index = await self._pool.generate_content(
            contents=prompt,
            config=call_config,
            starting_model=chain[0],
            label=f"engine-v2-{tier}",
        )

        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
        output_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0

        return GenerateResult(
            text=getattr(response, "text", "") or "",
            model_used=model_used,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            key_index=key_index,
        )
