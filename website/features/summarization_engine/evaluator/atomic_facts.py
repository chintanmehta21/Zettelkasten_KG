"""Extract importance-ranked source-grounded atomic facts, cached per URL and version."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from website.features.summarization_engine.core.cache import FsContentCache
from website.features.summarization_engine.evaluator.prompts import (
    ATOMIC_FACTS_PROMPT,
    PROMPT_VERSION,
)
from website.features.summarization_engine.summarization.common.json_utils import (
    parse_json_object,
)

# Optional industry-grade JSON repair layer (mangiucugna/json_repair, PyPI).
# Handles a wider range of LLM-malformations than our hand-rolled
# ``_repair_truncated_json_array`` — missing trailing braces, unbalanced
# quotes, escape errors, trailing commas, etc. When unavailable (bare-bones
# dev env) the script gracefully falls back to the hand-rolled repair.
try:
    from json_repair import loads as _json_repair_loads  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dep
    _json_repair_loads = None

logger = logging.getLogger(__name__)

# Atomic-facts output budget. Lane 1 research (2026-05-29) — Gemini 2.5 Flash
# silently defaults to ~8192 output tokens when ``max_output_tokens`` is unset
# (gemini-cli issue #23081, May 2026). The DMT-class truncation on 2026-05-28
# hit that ceiling mid-string at char 4759. 16384 gives a 2x margin without
# encroaching on the 65536 model cap and keeps cost predictable.
_ATOMIC_FACTS_MAX_OUTPUT_TOKENS = 16384


def _strip_fences(text: str) -> str:
    """Strip leading/trailing ```json fences from an LLM response."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _repair_truncated_json_array(text: str) -> list | None:
    """Salvage a truncated JSON array by snipping at the last complete top-level
    object boundary and closing the array. Handles the common LLM truncation
    pattern where ``max_output_tokens`` cuts the response mid-string inside the
    final object of an array.

    Returns the parsed list on success; ``None`` if the text is not an array,
    has no complete object, or the snipped output still fails to parse.
    """
    cleaned = text.strip()
    if not cleaned.startswith("["):
        return None
    depth = 0  # {} nesting depth (ignores [] / strings)
    in_string = False
    escape = False
    last_obj_end = -1  # 1-past-the-end index of the last `}` closing an array-level object
    for i, ch in enumerate(cleaned):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                last_obj_end = i + 1
    if last_obj_end == -1:
        return None
    repaired = cleaned[:last_obj_end] + "]"
    try:
        parsed = json.loads(repaired)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list):
        return parsed
    return None


def _parse_facts(text: str) -> list | dict:
    """Fence-tolerant parse for either a JSON array or an object.

    On JSON decode failure for an array-shaped payload, tries an escalating
    set of repair layers before re-raising:
        1. ``json_repair.loads`` (mangiucugna/json_repair PyPI) — handles
           missing braces, trailing commas, unbalanced quotes, etc.
        2. ``_repair_truncated_json_array`` — our hand-rolled snip-at-last-
           complete-object fallback that runs when json_repair is absent.
        3. Re-raise the original ``json.JSONDecodeError`` so the caller's
           retry-with-json-mime path can engage.
    """
    cleaned = _strip_fences(text)
    if cleaned.startswith("{"):
        return parse_json_object(cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        # Layer 1: industry-grade json_repair if available.
        # Layer 2 (hand-rolled) is preserved as a graceful-degradation
        # fallback for environments without json_repair installed (CI
        # shadows, bare-bones dev envs). When json_repair is present,
        # the hand-rolled layer is effectively unreachable — that's
        # defense-in-depth, not dead code.
        if _json_repair_loads is not None:
            try:
                repaired = _json_repair_loads(cleaned)
                if isinstance(repaired, (list, dict)):
                    logger.warning(
                        "atomic_facts.json_repair_salvaged shape=%s items=%d",
                        type(repaired).__name__,
                        len(repaired) if hasattr(repaired, "__len__") else -1,
                    )
                    return repaired
            except Exception:  # pragma: no cover - json_repair is permissive
                pass
        # Layer 2: hand-rolled array-truncation recovery
        repaired = _repair_truncated_json_array(cleaned)
        if repaired is not None:
            logger.warning(
                "atomic_facts.truncated_array_repaired salvaged=%d items "
                "(original truncated mid-object)",
                len(repaired),
            )
            return repaired
        # Layer 3: surrender — let the caller see the original decode error
        raise exc


async def extract_atomic_facts(
    *,
    client: Any,
    source_text: str,
    cache_root: Path,
    url: str,
    ingestor_version: str,
) -> list[dict]:
    cache = FsContentCache(root=cache_root, namespace="atomic_facts")
    key = (url, ingestor_version, PROMPT_VERSION)
    hit = cache.get(key)
    if hit and "facts" in hit and hit["facts"]:
        return hit["facts"]

    prompt = ATOMIC_FACTS_PROMPT.format(source_text=source_text[:30000])
    # ``role="atomic_facts"`` tags this call as an evaluator-side
    # (atomic-fact extraction) call in the telemetry split. Without the tag
    # it defaults to the tier ("flash") which the prod/eval classifier would
    # misattribute to the summarizer bucket.

    async def _call() -> Any:
        """Single Gemini call with explicit JSON-mode + 16k output budget.

        Lane 1 research (2026-05-29): the pre-fix code only set
        ``response_mime_type="application/json"`` on the SECOND (retry)
        attempt. The DMT-class truncation hit on the FIRST attempt — by
        then the model had already streamed an unmarked, prose-tolerant
        response that ran into the silent 8k default cap mid-string.
        Setting both from attempt 1 prevents the failure rather than
        repairs it.

        The ``TypeError`` catch is retained for one-level backward compat
        with mocks that don't accept ``response_mime_type``. Critically:
        ``max_output_tokens`` is in the canonical client signature, so we
        do NOT downgrade past that — a TypeError on it should be loud
        (surfaces a real bug), not silently swallowed.
        """
        kwargs: dict[str, Any] = {
            "tier": "flash",
            "role": "atomic_facts",
            "max_output_tokens": _ATOMIC_FACTS_MAX_OUTPUT_TOKENS,
            "response_mime_type": "application/json",
        }
        try:
            return await client.generate(prompt, **kwargs)
        except TypeError:
            # Legacy mock that doesn't accept ``response_mime_type`` —
            # preserve the perf-critical token cap and surface any other
            # surprises (e.g. future signature changes).
            return await client.generate(
                prompt, tier="flash", role="atomic_facts",
                max_output_tokens=_ATOMIC_FACTS_MAX_OUTPUT_TOKENS,
            )

    result = await _call()

    # Lane 1 gotcha: on Gemini 2.5 Flash, if the call ran out of tokens the
    # response can come back with ``finish_reason == "MAX_TOKENS"`` and
    # potentially-empty / truncated text. Log it so an operator can spot
    # the pattern in iter telemetry without having to re-derive it from
    # downstream parse failures.
    finish_reason = getattr(result, "finish_reason", None)
    if finish_reason and str(finish_reason).upper() == "MAX_TOKENS":
        logger.warning(
            "atomic_facts.max_tokens_hit url=%s output_tokens=%s — output "
            "may be truncated; downstream json_repair will attempt salvage.",
            url,
            getattr(result, "output_tokens", "?"),
        )

    try:
        raw = _parse_facts(result.text)
    except Exception as err:
        head = (result.text or "")[:200]
        logger.warning(
            "atomic_facts.parse_failed url=%s err=%s head=%r", url, err, head
        )
        # First-attempt already had json_mime + 16k budget + json_repair
        # fallback. If we're still here, the model produced something truly
        # unparseable (e.g. infinite-loop tool-use, content-filter refusal,
        # API surface error). Retry once with an explicit brevity directive
        # — Lane 1 research recommended prompt-shortening over re-adding
        # mime type which is already set.
        async def _call_brief() -> Any:
            # Lane 2 (Instructor pattern): include the REASON for the retry
            # in the reprompt — Gemini is more compliant when given context
            # for why brevity matters here. Token cap drops to 4096 to match
            # the prompt directive (otherwise the model sees "be brief" but
            # the API budget says "go nuts" → mixed signal).
            brief_prompt = (
                prompt
                + "\n\nYour previous response was unparseable, likely due to "
                "exceeding the output budget. Emit at most 15 fact objects, "
                "keep each claim under 80 words, total under 4096 output "
                "tokens. Strict JSON array with no narration before or after."
            )
            kwargs: dict[str, Any] = {
                "tier": "flash",
                "role": "atomic_facts",
                "max_output_tokens": 4096,
                "response_mime_type": "application/json",
            }
            try:
                return await client.generate(brief_prompt, **kwargs)
            except TypeError:
                return await client.generate(
                    brief_prompt, tier="flash", role="atomic_facts",
                    max_output_tokens=4096,
                )

        try:
            result = await _call_brief()
            raw = _parse_facts(result.text)
        except Exception as err2:
            head2 = (result.text or "")[:200]
            logger.warning(
                "atomic_facts.parse_failed url=%s err=%s head=%r (retry)",
                url,
                err2,
                head2,
            )
            cache.put(key, {"facts": [], "error": "parse_failed"})
            return []

    if isinstance(raw, dict) and "facts" in raw:
        facts = raw["facts"]
    elif isinstance(raw, list):
        facts = raw
    else:
        facts = []

    facts = facts[:30]

    expected_min = max(3, len(source_text) // 2000)
    if len(facts) < expected_min:
        logger.warning(
            "atomic_facts.underpopulated url=%s got=%d expected>=%d",
            url,
            len(facts),
            expected_min,
        )

    # Do NOT cache empty results — they're almost certainly parse/upstream failures.
    if facts:
        cache.put(key, {"facts": facts})
    return facts
