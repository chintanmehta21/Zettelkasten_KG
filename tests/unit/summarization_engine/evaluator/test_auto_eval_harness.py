"""Tests for the auto-eval harness."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from website.features.summarization_engine.evaluator.auto_eval_harness import (
    AutoEvalConfig,
    AutoEvalSchemaError,
    emit_scorecard_json,
    load_rubric,
    run_auto_eval,
    score_summary,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
RUBRIC_YT = REPO_ROOT / "docs" / "summary_eval" / "_config" / "rubric_youtube.yaml"


# ---- Inline minimal rubric used by anti-pattern tests --------------------- #


def _toy_rubric_dict() -> dict:
    return {
        "version": "rubric_toy.v1",
        "source_type": "toy",
        "composite_max_points": 100,
        "components": [
            {
                "id": "brief",
                "max_points": 60,
                "criteria": [
                    {"id": "brief.thesis", "max_points": 30},
                    {"id": "brief.format", "max_points": 30},
                ],
            },
            {
                "id": "tags",
                "max_points": 40,
                "criteria": [
                    {"id": "tags.count", "max_points": 20},
                    {"id": "tags.specificity", "max_points": 20},
                ],
            },
        ],
        "anti_patterns": [
            {
                "id": "missing_closing_remarks",
                "auto_cap": 70,
                "detection_field": "Closing remarks",
            },
            {
                "id": "verbatim_example",
                "penalty_points": 5,
            },
        ],
    }


def _write_rubric(tmp_path: Path, payload: dict) -> Path:
    import yaml
    p = tmp_path / "rubric_toy.yaml"
    p.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return p


def _full_credit_payload() -> dict:
    return {
        "url": "https://example.com/a",
        "criterion_scores": {
            "brief.thesis": 30,
            "brief.format": 30,
            "tags.count": 20,
            "tags.specificity": 20,
        },
        "anti_patterns_triggered": [],
        "fields_present": {"Closing remarks": True},
    }


# ---- load_rubric ---------------------------------------------------------- #


def test_load_rubric_round_trip_real_youtube():
    """Round-trip the real production rubric — sanity check the schema."""
    data = load_rubric(RUBRIC_YT)
    assert data["source_type"] == "youtube"
    assert data["composite_max_points"] == 100
    assert any(c["id"] == "brief_summary" for c in data["components"])
    # Anti-patterns are present and well-formed
    assert any(ap["id"] == "speakers_absent" for ap in data["anti_patterns"])


def test_load_rubric_missing_top_key_raises(tmp_path: Path):
    bad = _toy_rubric_dict()
    del bad["composite_max_points"]
    p = _write_rubric(tmp_path, bad)
    with pytest.raises(AutoEvalSchemaError, match="composite_max_points"):
        load_rubric(p)


def test_load_rubric_missing_criterion_key_raises(tmp_path: Path):
    bad = _toy_rubric_dict()
    del bad["components"][0]["criteria"][0]["max_points"]
    p = _write_rubric(tmp_path, bad)
    with pytest.raises(AutoEvalSchemaError, match="max_points"):
        load_rubric(p)


# ---- score_summary -------------------------------------------------------- #


def test_score_summary_full_credit_hits_composite_max(tmp_path: Path):
    rubric = _toy_rubric_dict()
    result = score_summary(_full_credit_payload(), rubric)
    assert result["composite"] == 100
    assert result["category_scores"] == {"brief": 60, "tags": 40}
    assert result["anti_patterns_triggered"] == []
    assert result["auto_cap_applied"] is None
    assert result["penalty_points"] == 0


def test_score_summary_anti_pattern_via_detection_field_caps_composite():
    """Missing 'Closing remarks' must fire missing_closing_remarks (auto_cap=70)."""
    rubric = _toy_rubric_dict()
    payload = _full_credit_payload()
    payload["fields_present"]["Closing remarks"] = False
    result = score_summary(payload, rubric)
    assert "missing_closing_remarks" in result["anti_patterns_triggered"]
    assert result["auto_cap_applied"] == 70
    assert result["composite"] == 70


def test_score_summary_penalty_points_subtract():
    rubric = _toy_rubric_dict()
    payload = _full_credit_payload()
    payload["anti_patterns_triggered"] = ["verbatim_example"]
    result = score_summary(payload, rubric)
    assert result["penalty_points"] == 5
    assert result["composite"] == 95


def test_score_summary_clamps_negative_to_zero():
    rubric = _toy_rubric_dict()
    rubric["anti_patterns"].append({"id": "huge", "penalty_points": 999})
    payload = _full_credit_payload()
    payload["anti_patterns_triggered"] = ["huge"]
    result = score_summary(payload, rubric)
    assert result["composite"] == 0


def test_score_summary_partial_credit_clamps_per_component():
    rubric = _toy_rubric_dict()
    payload = _full_credit_payload()
    # Over-allocated criterion gets clamped to its max (30), then component
    # is summed and clamped to comp max (60).
    payload["criterion_scores"]["brief.thesis"] = 9999
    result = score_summary(payload, rubric)
    assert result["category_scores"]["brief"] == 60


# ---- run_auto_eval -------------------------------------------------------- #


def _write_summary(tmp_path: Path, name: str, payload: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_run_auto_eval_aggregate_shape(tmp_path: Path):
    rubric_path = _write_rubric(tmp_path, _toy_rubric_dict())

    s1 = _write_summary(tmp_path, "s1.json", _full_credit_payload())  # 100
    p2 = _full_credit_payload()
    p2["fields_present"]["Closing remarks"] = False  # cap at 70
    s2 = _write_summary(tmp_path, "s2.json", p2)
    p3 = _full_credit_payload()
    p3["anti_patterns_triggered"] = ["verbatim_example"]  # 95
    s3 = _write_summary(tmp_path, "s3.json", p3)

    config = AutoEvalConfig(
        source_type="toy",
        rubric_path=rubric_path,
        summaries=[s1, s2, s3],
        pass_threshold=85,
    )
    result = run_auto_eval(config)

    assert result["summaries_scored"] == 3
    # composites: [100, 70, 95] → mean 88.33, p50 95
    assert result["mean_composite"] == pytest.approx(88.33, abs=0.01)
    assert result["p50"] == 95
    assert "p10" in result
    assert result["passed_threshold"] == 2  # 100, 95 >= 85; 70 fails
    assert result["threshold"] == 85
    assert len(result["per_summary"]) == 3
    assert {row["composite"] for row in result["per_summary"]} == {100, 70, 95}


# ---- emit_scorecard_json -------------------------------------------------- #


def test_emit_scorecard_json_round_trip(tmp_path: Path):
    rubric_path = _write_rubric(tmp_path, _toy_rubric_dict())
    s1 = _write_summary(tmp_path, "s1.json", _full_credit_payload())
    config = AutoEvalConfig(
        source_type="toy",
        rubric_path=rubric_path,
        summaries=[s1],
        pass_threshold=85,
    )
    result = run_auto_eval(config)

    out = tmp_path / "out" / "scorecard.json"
    written = emit_scorecard_json(result, out)
    assert written == out
    assert out.exists()
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["summaries_scored"] == 1
    assert loaded["mean_composite"] == 100.0
    assert loaded["per_summary"][0]["composite"] == 100
