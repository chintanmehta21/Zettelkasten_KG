"""iter-08 G6: scores.md auto-injects measurement-shift note for iter-08 only."""
from __future__ import annotations

from types import SimpleNamespace

from ops.scripts.score_rag_eval import _render_scores_md


def _stub_eval_result():
    cs = SimpleNamespace(chunking=80.0, retrieval=70.0, reranking=60.0, synthesis=50.0)
    return SimpleNamespace(
        component_scores=cs,
        composite=65.0,
        weights={"chunking": 0.1, "retrieval": 0.25, "reranking": 0.2, "synthesis": 0.45},
        weights_hash="deadbeef" * 8,
        faithfulness_score=70.0,
        answer_relevancy_score=80.0,
        latency_p50_ms=1200.0,
        latency_p95_ms=2400.0,
        eval_divergence=False,
        per_query=[],
    )


def _render(iter_id: str) -> str:
    return _render_scores_md(
        iter_id=iter_id,
        eval_result=_stub_eval_result(),
        n_queries=10,
        n_refusal=0,
        holistic={"critic_verdict_distribution": {}, "query_class_distribution": {}},
        burst=None,
        dropped_qids=None,
    )


def test_iter08_render_includes_measurement_shifts():
    """G6: iter-08 scores.md auto-injects the measurement-shift note."""
    md = _render("iter-08")
    assert "Known measurement shifts vs iter-07" in md
    assert "NDCG normaliser" in md
    assert "Per-query RAGAS" in md
    assert "Chunking score" in md


def test_iter07_render_omits_measurement_shifts():
    """G6: iter-07 scores.md does NOT include the iter-08 shifts note."""
    md = _render("iter-07")
    assert "Known measurement shifts vs iter-07" not in md


def test_iter09_render_omits_measurement_shifts():
    """G6: a future iter-09 also auto-strips the iter-08-specific note."""
    md = _render("iter-09")
    assert "Known measurement shifts vs iter-07" not in md
