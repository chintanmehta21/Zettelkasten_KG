"""Validate the iter-03 13-query dataset (Task 4B.1).

Pins:
- 10 iter-02 queries are copied verbatim (no drift).
- 3 action-verb regression queries (av-1, av-2, av-3) are present and
  mirror the q3/q8 iter-02 failure pattern: same expected gold zettel
  (gh-zk-org-zk) under imperative wording the synthesizer over-refused on.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ITER02 = REPO_ROOT / "docs/rag_eval/common/knowledge-management/iter-02/queries.json"
ITER03 = REPO_ROOT / "docs/rag_eval/common/knowledge-management/iter-03/queries.json"


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def test_iter03_queries_file_exists():
    assert ITER03.exists(), f"missing {ITER03}"


def test_iter03_has_thirteen_queries():
    data = _load(ITER03)
    assert len(data["queries"]) == 13


def test_iter03_meta_iter_label():
    assert _load(ITER03)["_meta"]["iter"] == "03"


def test_iter03_copies_iter02_ten_verbatim():
    iter02 = {q["qid"]: q for q in _load(ITER02)["queries"]}
    iter03 = {q["qid"]: q for q in _load(ITER03)["queries"]}
    for qid in iter02:
        assert qid in iter03, f"missing iter-02 query {qid} in iter-03"
        # text + ground_truth + class + expected_primary_citation must be byte-identical
        for field in ("text", "class", "ground_truth", "expected_primary_citation",
                      "expected_minimum_citations"):
            assert iter03[qid].get(field) == iter02[qid].get(field), (
                f"iter-03 {qid}.{field} drifted from iter-02"
            )


def test_iter03_action_verb_queries_present():
    iter03 = {q["qid"]: q for q in _load(ITER03)["queries"]}
    for qid in ("av-1", "av-2", "av-3"):
        assert qid in iter03, f"missing action-verb regression query {qid}"


def test_iter03_action_verb_queries_target_correct_gold_zettel():
    iter03 = {q["qid"]: q for q in _load(ITER03)["queries"]}
    for qid in ("av-1", "av-2", "av-3"):
        q = iter03[qid]
        # Mirror q8 — gh-zk-org-zk is the buildable wiki tool zettel.
        assert q["expected_primary_citation"] == "gh-zk-org-zk", (
            f"{qid} must point at the same gold zettel as iter-02 q8"
        )
        # Backstop on source-type so a future ingest swap (web/github)
        # does not silently invalidate the regression.
        assert "github" in q["expected_top1_source_type_in"]
        # Annotation must explain the regression intent.
        assert "annotation" in q


def test_iter03_meta_links_to_baseline():
    meta = _load(ITER03)["_meta"]
    assert meta["ci_gate_baseline"].endswith("iter-03/baseline.json")
    gates = meta["ci_gates_summary"]
    assert gates["end_to_end_gold_at_1_min"] == 0.65
    assert gates["synthesizer_grounding_min"] == 0.85
    assert gates["infra_failures_max"] == 0
