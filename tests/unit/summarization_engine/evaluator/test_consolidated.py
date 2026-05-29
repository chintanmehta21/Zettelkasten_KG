import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from website.features.summarization_engine.evaluator.consolidated import (
    ConsolidatedEvaluator,
    evaluator_implementation_fingerprint,
    rubric_sha256,
)
from website.features.summarization_engine.evaluator.models import EvalResult


_GOOD_RESPONSE = {
    "g_eval": {
        "coherence": {"score": 3, "anchor": "1=disjointed,2=minor jumps,3=logical", "reasoning": "ok"},
        "fluency": {"score": 3, "anchor": "1=ungrammatical,2=minor errors,3=clean", "reasoning": "ok"},
    },
    "finesure": {
        "faithfulness": {"score": 0.95, "items": []},
        "completeness": {"score": 0.88, "items": []},
        "conciseness": {"score": 0.9, "items": []},
    },
    "summac_lite": {
        "score": 0.93,
        "contradicted_sentences": [],
        "neutral_sentences": [],
    },
    "rubric": {
        "components": [
            {
                "id": "brief_summary",
                "score": 22,
                "max_points": 25,
                "criteria_fired": [],
                "criteria_missed": [],
            },
            {
                "id": "detailed_summary",
                "score": 40,
                "max_points": 45,
                "criteria_fired": [],
                "criteria_missed": [],
            },
            {
                "id": "tags",
                "score": 13,
                "max_points": 15,
                "criteria_fired": [],
                "criteria_missed": [],
            },
            {
                "id": "label",
                "score": 14,
                "max_points": 15,
                "criteria_fired": [],
                "criteria_missed": [],
            },
        ],
        "caps_applied": {
            "hallucination_cap": None,
            "omission_cap": None,
            "generic_cap": None,
        },
        "anti_patterns_triggered": [],
    },
    "maps_to_metric_summary": {
        "g_eval_composite": 90,
        "finesure_composite": 91,
        "qafact_composite": 90,
        "summac_composite": 93,
    },
    "editorialization_flags": [],
    "evaluator_metadata": {
        "prompt_version": "evaluator.v1",
        "rubric_version": "rubric_youtube.v1",
        "atomic_facts_hash": "abc",
        "model_used": "gemini-2.5-pro",
        "total_tokens_in": 100,
        "total_tokens_out": 50,
        "latency_ms": 1500,
    },
}


@pytest.mark.asyncio
async def test_consolidated_evaluator_parses_response():
    client = MagicMock()
    client._config = MagicMock()
    client._config.gemini.phase_tiers = {"evaluator": "flash"}
    client.generate = AsyncMock(
        return_value=MagicMock(
            text=json.dumps(_GOOD_RESPONSE),
            input_tokens=100,
            output_tokens=50,
            model_used="gemini-2.5-flash",
        )
    )

    evaluator = ConsolidatedEvaluator(client)
    result = await evaluator.evaluate(
        rubric_yaml={
            "version": "rubric_youtube.v1",
            "composite_max_points": 100,
            "source_type": "youtube",
            "components": [],
        },
        atomic_facts=[{"claim": "x", "importance": 3}],
        source_text="source",
        summary_json={"mini_title": "t"},
    )

    assert isinstance(result, EvalResult)
    assert result.rubric.total_of_100 == 89
    assert result.evaluator_metadata["model_used"] == "gemini-2.5-flash"
    assert (
        result.evaluator_metadata["implementation_fingerprint"]
        == evaluator_implementation_fingerprint()
    )
    assert result.evaluator_metadata["rubric_sha256"] == rubric_sha256(
        {
            "version": "rubric_youtube.v1",
            "composite_max_points": 100,
            "source_type": "youtube",
            "components": [],
        }
    )
    assert client.generate.await_args.kwargs["tier"] == "flash"


@pytest.mark.asyncio
async def test_consolidated_evaluator_retries_malformed_json():
    client = MagicMock()
    client._config = MagicMock()
    client._config.gemini.phase_tiers = {"evaluator": "flash"}
    client.generate = AsyncMock(
        side_effect=[
            MagicMock(
                text='```json\n{"g_eval": {"reasoning": "bad "quote""}}\n```',
                input_tokens=100,
                output_tokens=50,
                model_used="gemini-2.5-flash",
            ),
            MagicMock(
                text=json.dumps(_GOOD_RESPONSE),
                input_tokens=101,
                output_tokens=51,
                model_used="gemini-2.5-flash",
            ),
        ]
    )

    evaluator = ConsolidatedEvaluator(client)
    result = await evaluator.evaluate(
        rubric_yaml={
            "version": "rubric_youtube.v1",
            "composite_max_points": 100,
            "source_type": "youtube",
            "components": [],
        },
        atomic_facts=[{"claim": "x", "importance": 3}],
        source_text="source",
        summary_json={"mini_title": "t"},
    )

    assert isinstance(result, EvalResult)
    assert client.generate.await_count == 2
    assert result.evaluator_metadata["total_tokens_in"] == 101


