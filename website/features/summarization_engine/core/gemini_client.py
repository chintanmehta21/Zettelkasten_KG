"""Tiered Gemini client wrapping the existing key pool."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from website.features.summarization_engine.core.config import EngineConfig
from website.features.summarization_engine.core.errors import GeminiError

Tier = Literal["pro", "flash"]


def _extract_finish_reason(response: Any) -> str | None:
    """Pluck ``finish_reason`` from a Gemini SDK response without crashing.

    Canonical SDK shape: ``response.candidates[0].finish_reason`` (an enum that
    str-coerces to ``"MAX_TOKENS"`` / ``"STOP"`` / ``"SAFETY"`` / etc.).
    Older / mocked responses may not expose ``candidates`` at all — in which
    case we return ``None`` rather than raising. Both the enum and string
    forms are accepted; enum is stringified for caller convenience.
    """
    try:
        candidates = getattr(response, "candidates", None)
        if not candidates:
            return None
        first = candidates[0]
        reason = getattr(first, "finish_reason", None)
        if reason is None:
            return None
        # Normalize enum → "MAX_TOKENS" string, leave plain strings alone.
        name = getattr(reason, "name", None)
        return name if isinstance(name, str) else str(reason)
    except Exception:
        return None


@dataclass(frozen=True)
class GenerateResult:
    """Result of a single Gemini generate call."""

    text: str
    model_used: str
    input_tokens: int
    output_tokens: int
    key_index: int = 0
    # starting_model + fallback_reason expose key-pool routing decisions so
    # summarizers can surface them in ``SummaryMetadata.model_used``. A non-None
    # ``fallback_reason`` means the starting-tier model failed and the pool
    # downgraded to a lower tier (e.g. ``"gemini-2.5-flash-timeout"``). Callers
    # that don't care can ignore both fields; they default to safe values.
    starting_model: str | None = None
    fallback_reason: str | None = None
    # Lane 1 (2026-05-30) — Gemini's candidate.finish_reason surfaced so callers
    # can detect MAX_TOKENS / SAFETY / RECITATION outcomes before downstream
    # parse logic blows up on truncated output. Defaults to None so legacy
    # call sites and tests don't need to set it.
    finish_reason: str | None = None


class TieredGeminiClient:
    """Add Pro/Flash tier selection on top of GeminiKeyPool."""

    def __init__(self, key_pool: Any, config: EngineConfig):
        self._pool = key_pool
        self._config = config
        # Opt-in per-client call trace. When a summarizer wants to attribute
        # every Gemini call back to a role (``summarizer``/``patch``/...), it
        # sets this to a fresh list before calling ``generate`` and reads
        # the populated entries afterwards. Unused in legacy paths.
        self._call_journal: list | None = None

    def enable_call_journal(self) -> list[dict]:
        """Start recording per-call telemetry on this client.

        Returns the mutable journal list so the caller can read it later
        (``drain_call_journal`` is the cleaner API; this return value is
        provided so callers can subscribe without losing entries emitted
        between enable and drain). Idempotent: calling twice reuses the
        existing list rather than discarding in-flight entries.
        """
        if self._call_journal is None:
            self._call_journal = []
        return self._call_journal

    def drain_call_journal(self) -> list[dict]:
        """Return a copy of the journal and reset it to an empty list.

        Returns ``[]`` when no journal was enabled. The copy isolates
        callers from subsequent appends so they can serialize safely.
        """
        if self._call_journal is None:
            return []
        drained = list(self._call_journal)
        self._call_journal = []
        return drained

    async def generate_multimodal(
        self,
        contents: list,
        *,
        starting_model: str | None = None,
        label: str = "multimodal",
        role: str | None = None,
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

        telemetry_sink: list | None = [] if self._call_journal is not None else None
        response, model_used, key_index = await self._pool.generate_content(
            contents=contents,
            config=config,
            starting_model=model,
            label=label,
            telemetry_sink=telemetry_sink,
        )
        fallback_reason: str | None = None

        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
        output_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0

        if telemetry_sink:
            entry = dict(telemetry_sink[0])
            entry["role"] = role or label
            entry["input_tokens"] = input_tokens
            entry["output_tokens"] = output_tokens
            fallback_reason = entry.get("fallback_reason")
            if self._call_journal is not None:
                self._call_journal.append(entry)

        return GenerateResult(
            text=getattr(response, "text", "") or "",
            model_used=model_used,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            key_index=key_index,
            starting_model=model,
            fallback_reason=fallback_reason,
            finish_reason=_extract_finish_reason(response),
        )

    async def generate(
        self,
        prompt: str,
        *,
        tier: Tier = "pro",
        response_schema: type[BaseModel] | None = None,
        response_mime_type: str | None = None,
        system_instruction: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        role: str | None = None,
    ) -> GenerateResult:
        chain = self._config.gemini.model_chains.get(tier)
        if not chain:
            raise GeminiError(f"No model chain configured for tier={tier!r}")

        call_config: dict[str, Any] = {
            "temperature": temperature
            if temperature is not None
            else self._config.gemini.temperature,
            "max_output_tokens": max_output_tokens
            if max_output_tokens is not None
            else self._config.gemini.max_output_tokens,
        }
        if response_schema is not None:
            call_config["response_mime_type"] = "application/json"
            # Don't pass response_schema to Gemini — Pydantic v2 emits
            # additionalProperties which Gemini rejects.  JSON mode +
            # prompt-based structure + parse_json_object is reliable enough.
        # Explicit response_mime_type wins over the schema-derived default.
        # Use case: atomic_facts extraction wants JSON mode without a schema
        # (the response is a flat array, not a Pydantic-modelled object).
        # Setting this to "application/json" forces Gemini to skip prose
        # narration and emit strict JSON from the first token — addresses
        # the truncation pattern caught on the DMT zettel 2026-05-28.
        if response_mime_type is not None:
            call_config["response_mime_type"] = response_mime_type

        if system_instruction:
            call_config["system_instruction"] = system_instruction

        label = f"engine-v2-{tier}"
        telemetry_sink: list | None = [] if self._call_journal is not None else []
        # We always collect telemetry into a throw-away sink so ``GenerateResult``
        # can surface ``fallback_reason`` regardless of whether the caller
        # installed a per-summarizer journal. The overhead is a single list
        # allocation per call.
        response, model_used, key_index = await self._pool.generate_content(
            contents=prompt,
            config=call_config,
            starting_model=chain[0],
            label=label,
            telemetry_sink=telemetry_sink,
        )
        fallback_reason: str | None = None

        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
        output_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0

        if telemetry_sink:
            entry = dict(telemetry_sink[0])
            entry["role"] = role or tier
            # Carry token counts into the journal so
            # ``core.telemetry.build_telemetry`` can split prod vs eval
            # without re-fetching usage metadata.
            entry["input_tokens"] = input_tokens
            entry["output_tokens"] = output_tokens
            fallback_reason = entry.get("fallback_reason")
            if self._call_journal is not None:
                self._call_journal.append(entry)

        return GenerateResult(
            text=getattr(response, "text", "") or "",
            model_used=model_used,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            key_index=key_index,
            starting_model=chain[0],
            fallback_reason=fallback_reason,
            finish_reason=_extract_finish_reason(response),
        )
