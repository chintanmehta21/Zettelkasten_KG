"""C#1: declared-refusal vs resolution-failure in score_rag_eval.

A query whose ``expected_primary_citation`` is empty/absent is a DECLARED
refusal and is legitimately scored as a refusal. A query that declares a
non-empty needle but resolves (via expected_overrides) to zero gold ids is a
RESOLUTION FAILURE — NOT a refusal. It must be segregated as ``unscorable``,
excluded from the gold set + holistic, and surfaced loudly in the scorecard.
Previously it was silently reclassified ``expected_behavior="refuse"`` and
mis-scored a should-have-answered query as a refusal.
"""
from __future__ import annotations

from types import SimpleNamespace

from ops.scripts.score_rag_eval import _build_gold_queries, _render_scores_md


def _doc(queries: list[dict]) -> dict:
    return {"queries": queries, "_meta": {}}


def test_declared_refusal_is_still_scored_as_refusal():
    """Empty/absent expected_primary_citation -> declared refusal -> stays a
    refusal (legitimate, unchanged behavior), NOT unscorable."""
    doc = _doc([
        {"qid": "q11", "text": "adversarial nonsense?",
         "expected_primary_citation": "", "ground_truth": ""},
    ])
    gold, unscorable = _build_gold_queries(doc, {})
    assert unscorable == []
    assert len(gold) == 1
    assert gold[0].id == "q11"
    assert gold[0].expected_behavior == "refuse"


def test_absent_expected_key_is_declared_refusal():
    doc = _doc([
        {"qid": "qX", "text": "no expected key at all", "ground_truth": ""},
    ])
    gold, unscorable = _build_gold_queries(doc, {})
    assert unscorable == []
    assert gold[0].expected_behavior == "refuse"


def test_resolution_failure_is_unscorable_not_refusal():
    """Non-empty needle that resolved to nothing -> RESOLUTION FAILURE ->
    unscorable, excluded from gold, NOT a refusal.

    The harness ALWAYS adds the qid to expected_overrides (resolution was
    attempted); an empty list means the title substring matched no ingested
    zettel. The raw-needle fallback must NOT mask this."""
    doc = _doc([
        {"qid": "q5", "text": "what does the economics zettel say?",
         "expected_primary_citation": "India 1991 balance of payments",
         "ground_truth": "facts"},
    ])
    gold, unscorable = _build_gold_queries(doc, {"q5": []})
    assert unscorable == ["q5"]
    assert gold == []  # excluded entirely — never reaches EvalRunner


def test_legacy_literal_node_id_without_resolution_still_scores():
    """Backward-compat: a v1 queries.json that declares a LITERAL node-id and
    for which NO resolution was attempted (qid absent from overrides) keeps
    the legacy raw-string fallback — scored as a normal answer query."""
    doc = _doc([
        {"qid": "qL", "text": "q", "expected_primary_citation": "yt-attention",
         "ground_truth": "g"},
    ])
    gold, unscorable = _build_gold_queries(doc, {})  # no resolution attempted
    assert unscorable == []
    assert len(gold) == 1
    assert gold[0].expected_behavior == "answer"
    assert gold[0].gold_node_ids == ["yt-attention"]


def test_resolution_failure_empty_override_list_is_unscorable():
    """expected_overrides[qid] == [] (explicit empty) with a declared needle
    is still a resolution failure, not a refusal."""
    doc = _doc([
        {"qid": "q7", "text": "q",
         "expected_primary_citation": ["Some Title"], "ground_truth": "g"},
    ])
    gold, unscorable = _build_gold_queries(doc, {"q7": []})
    assert unscorable == ["q7"]
    assert gold == []


def test_resolved_query_is_scored_normally():
    """Declared needle that DID resolve -> normal answer query, not
    unscorable, not refusal."""
    doc = _doc([
        {"qid": "q1", "text": "q",
         "expected_primary_citation": "Attention Is All You Need",
         "ground_truth": "transformers; attention"},
    ])
    gold, unscorable = _build_gold_queries(doc, {"q1": ["z-attention"]})
    assert unscorable == []
    assert len(gold) == 1
    assert gold[0].expected_behavior == "answer"
    assert gold[0].gold_node_ids == ["z-attention"]


def test_mixed_set_segregates_correctly():
    doc = _doc([
        {"qid": "a", "text": "q", "expected_primary_citation": "Found",
         "ground_truth": "g"},
        {"qid": "b", "text": "q", "expected_primary_citation": "Missing",
         "ground_truth": "g"},
        {"qid": "c", "text": "q", "expected_primary_citation": "",
         "ground_truth": ""},
    ])
    # Harness resolves every qid: a->found, b->[] (miss), c is a refusal so
    # _resolve_expected yields [] but it did not declare a citation.
    gold, unscorable = _build_gold_queries(doc, {"a": ["z-a"], "b": [], "c": []})
    assert unscorable == ["b"]                       # declared but unresolved
    ids = {g.id for g in gold}
    assert ids == {"a", "c"}                          # a=answer, c=refusal
    by = {g.id: g for g in gold}
    assert by["a"].expected_behavior == "answer"
    assert by["c"].expected_behavior == "refuse"


def _stub_eval_result():
    cs = SimpleNamespace(chunking=80.0, retrieval=70.0, reranking=60.0, synthesis=50.0)
    return SimpleNamespace(
        component_scores=cs, composite=65.0,
        weights={"chunking": 0.1, "retrieval": 0.25, "reranking": 0.2, "synthesis": 0.45},
        weights_hash="deadbeef" * 8, faithfulness_score=70.0,
        answer_relevancy_score=80.0, latency_p50_ms=1.0, latency_p95_ms=2.0,
        eval_divergence=False, per_query=[],
    )


def test_scorecard_surfaces_unscorable_loudly():
    md = _render_scores_md(
        iter_id="iter-XX", eval_result=_stub_eval_result(), n_queries=5,
        n_refusal=1,
        holistic={"critic_verdict_distribution": {}, "query_class_distribution": {}},
        burst=None, dropped_qids=[], unscorable_qids=["q5", "q7"],
    )
    assert "UNRESOLVED / UNSCORABLE" in md
    assert "q5" in md and "q7" in md
    assert "NOT refusals" in md
    # C#6 retrieval-semantics note must also be present.
    assert "post-cascade recall" in md


def test_scorecard_omits_unscorable_section_when_none():
    md = _render_scores_md(
        iter_id="iter-XX", eval_result=_stub_eval_result(), n_queries=5,
        n_refusal=0,
        holistic={"critic_verdict_distribution": {}, "query_class_distribution": {}},
        burst=None, dropped_qids=[], unscorable_qids=[],
    )
    assert "UNRESOLVED / UNSCORABLE" not in md
    # C#6 note is unconditional.
    assert "post-cascade recall" in md