# ---------------------------------------------------------------------------
# CF-2 R2: shape-aware judge prompt + editorialization_flags hard gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_judge_prompt_carries_shape_mask_text_for_academic_roundup():
    """When summary_json._shape == academic_roundup, the rendered judge prompt
    must contain the shape-mask override telling the judge NOT to apply
    editorialization_penalty for paper-fact language."""
    client = MagicMock()
    client._config = MagicMock()
    client._config.gemini.phase_tiers = {"evaluator": "flash"}
    flagged = dict(_GOOD_RESPONSE)
    flagged["editorialization_flags"] = [
        {"sentence": "novel synthesis", "flag_type": "added_judgment", "explanation": ""},
        {"sentence": "efficient route", "flag_type": "added_stance", "explanation": ""},
        {"sentence": "broad scope", "flag_type": "added_framing", "explanation": ""},
    ]
    client.generate = AsyncMock(
        return_value=MagicMock(
            text=json.dumps(flagged),
            input_tokens=100,
            output_tokens=50,
            model_used="gemini-2.5-flash",
        )
    )

    evaluator = ConsolidatedEvaluator(client)
    result = await evaluator.evaluate(
        rubric_yaml={"version": "v1", "components": []},
        atomic_facts=[],
        source_text="source",
        summary_json={"mini_title": "t", "_shape": "academic_roundup"},
    )

    sent_prompt = client.generate.await_args.args[0]
    assert "CONTENT_SHAPE: academic_roundup" in sent_prompt
    assert "do NOT apply editorialization_penalty" in sent_prompt
    # Hard gate must zero editorialization_flags for shape-exempt newsletters.
    assert result.editorialization_flags == []
    assert (
        result.evaluator_metadata["editorialization_zeroed_by_shape"]
        == "academic_roundup"
    )


@pytest.mark.asyncio
async def test_judge_prompt_defaults_shape_to_general_when_absent():
    client = MagicMock()
    client._config = MagicMock()
    client._config.gemini.phase_tiers = {"evaluator": "flash"}
    flagged = dict(_GOOD_RESPONSE)
    flagged["editorialization_flags"] = [
        {"sentence": "stance", "flag_type": "added_stance", "explanation": ""}
    ]
    client.generate = AsyncMock(
        return_value=MagicMock(
            text=json.dumps(flagged),
            input_tokens=100,
            output_tokens=50,
            model_used="gemini-2.5-flash",
        )
    )

    evaluator = ConsolidatedEvaluator(client)
    result = await evaluator.evaluate(
        rubric_yaml={"version": "v1", "components": []},
        atomic_facts=[],
        source_text="source",
        summary_json={"mini_title": "t"},   # no _shape key
    )

    sent_prompt = client.generate.await_args.args[0]
    assert "CONTENT_SHAPE: general" in sent_prompt
    # General shape is NOT exempt; flags must be preserved.
    assert len(result.editorialization_flags) == 1
    assert "editorialization_zeroed_by_shape" not in result.evaluator_metadata


# ---------------------------------------------------------------------------
# Fix #2 (2026-05-30) — Instructor-style validation-aware retry + synth flag
# ---------------------------------------------------------------------------
# Pre-fix: ConsolidatedEvaluator did ``return EvalResult(**payload)`` — if the
# judge omitted required top-level fields (wz=1c0af8ec 2026-05-28: 3 missing),
# Pydantic raised and the whole zettel evaluation failed.
# Post-fix: on ValidationError with missing top-level fields, ONE retry with
# an Instructor-style "missing fields: X, Y, Z" reprompt. On second failure,
# synthesize neutral defaults and tag ``evaluator_metadata.backfilled_fields``
# so 04_compute_composite excludes the row from aggregates.


