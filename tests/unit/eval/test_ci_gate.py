"""Hard CI gate (Task 4C.1) — compare iter-03 answers.json against the
frozen iter-03 baseline.json thresholds. Returns non-zero exit on failure.

The gate is invoked via `python ops/scripts/rag_eval_loop.py --enforce-gates
--queries <queries.json> --answers <answers.json> --baseline <baseline.json>`
and is the only thing the iter-03 PR-gated CI workflow runs.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ops.scripts.eval.ci_gate import (
    GateResult,
    compute_end_to_end_gold_at_1,
    compute_infra_failures,
    compute_synthesizer_grounding,
    enforce_gates,
    load_baseline,
    load_queries,
)


# ---------- baseline + queries fixtures ------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE = REPO_ROOT / "docs/rag_eval/common/knowledge-management/iter-03/baseline.json"
QUERIES = REPO_ROOT / "docs/rag_eval/common/knowledge-management/iter-03/queries.json"


def test_baseline_loads_and_exposes_three_gate_thresholds():
    b = load_baseline(BASELINE)
    assert b["ci_gates"]["end_to_end_gold_at_1_min"] == 0.65
    assert b["ci_gates"]["synthesizer_grounding_min"] == 0.85
    assert b["ci_gates"]["infra_failures_max"] == 0


def test_queries_load_returns_qid_indexed_map():
    q = load_queries(QUERIES)
    assert "q1" in q
    assert "av-1" in q
    assert q["q1"]["expected_primary_citation"] == "gh-zk-org-zk"


# ---------- gold@1 computation ---------------------------------------------


def _ans(qid: str, top_node: str | None, *, verdict: str = "supported", content: str = "x") -> dict:
    citations = [{"node_id": top_node, "rerank_score": 0.9}] if top_node else []
    return {
        "query_id": qid,
        "answer": content,
        "citations": citations,
        "retrieved_node_ids": [top_node] if top_node else [],
        "reranked_node_ids": [top_node] if top_node else [],
        "per_stage": {
            "query_class": "lookup",
            "retrieval_recall_at_10": 1.0 if top_node else 0.0,
            "reranker_top1_top2_margin": None,
            "synthesizer_grounding_pct": (
                1.0 if verdict in ("supported", "retried_supported") else
                0.5 if verdict == "partial" else 0.0
            ),
            "critic_verdict": verdict,
            "model_chain_used": ["gemini-2.5-flash"],
            "latency_ms": {"retrieval": None, "rerank": None, "synth": None, "critic": None, "total": 1000},
        },
    }


def _queries_simple() -> dict:
    return {
        "q1": {"qid": "q1", "expected_primary_citation": "gh-zk-org-zk"},
        "q2": {"qid": "q2", "expected_primary_citation": ["yt-a", "yt-b"]},
        "q9": {
            "qid": "q9",
            "expected_primary_citation": [],
            "expected_critic_verdict": "unsupported_or_partial",
        },
    }


def test_gold_at_1_string_match():
    answers = [_ans("q1", "gh-zk-org-zk")]
    out = compute_end_to_end_gold_at_1(answers, _queries_simple())
    assert out == 1.0


def test_gold_at_1_string_miss():
    answers = [_ans("q1", "yt-other")]
    assert compute_end_to_end_gold_at_1(answers, _queries_simple()) == 0.0


def test_gold_at_1_list_match():
    answers = [_ans("q2", "yt-b")]
    assert compute_end_to_end_gold_at_1(answers, _queries_simple()) == 1.0


def test_gold_at_1_adversarial_pass_on_refusal():
    answers = [_ans("q9", None, verdict="unsupported", content="I can't find that in your Zettels.")]
    assert compute_end_to_end_gold_at_1(answers, _queries_simple()) == 1.0


def test_gold_at_1_adversarial_fail_when_hallucinates():
    answers = [_ans("q9", "yt-a", verdict="supported")]
    assert compute_end_to_end_gold_at_1(answers, _queries_simple()) == 0.0


def test_gold_at_1_mixed_average():
    answers = [
        _ans("q1", "gh-zk-org-zk"),  # pass
        _ans("q2", "yt-other"),       # fail
        _ans("q9", None, verdict="partial"),  # pass (adversarial → refusal/partial ok)
    ]
    val = compute_end_to_end_gold_at_1(answers, _queries_simple())
    assert abs(val - (2 / 3)) < 1e-6


# ---------- synthesizer grounding ------------------------------------------


def test_synthesizer_grounding_average_skips_none():
    answers = [
        _ans("q1", "gh-zk-org-zk", verdict="supported"),
        _ans("q2", "yt-a", verdict="partial"),
    ]
    # Force one record to have None grounding
    answers.append({"query_id": "q3", "per_stage": {"synthesizer_grounding_pct": None}})
    val = compute_synthesizer_grounding(answers)
    assert abs(val - 0.75) < 1e-6


def test_synthesizer_grounding_empty_returns_zero():
    assert compute_synthesizer_grounding([]) == 0.0


# ---------- infra failures --------------------------------------------------


def test_infra_failures_counts_missing_per_stage():
    answers = [
        _ans("q1", "gh-zk-org-zk"),
        {"query_id": "q2", "answer": "", "infra_failure": True},
        {"query_id": "q3", "answer": ""},  # missing per_stage entirely
    ]
    assert compute_infra_failures(answers) == 2


def test_infra_failures_zero_on_clean_run():
    answers = [_ans("q1", "gh-zk-org-zk"), _ans("q2", "yt-a")]
    assert compute_infra_failures(answers) == 0


# ---------- end-to-end gate -------------------------------------------------


def _baseline_obj() -> dict:
    return {
        "ci_gates": {
            "end_to_end_gold_at_1_min": 0.65,
            "synthesizer_grounding_min": 0.85,
            "infra_failures_max": 0,
        }
    }


def test_enforce_gates_passes_on_good_run(capsys):
    answers = [_ans(f"q{i}", "gh-zk-org-zk", verdict="supported") for i in range(13)]
    queries = {f"q{i}": {"expected_primary_citation": "gh-zk-org-zk"} for i in range(13)}
    result = enforce_gates(answers=answers, queries=queries, baseline=_baseline_obj())
    assert isinstance(result, GateResult)
    assert result.exit_code == 0
    assert result.gold_at_1 == 1.0
    assert result.synthesizer_grounding == 1.0
    assert result.infra_failures == 0
    assert result.passed is True


def test_enforce_gates_fails_on_low_gold_at_1():
    answers = [_ans(f"q{i}", "yt-wrong", verdict="supported") for i in range(13)]
    queries = {f"q{i}": {"expected_primary_citation": "gh-zk-org-zk"} for i in range(13)}
    result = enforce_gates(answers=answers, queries=queries, baseline=_baseline_obj())
    assert result.exit_code == 1
    assert result.passed is False
    assert "gold_at_1" in " ".join(result.failures).lower()


def test_enforce_gates_fails_on_low_grounding():
    # All gold@1 PASS but every verdict is unsupported -> grounding 0.0
    answers = [_ans(f"q{i}", "gh-zk-org-zk", verdict="unsupported") for i in range(13)]
    queries = {f"q{i}": {"expected_primary_citation": "gh-zk-org-zk"} for i in range(13)}
    result = enforce_gates(answers=answers, queries=queries, baseline=_baseline_obj())
    assert result.exit_code == 1
    assert any("grounding" in f.lower() for f in result.failures)


def test_enforce_gates_fails_on_any_infra_failure():
    answers = [_ans(f"q{i}", "gh-zk-org-zk", verdict="supported") for i in range(12)]
    answers.append({"query_id": "q12", "answer": "", "infra_failure": True})
    queries = {f"q{i}": {"expected_primary_citation": "gh-zk-org-zk"} for i in range(13)}
    result = enforce_gates(answers=answers, queries=queries, baseline=_baseline_obj())
    assert result.exit_code == 1
    assert any("infra" in f.lower() for f in result.failures)


def test_enforce_gates_aggregates_multiple_failures():
    answers = [_ans("q1", "yt-wrong", verdict="unsupported")]
    queries = {"q1": {"expected_primary_citation": "gh-zk-org-zk"}}
    result = enforce_gates(answers=answers, queries=queries, baseline=_baseline_obj())
    assert result.exit_code == 1
    assert len(result.failures) >= 2  # both gold@1 AND grounding


# ---------- CLI invocation --------------------------------------------------


def test_cli_enforce_gates_returns_nonzero_on_failure(tmp_path):
    from ops.scripts.rag_eval_loop import _cli_dispatch

    answers_p = tmp_path / "answers.json"
    answers_p.write_text(
        json.dumps([_ans("q1", "yt-wrong", verdict="unsupported")]),
        encoding="utf-8",
    )
    queries_p = tmp_path / "queries.json"
    queries_p.write_text(
        json.dumps({"queries": [{"qid": "q1", "expected_primary_citation": "gh-zk-org-zk"}]}),
        encoding="utf-8",
    )
    baseline_p = tmp_path / "baseline.json"
    baseline_p.write_text(json.dumps(_baseline_obj()), encoding="utf-8")
    rc = _cli_dispatch(
        [
            "--enforce-gates",
            "--answers", str(answers_p),
            "--queries", str(queries_p),
            "--baseline", str(baseline_p),
        ]
    )
    assert rc == 1


def test_cli_enforce_gates_returns_zero_on_pass(tmp_path):
    from ops.scripts.rag_eval_loop import _cli_dispatch

    answers_p = tmp_path / "answers.json"
    answers_p.write_text(
        json.dumps(
            [_ans(f"q{i}", "gh-zk-org-zk", verdict="supported") for i in range(13)]
        ),
        encoding="utf-8",
    )
    queries_p = tmp_path / "queries.json"
    queries_p.write_text(
        json.dumps(
            {"queries": [{"qid": f"q{i}", "expected_primary_citation": "gh-zk-org-zk"} for i in range(13)]}
        ),
        encoding="utf-8",
    )
    baseline_p = tmp_path / "baseline.json"
    baseline_p.write_text(json.dumps(_baseline_obj()), encoding="utf-8")
    rc = _cli_dispatch(
        [
            "--enforce-gates",
            "--answers", str(answers_p),
            "--queries", str(queries_p),
            "--baseline", str(baseline_p),
        ]
    )
    assert rc == 0
