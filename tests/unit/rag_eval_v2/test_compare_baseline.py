"""compare_baseline math + cross-Kasten overfit guardrail."""
from __future__ import annotations

import json


def test_delta_handles_none(compare_baseline):
    assert compare_baseline._delta(70.0, 60.0) == 10.0
    assert compare_baseline._delta(None, 60.0) is None
    assert compare_baseline._delta(70.0, None) is None


def test_compare_one_no_eval(tmp_path, compare_baseline, monkeypatch):
    monkeypatch.setattr(compare_baseline, "RAG_EVAL_V2", tmp_path)
    (tmp_path / "economics").mkdir()
    out = compare_baseline.compare_one("economics", 1)
    assert out["status"] == "no_eval"


def test_compare_one_full_delta(tmp_path, compare_baseline, monkeypatch):
    monkeypatch.setattr(compare_baseline, "RAG_EVAL_V2", tmp_path)
    kdir = tmp_path / "economics"
    (kdir / "iter-1").mkdir(parents=True)
    (kdir / "baseline_score.json").write_text(json.dumps({
        "composite": 60.0,
        "components": {"chunking": 40.0, "retrieval": 64.0,
                       "reranking": 52.0, "synthesis": 66.0},
        "holistic": {"gold_at_1_unconditional": 0.62},
    }))
    (kdir / "iter-1" / "eval.json").write_text(json.dumps({
        "composite": 70.0,
        "component_scores": {"chunking": 45.0, "retrieval": 70.0,
                             "reranking": 50.0, "synthesis": 72.0},
        "holistic": {"gold_at_1_unconditional": 0.75,
                     "accuracy_user_visible": 0.7,
                     "over_refusal_rate": 0.05,
                     "under_refusal_rate": 0.0},
    }))
    out = compare_baseline.compare_one("economics", 1)
    assert out["status"] == "ok"
    assert out["composite"]["delta"] == 10.0
    assert out["component_delta"]["reranking"] == -2.0  # regressed stage
    assert out["component_delta"]["retrieval"] == 6.0
    assert out["holistic"]["delta"]["gold_at_1_unconditional"] == 0.13


def test_compare_one_flags_low_gold_and_regression(tmp_path, compare_baseline, monkeypatch):
    monkeypatch.setattr(compare_baseline, "RAG_EVAL_V2", tmp_path)
    kdir = tmp_path / "psychedelic-drugs"
    (kdir / "iter-2").mkdir(parents=True)
    (kdir / "baseline_score.json").write_text(json.dumps({
        "composite": 60.26,
        "components": {"chunking": 40.0, "retrieval": 64.0,
                       "reranking": 52.0, "synthesis": 66.0},
        "holistic": {},
    }))
    (kdir / "iter-2" / "eval.json").write_text(json.dumps({
        "composite": 55.0,
        "component_scores": {"chunking": 30.0, "retrieval": 60.0,
                             "reranking": 50.0, "synthesis": 60.0},
        "holistic": {"gold_at_1_unconditional": 0.4, "over_refusal_rate": 0.2},
    }))
    out = compare_baseline.compare_one("psychedelic-drugs", 2)
    joined = " ".join(out["recommendations"])
    assert "composite regressed" in joined
    assert "gold@1" in joined
    assert "over_refusal_rate" in joined


def test_cross_kasten_overfit_guardrail(compare_baseline):
    per = [
        {"status": "ok",
         "composite": {"current": 70.0, "delta": 10.0},
         "holistic": {"current": {"gold_at_1_unconditional": 0.7}}},
        {"status": "ok",
         "composite": {"current": 58.0, "delta": -2.0},  # regressed on Kasten 2
         "holistic": {"current": {"gold_at_1_unconditional": 0.5}}},
    ]
    agg = compare_baseline.cross_kasten_aggregate(per)
    assert agg["n_kastens"] == 2
    assert agg["mean_composite_delta"] == 4.0
    # the guardrail: min delta is negative -> improvement is NOT uniform
    assert agg["min_composite_delta"] == -2.0
    assert "overfit" in agg["overfit_guardrail"].lower()


def test_cross_kasten_no_data(compare_baseline):
    assert compare_baseline.cross_kasten_aggregate(
        [{"status": "no_eval"}]
    )["status"] == "no_data"