def test_extract_missing_required_fields_filters_top_level_only():
    """The helper must extract ONLY top-level missing fields, not nested
    type errors. Nested errors should bubble up untouched."""
    from pydantic import ValidationError
    from website.features.summarization_engine.evaluator.consolidated import (
        _extract_missing_required_fields,
    )
    from website.features.summarization_engine.evaluator.models import EvalResult

    # Top-level missing: summac_lite (already Optional after Fix-2026-05-28),
    # so test with finesure + rubric + maps_to_metric_summary missing.
    bare = {"g_eval": {"coherence": {"score": 2}, "fluency": {"score": 2}},
             "evaluator_metadata": {}}
    try:
        EvalResult.model_validate(bare)
        raise AssertionError("expected ValidationError")
    except ValidationError as ve:
        missing = _extract_missing_required_fields(ve)

    # Order may vary by pydantic version; check membership
    assert "finesure" in missing
    assert "rubric" in missing
    assert "maps_to_metric_summary" in missing
    # g_eval IS present — must not appear
    assert "g_eval" not in missing


def test_extract_missing_required_fields_ignores_nested_missing():
    """A missing nested field (e.g. finesure.faithfulness) must NOT be
    reported as a top-level missing field — those are different bugs that
    need different handling."""
    from pydantic import ValidationError
    from website.features.summarization_engine.evaluator.consolidated import (
        _extract_missing_required_fields,
    )
    from website.features.summarization_engine.evaluator.models import EvalResult

    # finesure present but missing the required sub-fields
    bad_nested = {
        "g_eval": {"coherence": {"score": 2}, "fluency": {"score": 2}},
        "finesure": {},  # missing faithfulness, completeness, conciseness
        "rubric": {"components": [], "anti_patterns_triggered": [],
                    "caps_applied": {"hallucination_cap": None,
                                      "omission_cap": None, "generic_cap": None}},
        "maps_to_metric_summary": {},
        "evaluator_metadata": {},
    }
    try:
        EvalResult.model_validate(bad_nested)
        raise AssertionError("expected ValidationError")
    except ValidationError as ve:
        missing = _extract_missing_required_fields(ve)
    # Nested errors → no top-level missing fields reported
    assert "finesure" not in missing
    assert missing == [] or all(m not in ("finesure", "g_eval", "rubric") for m in missing)


def test_synth_missing_field_defaults_populates_known_fields():
    """Helper injects minimum-viable defaults; returns list of fields actually
    backfilled. Unknown fields are skipped (no fabrication)."""
    from website.features.summarization_engine.evaluator.consolidated import (
        _synth_missing_field_defaults,
    )
    payload = {"g_eval": {"coherence": {"score": 2}, "fluency": {"score": 2}}}
    backfilled = _synth_missing_field_defaults(
        payload, ["finesure", "rubric", "unknown_field"]
    )
    assert "finesure" in payload
    assert "rubric" in payload
    assert "unknown_field" not in payload  # never fabricated
    assert backfilled == ["finesure", "rubric"]


@pytest.mark.asyncio
async def test_evaluate_retries_on_missing_required_fields_and_recovers():
    """Pre-fix: ValidationError raised straight to caller, zettel eval failed.
    Post-fix: ONE retry with reprompt — second response is complete, no synth
    needed, evaluator_metadata.backfilled_fields stays empty.

    Also verifies: validation_retry_fired=True, retry's tokens are merged
    into the metadata totals (so cost telemetry reflects reality)."""
    # First response: missing finesure + rubric + maps_to_metric_summary
    bad_response = {
        "g_eval": {
            "coherence": {"score": 2, "anchor": "", "reasoning": ""},
            "fluency": {"score": 2, "anchor": "", "reasoning": ""},
        },
        # finesure, rubric, maps_to_metric_summary intentionally omitted
        "evaluator_metadata": {},
    }
    client = MagicMock()
    client._config = MagicMock()
    client._config.gemini.phase_tiers = {"evaluator": "flash"}
    client.generate = AsyncMock(side_effect=[
        MagicMock(text=json.dumps(bad_response),
                   input_tokens=100, output_tokens=50,
                   model_used="gemini-2.5-flash"),
        MagicMock(text=json.dumps(_GOOD_RESPONSE),
                   input_tokens=110, output_tokens=60,
                   model_used="gemini-2.5-flash"),
    ])

    evaluator = ConsolidatedEvaluator(client)
    result = await evaluator.evaluate(
        rubric_yaml={"version": "v1", "components": []},
        atomic_facts=[],
        source_text="source",
        summary_json={"mini_title": "t"},
    )

    assert isinstance(result, EvalResult)
    # Retry fired exactly once → 2 generate calls
    assert client.generate.await_count == 2
    # Reprompt must include the missing-fields directive
    retry_prompt = client.generate.await_args_list[1].args[0]
    assert "missing required top-level fields" in retry_prompt
    assert "finesure" in retry_prompt
    assert "rubric" in retry_prompt
    # Metadata flags the retry; tokens merged
    meta = result.evaluator_metadata
    assert meta.get("validation_retry_fired") is True
    assert meta.get("backfilled_fields") == []  # full recovery, no synth
    # Token totals = first attempt + retry (merged)
    assert meta["total_tokens_in"] >= 100 + 110
    assert meta["total_tokens_out"] >= 50 + 60


