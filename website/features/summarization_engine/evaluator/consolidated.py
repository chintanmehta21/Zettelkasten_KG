"""The consolidated Gemini-Pro evaluation call."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from website.features.summarization_engine.evaluator.models import EvalResult
from website.features.summarization_engine.evaluator.numeric_grounding import (
    extract_numeric_tokens,
    numeric_validator,
)
from website.features.summarization_engine.evaluator.prompts import (
    CONSOLIDATED_SYSTEM,
    CONSOLIDATED_USER_TEMPLATE,
    PROMPT_VERSION,
)
from website.features.summarization_engine.summarization.common.json_utils import (
    parse_json_object,
)

logger = logging.getLogger(__name__)

# Lane 2 (2026-05-30 Fix #2) — Instructor-style validation-aware retry support.
#
# Minimum-viable defaults for each required EvalResult top-level field. When
# the judge omits one or more required fields AND the single validation-
# retry reprompt also fails, we synthesize these defaults to keep the
# pipeline alive AND set ``evaluator_metadata.backfilled_fields = [...]`` so
# downstream aggregators (04_compute_composite) can EXCLUDE such rows.
# Synthesized scores are deliberately neutral (0.5 / level-1 floor / empty
# lists) so they don't bias either direction if accidentally aggregated.
_EVAL_RESULT_MIN_DEFAULTS: dict[str, Any] = {
    "g_eval": {
        "coherence": {"score": 1, "anchor": "", "reasoning": "synthesized: judge omitted field"},
        "fluency":   {"score": 1, "anchor": "", "reasoning": "synthesized: judge omitted field"},
    },
    "finesure": {
        "faithfulness": {"score": 0.5, "items": []},
        "completeness": {"score": 0.5, "items": []},
        "conciseness":  {"score": 0.5, "items": []},
    },
    # summac_lite is already Optional[SummaCLite] = None on the model — list
    # it here so we don't try to inject for it (no-op via the loop guard).
    "summac_lite": None,
    "rubric": {
        "components": [],
        "anti_patterns_triggered": [],
        "caps_applied": {
            "hallucination_cap": None,
            "omission_cap": None,
            "generic_cap": None,
        },
    },
    "maps_to_metric_summary": {
        "g_eval": 0.0, "finesure": 0.0, "qafact": 0.0, "summac": 0.0,
    },
}


def _extract_missing_required_fields(exc: ValidationError) -> list[str]:
    """Pluck the names of top-level required fields the judge omitted.

    Pydantic v2 ``ValidationError.errors()`` returns a list of dicts. We
    filter for ``type == "missing"`` and take the first element of ``loc``
    (which is the top-level field name). Nested errors (e.g. a missing
    sub-field inside ``finesure``) are NOT counted as missing top-levels —
    those should bubble up untouched so the operator sees them.
    """
    missing: list[str] = []
    for err in exc.errors():
        if err.get("type") != "missing":
            continue
        loc = err.get("loc") or ()
        if not loc:
            continue
        top = loc[0]
        if isinstance(top, str) and len(loc) == 1 and top not in missing:
            missing.append(top)
    return missing


def _synth_missing_field_defaults(payload: dict, missing_fields: list[str]) -> list[str]:
    """Inject minimum-viable defaults for each missing field. Returns the
    list of fields actually backfilled (so the caller can record which ones
    were synthesized in evaluator_metadata)."""
    backfilled: list[str] = []
    for field in missing_fields:
        if field not in _EVAL_RESULT_MIN_DEFAULTS:
            # Unknown field — don't fabricate; let pydantic surface the error
            continue
        default = _EVAL_RESULT_MIN_DEFAULTS[field]
        # Note: summac_lite default is None and is already model-side-Optional;
        # injecting None is a no-op but we still flag it so the row is excluded.
        payload[field] = default
        backfilled.append(field)
    return backfilled


# Cap on number of unsupported numeric tokens reported, to keep the evaluator
# payload compact in eval-loop artifacts.
_UNSUPPORTED_NUMERIC_CAP = 5

# CF-2 R2: shape mask for which editorialization_flags must be zeroed.
# Keeps the LLM judge prompt drift from re-triggering hallucination_cap when
# a newsletter shape legitimately uses evaluative-sounding paper-fact language.
_NO_STANCE_PENALTY_SHAPES = frozenset({
    "academic_roundup",
    "link_digest",
    "news_aggregator",
    "product_announcement",
})


def compute_numeric_grounding_signal(
    summary_json: dict | None, source_text: str | None
) -> dict:
    """Faithfulness sub-signal: ratio of grounded numeric tokens to extracted ones.

    Returns a dict with two stable keys:
      - ``numeric_grounding_score`` (float in [0.0, 1.0]); 1.0 when summary has
        zero numeric tokens (vacuously grounded).
      - ``unsupported_numeric_claims`` (list[str]) capped at
        ``_UNSUPPORTED_NUMERIC_CAP`` entries.

    Raises ``TypeError`` for malformed input, with the offending key surfaced,
    so callers fail loudly instead of silently falling back to a default.
    """
    if summary_json is None:
        raise TypeError(
            "compute_numeric_grounding_signal: summary_json must not be None"
        )
    if not isinstance(summary_json, dict):
        raise TypeError(
            "compute_numeric_grounding_signal: summary_json must be dict, "
            f"got {type(summary_json).__name__}"
        )
    if source_text is None:
        raise TypeError(
            "compute_numeric_grounding_signal: source_text must not be None"
        )
    if not isinstance(source_text, str):
        raise TypeError(
            "compute_numeric_grounding_signal: source_text must be str, "
            f"got {type(source_text).__name__}"
        )

    summary_text = _flatten_summary_text(summary_json)
    tokens = extract_numeric_tokens(summary_text)
    if not tokens:
        return {
            "numeric_grounding_score": 1.0,
            "unsupported_numeric_claims": [],
        }
    result = numeric_validator(summary_text, source_text)
    ungrounded: list[str] = list(result.get("ungrounded", []))
    return {
        "numeric_grounding_score": float(result.get("ratio", 0.0)),
        "unsupported_numeric_claims": ungrounded[:_UNSUPPORTED_NUMERIC_CAP],
    }


def _flatten_summary_text(summary_json: dict) -> str:
    """Concatenate every string leaf in the summary payload.

    The summarizer's JSON shape varies per archetype (mini_title / brief /
    detailed / sections / tags / etc.). Rather than hard-code keys, we walk
    the structure and collect every string for grounding inspection.
    """
    parts: list[str] = []

    def _walk(node) -> None:
        if isinstance(node, str):
            parts.append(node)
        elif isinstance(node, dict):
            for v in node.values():
                _walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                _walk(v)

    _walk(summary_json)
    return "\n".join(parts)


class ConsolidatedEvaluator:
    def __init__(
        self,
        gemini_client: Any,
        *,
        enable_validation_retry: bool = True,
    ) -> None:
        """Build a consolidated rubric evaluator.

        Args:
            gemini_client: a Gemini client matching ``TieredGeminiClient.generate``.
            enable_validation_retry: when the judge omits required EvalResult
                top-level fields, retry ONCE with a "missing fields: X, Y, Z"
                reprompt before falling back to synth+flag. Default True for
                the eval-harness (latency-tolerant, prefers correct data).
                Production add-zettel pipelines may pass ``False`` to skip
                the retry and synth-immediately — saves 30-60s user-facing
                latency on the ~5% of zettels where the model returns an
                incomplete schema, at the cost of slightly lower data quality
                (no chance to recover via reprompt). Backfilled rows are still
                FLAGGED via ``evaluator_metadata.backfilled_fields`` and
                EXCLUDED from corpus-mean aggregates in either mode.
        """
        self._client = gemini_client
        self._enable_validation_retry = enable_validation_retry

    def _tier(self) -> str:
        cfg = getattr(self._client, "_config", None)
        if cfg is None:
            return "pro"
        return getattr(cfg.gemini, "phase_tiers", {}).get("evaluator", "pro")

    async def evaluate(
        self,
        *,
        rubric_yaml: dict,
        atomic_facts: list[dict],
        source_text: str,
        summary_json: dict,
    ) -> EvalResult:
        # CF-2 R2: surface newsletter content shape to the judge so it can
        # apply shape-aware rubric overrides (academic_roundup etc.).
        shape = str(summary_json.get("_shape", "general")) if isinstance(
            summary_json, dict
        ) else "general"
        prompt = CONSOLIDATED_USER_TEMPLATE.format(
            _shape=shape,
            rubric_yaml=yaml.safe_dump(rubric_yaml, sort_keys=False),
            atomic_facts=json.dumps(atomic_facts, indent=2),
            source_text=source_text[:30000],
            summary_json=json.dumps(summary_json, indent=2),
        )
        import asyncio as _asyncio

        t0 = time.perf_counter()
        last_text = ""
        result = None
        last_exc: Exception | None = None
        payload: dict | None = None
        for attempt in range(3):
            try:
                result = await self._client.generate(
                    prompt,
                    tier=self._tier(),
                    system_instruction=CONSOLIDATED_SYSTEM,
                    temperature=0.0,
                    max_output_tokens=32768,
                    role="rubric_evaluator",
                )
                last_text = (result.text or "").strip()
                if last_text:
                    try:
                        payload = parse_json_object(last_text)
                        last_exc = None
                        break
                    except Exception as exc:  # noqa: BLE001 - retry malformed JSON
                        last_exc = exc
            except Exception as exc:  # noqa: BLE001 — retry on any transient failure
                last_exc = exc
            if attempt < 2:
                await _asyncio.sleep(2 * (attempt + 1))
        latency_ms = int((time.perf_counter() - t0) * 1000)

        if last_exc is not None and not last_text:
            raise RuntimeError(
                f"Evaluator failed after 3 attempts: {type(last_exc).__name__}: {last_exc}"
            ) from last_exc

        if not last_text:
            raise RuntimeError(
                "Evaluator returned empty text after 3 attempts "
                f"(model={getattr(result, 'model_used', '?')}, "
                f"in={getattr(result, 'input_tokens', 0)}, "
                f"out={getattr(result, 'output_tokens', 0)})"
            )

        if payload is None:
            preview = last_text[:200].replace("\n", " ")
            raise RuntimeError(
                f"Evaluator returned non-JSON after 3 attempts: {last_exc} | preview={preview!r}"
            ) from last_exc

        payload.setdefault("evaluator_metadata", {})
        payload["evaluator_metadata"].setdefault("prompt_version", PROMPT_VERSION)
        payload["evaluator_metadata"].setdefault(
            "rubric_version", rubric_yaml.get("version", "unknown")
        )
        payload["evaluator_metadata"]["implementation_fingerprint"] = (
            evaluator_implementation_fingerprint()
        )
        payload["evaluator_metadata"]["rubric_sha256"] = rubric_sha256(rubric_yaml)
        payload["evaluator_metadata"]["model_used"] = getattr(
            result, "model_used", payload["evaluator_metadata"].get("model_used")
        )
        payload["evaluator_metadata"]["total_tokens_in"] = getattr(
            result, "input_tokens", 0
        )
        payload["evaluator_metadata"]["total_tokens_out"] = getattr(
            result, "output_tokens", 0
        )
        payload["evaluator_metadata"]["latency_ms"] = latency_ms

        # Faithfulness sub-signal: deterministic numeric grounding check
        # against the source text. Surfaced inside ``evaluator_metadata`` to
        # preserve the existing ``EvalResult`` schema (backward compatible).
        numeric_signal = compute_numeric_grounding_signal(summary_json, source_text)
        payload["evaluator_metadata"]["numeric_grounding_score"] = numeric_signal[
            "numeric_grounding_score"
        ]
        payload["evaluator_metadata"]["unsupported_numeric_claims"] = numeric_signal[
            "unsupported_numeric_claims"
        ]
        # CF-2 R2 belt-and-braces: zero editorialization_flags for shape-exempt
        # newsletters so prompt drift cannot regress to hallucination_cap.
        if shape in _NO_STANCE_PENALTY_SHAPES:
            payload["editorialization_flags"] = []
            payload["evaluator_metadata"]["editorialization_zeroed_by_shape"] = shape

        # Lane 2 (2026-05-30 Fix #2) — Instructor-style validation-aware retry.
        # When the judge omits required top-level fields (the 2026-05-28
        # wz=1c0af8ec failure mode: g_eval present, finesure/summac_lite/rubric
        # missing), reprompt ONCE with an explicit "missing fields: X, Y, Z"
        # suffix. Empirically the model self-corrects on first re-ask (our
        # patch run on the same zettel produced a complete response with
        # only 6.8k in / 3.4k out — 10% of budget). If the retry ALSO fails,
        # synthesize neutral defaults and flag the row in
        # evaluator_metadata.backfilled_fields so downstream aggregators
        # (04_compute_composite) EXCLUDE it from corpus-mean stats —
        # otherwise we'd silently bias the judge mean toward 0.5.
        payload["evaluator_metadata"].setdefault("backfilled_fields", [])
        try:
            return EvalResult(**payload)
        except ValidationError as ve:
            missing = _extract_missing_required_fields(ve)
            if not missing:
                # Validation failed for a reason OTHER than missing top-level
                # fields (e.g. nested type error). Re-raise; not our problem.
                raise

            # Production opt-out: skip retry entirely, synth + flag immediately.
            # Saves 30-60s user-facing latency on the ~5% failing zettels.
            if not self._enable_validation_retry:
                logger.warning(
                    "evaluator.validation_retry_disabled missing_fields=%s "
                    "— synth+flag (production latency mode)",
                    missing,
                )
                backfilled = _synth_missing_field_defaults(payload, missing)
                payload["evaluator_metadata"]["backfilled_fields"] = backfilled
                payload["evaluator_metadata"]["validation_retry_fired"] = False
                payload["evaluator_metadata"]["latency_ms"] = int(
                    (time.perf_counter() - t0) * 1000
                )
                try:
                    return EvalResult(**payload)
                except ValidationError as final_ve:
                    remaining = [
                        {"loc": e.get("loc"), "type": e.get("type")}
                        for e in final_ve.errors()[:5]
                    ]
                    raise RuntimeError(
                        f"Evaluator schema unrecoverable after synth "
                        f"(backfilled={backfilled}, "
                        f"remaining_errors={remaining}): {final_ve}"
                    ) from final_ve

            logger.warning(
                "evaluator.validation_retry missing_fields=%s — reprompting once",
                missing,
            )
            retry_suffix = (
                "\n\nYour previous response was missing required top-level "
                f"fields: {missing}. Re-emit the COMPLETE JSON object with "
                "ALL required top-level fields populated. Do not omit any "
                "field listed in the schema shown earlier."
            )
            retry_prompt = prompt + retry_suffix

            retry_payload: dict | None = None
            retry_result = None
            try:
                retry_result = await self._client.generate(
                    retry_prompt,
                    tier=self._tier(),
                    system_instruction=CONSOLIDATED_SYSTEM,
                    temperature=0.0,
                    max_output_tokens=32768,
                    role="rubric_evaluator",
                )
                retry_text = (retry_result.text or "").strip()
                if retry_text:
                    retry_payload = parse_json_object(retry_text)
            except Exception as retry_exc:  # noqa: BLE001
                logger.warning(
                    "evaluator.validation_retry_call_failed err=%s",
                    retry_exc,
                )

            if retry_payload is not None:
                # Re-enrich evaluator_metadata using the RETRY result's
                # token / model info so telemetry reflects what actually ran.
                retry_payload.setdefault("evaluator_metadata", {})
                # Preserve the original metadata (rubric_sha, fingerprint,
                # numeric_grounding) but overlay the call-specific fields
                # from the retry. Token counts are SUMMED across attempts —
                # total_tokens_in/out reflect the true end-to-end cost.
                # Latency is updated to the end-to-end wall-clock so the
                # retry's contribution shows up in iter telemetry.
                merged_meta = dict(payload["evaluator_metadata"])
                merged_meta["model_used"] = getattr(
                    retry_result, "model_used", merged_meta.get("model_used"),
                )
                merged_meta["total_tokens_in"] = (
                    merged_meta.get("total_tokens_in", 0)
                    + getattr(retry_result, "input_tokens", 0)
                )
                merged_meta["total_tokens_out"] = (
                    merged_meta.get("total_tokens_out", 0)
                    + getattr(retry_result, "output_tokens", 0)
                )
                merged_meta["latency_ms"] = int((time.perf_counter() - t0) * 1000)
                merged_meta["validation_retry_fired"] = True
                merged_meta["validation_retry_missing_fields"] = missing
                retry_payload["evaluator_metadata"] = merged_meta
                retry_payload["evaluator_metadata"].setdefault("backfilled_fields", [])
                try:
                    return EvalResult(**retry_payload)
                except ValidationError as ve2:
                    logger.warning(
                        "evaluator.validation_retry_failed missing=%s",
                        _extract_missing_required_fields(ve2),
                    )
                    # Fall through to synth path

            # Synth-fallback: backfill the missing fields with neutral
            # defaults so the row is constructable. CRITICAL: the row is
            # FLAGGED via backfilled_fields so it gets EXCLUDED from
            # aggregates downstream.
            backfilled = _synth_missing_field_defaults(payload, missing)
            payload["evaluator_metadata"]["backfilled_fields"] = backfilled
            payload["evaluator_metadata"]["validation_retry_fired"] = True
            payload["evaluator_metadata"]["validation_retry_succeeded"] = False
            payload["evaluator_metadata"]["latency_ms"] = int(
                (time.perf_counter() - t0) * 1000
            )
            if backfilled:
                logger.warning(
                    "evaluator.synthesized_defaults backfilled=%s "
                    "— ROW MUST BE EXCLUDED FROM AGGREGATES",
                    backfilled,
                )
            # Blocking-#1 (2026-05-30 review): synth only fills MISSING fields.
            # If the payload has other validation issues (nested OOR, type
            # mismatch, etc.) the final construction will STILL raise. We
            # surface that loudly with explicit context rather than letting
            # the raw ValidationError propagate — callers can then choose to
            # log + skip the zettel cleanly instead of treating it as a
            # transient error worth retrying.
            try:
                return EvalResult(**payload)
            except ValidationError as final_ve:
                remaining = [
                    {"loc": e.get("loc"), "type": e.get("type")}
                    for e in final_ve.errors()[:5]
                ]
                logger.error(
                    "evaluator.synth_path_still_invalid backfilled=%s "
                    "remaining_errors=%s",
                    backfilled, remaining,
                )
                raise RuntimeError(
                    f"Evaluator schema unrecoverable after synth "
                    f"(backfilled={backfilled}, "
                    f"remaining_errors={remaining}): {final_ve}"
                ) from final_ve


def evaluator_implementation_fingerprint() -> str:
    digest = hashlib.sha256()
    evaluator_dir = Path(__file__).resolve().parent
    for path in sorted(evaluator_dir.glob("*.py")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def rubric_sha256(rubric_yaml: dict) -> str:
    payload = yaml.safe_dump(rubric_yaml, sort_keys=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
