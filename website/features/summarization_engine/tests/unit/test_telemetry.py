"""Tests for ``core.telemetry.build_telemetry`` — the prod/eval splitter."""
from __future__ import annotations

from website.features.summarization_engine.core.telemetry import (
    build_telemetry,
    classify_role,
)


def test_classify_role_prod_defaults():
    assert classify_role(None) == "prod"
    assert classify_role("summarizer") == "prod"
    assert classify_role("patch") == "prod"
    assert classify_role("repair") == "prod"
    assert classify_role("dense_verify") == "prod"
    assert classify_role("unknown_future_role") == "prod"  # fail-prod, not fail-eval


def test_classify_role_eval_opt_in():
    assert classify_role("rubric_evaluator") == "eval"
    assert classify_role("atomic_facts") == "eval"
    assert classify_role("next_actions") == "eval"
    assert classify_role("finesure") == "eval"
    assert classify_role("ragas") == "eval"


def test_build_telemetry_empty_journal():
    out = build_telemetry([])
    assert out == {
        "prod_calls": {"count": 0, "tokens_in": 0, "tokens_out": 0, "total_tokens": 0, "by_model": {}},
        "eval_calls": {"count": 0, "tokens_in": 0, "tokens_out": 0, "total_tokens": 0, "by_model": {}},
        "grand_total": {"count": 0, "tokens_in": 0, "tokens_out": 0, "total_tokens": 0, "by_model": {}},
    }


def test_build_telemetry_splits_prod_and_eval():
    journal = [
        # 3 prod calls on flash (summarizer + patch + repair)
        {"role": "summarizer", "model": "gemini-2.5-flash", "input_tokens": 100, "output_tokens": 50},
        {"role": "patch", "model": "gemini-2.5-flash", "input_tokens": 30, "output_tokens": 20},
        {"role": "repair", "model": "gemini-2.5-flash-lite", "input_tokens": 10, "output_tokens": 5},
        # 2 eval calls
        {"role": "rubric_evaluator", "model": "gemini-2.5-flash", "input_tokens": 500, "output_tokens": 200},
        {"role": "atomic_facts", "model": "gemini-2.5-flash-lite", "input_tokens": 40, "output_tokens": 10},
    ]
    out = build_telemetry(journal)

    assert out["prod_calls"]["count"] == 3
    assert out["prod_calls"]["tokens_in"] == 140
    assert out["prod_calls"]["tokens_out"] == 75
    assert out["prod_calls"]["total_tokens"] == 215
    assert out["prod_calls"]["by_model"]["gemini-2.5-flash"] == {
        "count": 2,
        "tokens_in": 130,
        "tokens_out": 70,
        "total_tokens": 200,
    }
    assert out["prod_calls"]["by_model"]["gemini-2.5-flash-lite"] == {
        "count": 1,
        "tokens_in": 10,
        "tokens_out": 5,
        "total_tokens": 15,
    }

    assert out["eval_calls"]["count"] == 2
    assert out["eval_calls"]["total_tokens"] == 750
    assert out["eval_calls"]["by_model"]["gemini-2.5-flash"]["count"] == 1
    assert out["eval_calls"]["by_model"]["gemini-2.5-flash-lite"]["count"] == 1

    assert out["grand_total"]["count"] == 5
    assert out["grand_total"]["total_tokens"] == 965


def test_build_telemetry_missing_model_falls_back_to_unknown():
    journal = [{"role": "summarizer", "input_tokens": 5, "output_tokens": 3}]
    out = build_telemetry(journal)
    assert "unknown" in out["prod_calls"]["by_model"]
    assert out["prod_calls"]["by_model"]["unknown"]["count"] == 1


def test_build_telemetry_tolerates_missing_tokens():
    # A partial capture (e.g. a failure before usage_metadata was read)
    # should not raise — missing fields default to zero.
    journal = [{"role": "summarizer", "model": "gemini-2.5-flash"}]
    out = build_telemetry(journal)
    assert out["prod_calls"]["count"] == 1
    assert out["prod_calls"]["total_tokens"] == 0


def test_build_telemetry_uses_model_used_fallback():
    # When ``model`` is absent but ``model_used`` is present, prefer it.
    journal = [
        {
            "role": "summarizer",
            "model_used": "gemini-2.5-flash-lite",
            "input_tokens": 1,
            "output_tokens": 1,
        }
    ]
    out = build_telemetry(journal)
    assert "gemini-2.5-flash-lite" in out["prod_calls"]["by_model"]


def test_build_telemetry_unknown_role_is_prod():
    # Unknown roles default to prod so forgetting a role tag never
    # silently drops a prod call out of the prod bucket.
    journal = [
        {"role": "brand_new_role_nobody_registered", "model": "gemini-2.5-flash", "input_tokens": 1, "output_tokens": 1},
    ]
    out = build_telemetry(journal)
    assert out["prod_calls"]["count"] == 1
    assert out["eval_calls"]["count"] == 0