@pytest.mark.asyncio
async def test_evaluate_synths_defaults_when_retry_also_fails():
    """If both the original call AND the retry omit required fields, the
    evaluator synthesizes neutral defaults and FLAGS the row so downstream
    aggregators exclude it. The whole zettel eval must NOT fail — partial
    data is still useful (NLI / atomic_facts are independent signals)."""
    # Both responses missing finesure + rubric + maps_to_metric_summary
    bad_response = {
        "g_eval": {
            "coherence": {"score": 2, "anchor": "", "reasoning": ""},
            "fluency": {"score": 2, "anchor": "", "reasoning": ""},
        },
        "evaluator_metadata": {},
    }
    client = MagicMock()
    client._config = MagicMock()
    client._config.gemini.phase_tiers = {"evaluator": "flash"}
    client.generate = AsyncMock(side_effect=[
        MagicMock(text=json.dumps(bad_response),
                   input_tokens=100, output_tokens=50,
                   model_used="gemini-2.5-flash"),
        MagicMock(text=json.dumps(bad_response),  # retry ALSO incomplete
                   input_tokens=100, output_tokens=50,
                   model_used="gemini-2.5-flash"),
    ])

    evaluator = ConsolidatedEvaluator(client)
    result = await evaluator.evaluate(
        rubric_yaml={"version": "v1", "components": []},
        atomic_facts=[],
        source_text="source",
        summary_json={"mini_title": "t"},
    )

    # Result was constructed (no exception bubbled to caller)
    assert isinstance(result, EvalResult)
    # CRITICAL: backfilled_fields is non-empty → row will be EXCLUDED from
    # corpus-mean aggregates by 04_compute_composite.
    meta = result.evaluator_metadata
    assert set(meta["backfilled_fields"]) >= {"finesure", "rubric", "maps_to_metric_summary"}
    assert meta.get("validation_retry_fired") is True
    assert meta.get("validation_retry_succeeded") is False
    # g_eval came from the model — should NOT be synthesized
    assert result.g_eval.coherence.score == 2
    # finesure was synthesized — scores at neutral 0.5
    assert result.finesure.faithfulness.score == 0.5


@pytest.mark.asyncio
async def test_evaluate_synth_path_raises_runtime_error_on_nested_errors():
    """Blocking #1 from Fix #2 review (2026-05-30): synth path only fills
    missing top-level fields. If the payload has nested validation issues
    (e.g. g_eval.coherence.score = 99 outside [1,3]), the final EvalResult
    construction must STILL raise — but as a clean RuntimeError with
    explicit context, not a raw ValidationError. Without this, the synth
    path would silently swallow nested type errors and corrupt downstream
    analytics."""
    # g_eval present BUT missing the inner 'fluency' field (nested-missing,
    # NOT top-level missing) AND missing finesure/rubric/maps (top-level).
    # My helper extracts only top-level → synth fills finesure/rubric/maps;
    # the inner g_eval.fluency error survives → final construction raises.
    # GEvalScores's _to_score validator coerces most numeric out-of-range
    # values; nested-missing is the cleanest way to bypass coercion.
    bad = {
        "g_eval": {
            "coherence": {"score": 2, "anchor": "", "reasoning": ""},
            # fluency intentionally omitted — nested missing
        },
        "evaluator_metadata": {},
    }
    client = MagicMock()
    client._config = MagicMock()
    client._config.gemini.phase_tiers = {"evaluator": "flash"}
    client.generate = AsyncMock(side_effect=[
        MagicMock(text=json.dumps(bad), input_tokens=100, output_tokens=50,
                   model_used="gemini-2.5-flash"),
        MagicMock(text=json.dumps(bad), input_tokens=100, output_tokens=50,
                   model_used="gemini-2.5-flash"),
    ])
    evaluator = ConsolidatedEvaluator(client)
    with pytest.raises(RuntimeError) as exc_info:
        await evaluator.evaluate(
            rubric_yaml={"version": "v1", "components": []},
            atomic_facts=[], source_text="src", summary_json={"mini_title": "t"},
        )
    assert "Evaluator schema unrecoverable after synth" in str(exc_info.value)
    # Backfilled fields must be in the error message so the caller knows
    # WHICH fields were synthesized vs. which still failed
    assert "backfilled=" in str(exc_info.value)


