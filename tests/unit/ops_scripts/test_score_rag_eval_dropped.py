"""iter-08 Phase 7.G: dropped-qid surfacing in score_rag_eval."""
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


def test_render_scores_md_includes_unscored_qids():
    md = _render_scores_md(
        iter_id="iter-XX",
        eval_result=_stub_eval_result(),
        n_queries=8,
        n_refusal=0,
        holistic={"critic_verdict_distribution": {}, "query_class_distribution": {}},
        burst=None,
        dropped_qids=["q3", "q9"],
    )
    assert "Unscored qids" in md
    assert "q3" in md
    assert "q9" in md


def test_render_scores_md_omits_section_when_no_drops():
    md = _render_scores_md(
        iter_id="iter-XX",
        eval_result=_stub_eval_result(),
        n_queries=10,
        n_refusal=0,
        holistic={"critic_verdict_distribution": {}, "query_class_distribution": {}},
        burst=None,
        dropped_qids=[],
    )
    assert "Unscored qids" not in md