@pytest.mark.asyncio
async def test_evaluate_production_opt_out_skips_retry_and_synths_immediately():
    """Important #2 from Fix #2 review (2026-05-30): production callers can
    pass ``enable_validation_retry=False`` to skip the retry path and synth
    immediately — saves 30-60s user-facing latency on the ~5% failing zettels.
    Backfilled rows are still FLAGGED so they're excluded from aggregates."""
    bad = {
        "g_eval": {
            "coherence": {"score": 2, "anchor": "", "reasoning": ""},
            "fluency":   {"score": 2, "anchor": "", "reasoning": ""},
        },
        "evaluator_metadata": {},
    }
    client = MagicMock()
    client._config = MagicMock()
    client._config.gemini.phase_tiers = {"evaluator": "flash"}
    client.generate = AsyncMock(return_value=MagicMock(
        text=json.dumps(bad), input_tokens=100, output_tokens=50,
        model_used="gemini-2.5-flash",
    ))
    # enable_validation_retry=False → no retry call, straight to synth
    evaluator = ConsolidatedEvaluator(client, enable_validation_retry=False)
    result = await evaluator.evaluate(
        rubric_yaml={"version": "v1", "components": []},
        atomic_facts=[], source_text="src", summary_json={"mini_title": "t"},
    )
    # EXACTLY 1 generate call — production latency mode skips the retry
    assert client.generate.await_count == 1
    meta = result.evaluator_metadata
    # Synth populated; validation_retry_fired explicitly False (production knows
    # they opted out — not "we tried and gave up")
    assert set(meta["backfilled_fields"]) >= {"finesure", "rubric", "maps_to_metric_summary"}
    assert meta["validation_retry_fired"] is False


def test_aggregable_rows_helper_filters_backfilled_only():
    """Important #1 from Fix #2 review (2026-05-30): shared helper at
    docs/zettel_eval_v1/scripts/lib/aggregable.py is the single point of
    truth for the exclusion. Future aggregators (06_run_stats, 11_select_best,
    07_diff_runs, ...) import from here so the filter logic can't drift."""
    import importlib.util
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[4]
    spec_path = repo_root / "docs" / "zettel_eval_v1" / "scripts" / "lib" / "aggregable.py"
    spec = importlib.util.spec_from_file_location("aggregable_test", spec_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    rows = [
        {"composite": 70.0, "backfilled": 0},
        {"composite": 30.0, "backfilled": 1},  # excluded
        {"composite": 80.0},                    # no backfilled column → aggregable
        {"composite": 50.0, "backfilled": 1},  # excluded
    ]
    out = mod.aggregable_rows(rows)
    assert len(out) == 2
    assert [r["composite"] for r in out] == [70.0, 80.0]
    assert mod.excluded_count(rows) == 2
    assert mod.is_aggregable_row({"backfilled": 0}) is True
    assert mod.is_aggregable_row({"backfilled": 1}) is False
    assert mod.is_aggregable_row({}) is True  # legacy CSV w/o column


@pytest.mark.asyncio
async def test_evaluate_happy_path_does_not_set_backfilled_fields():
    """Sanity: when the judge returns a complete response on the first try,
    backfilled_fields stays empty (no retry, no synth, no telemetry bloat)."""
    client = MagicMock()
    client._config = MagicMock()
    client._config.gemini.phase_tiers = {"evaluator": "flash"}
    client.generate = AsyncMock(return_value=MagicMock(
        text=json.dumps(_GOOD_RESPONSE),
        input_tokens=100, output_tokens=50, model_used="gemini-2.5-flash",
    ))
    evaluator = ConsolidatedEvaluator(client)
    result = await evaluator.evaluate(
        rubric_yaml={"version": "v1", "components": []},
        atomic_facts=[], source_text="src", summary_json={"mini_title": "t"},
    )
    assert client.generate.await_count == 1
    meta = result.evaluator_metadata
    assert meta.get("backfilled_fields") == []
    assert meta.get("validation_retry_fired") is None


def test_prompt_version_bumped_to_v7():
    from website.features.summarization_engine.evaluator.prompts import PROMPT_VERSION

    assert PROMPT_VERSION == "evaluator.v7"
