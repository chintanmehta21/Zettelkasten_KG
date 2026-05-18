"""iter-12 Class K3: confidence-gap bypass tests."""
import pytest
from website.features.rag_pipeline.types import (
    ChunkKind,
    QueryClass,
    RetrievalCandidate,
    SourceType,
)


def _cand(node_id, base_rrf, final_rrf, title_boost=0.0):
    """Build a minimal RetrievalCandidate that the gate accepts."""
    c = RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id=node_id,
        chunk_idx=0,
        name=node_id,
        source_type=SourceType.WEB,
        url="",
        content="",
    )
    c.rrf_score = final_rrf
    c.metadata = {
        "_base_rrf_score": base_rrf,
        "_title_overlap_boost": title_boost,
    }
    return c


def test_top1_top2_gap_helper_basic():
    from website.features.rag_pipeline.retrieval.hybrid import _top1_top2_gap
    cands = [_cand("a", 0.10, 0.90), _cand("b", 0.55, 0.50), _cand("c", 0.45, 0.40)]
    gap = _top1_top2_gap(cands)
    assert gap is not None
    assert abs(gap - (0.90 / 0.50)) < 1e-9


def test_top1_top2_gap_undefined_for_singleton():
    from website.features.rag_pipeline.retrieval.hybrid import _top1_top2_gap
    assert _top1_top2_gap([]) is None
    assert _top1_top2_gap([_cand("only", 0.5, 0.5)]) is None


def test_top1_top2_gap_handles_zero_top2():
    """Tiny epsilon prevents division by zero; gap must be finite and very large."""
    from website.features.rag_pipeline.retrieval.hybrid import _top1_top2_gap
    cands = [_cand("a", 0.5, 0.5), _cand("b", 0.0, 0.0)]
    gap = _top1_top2_gap(cands)
    assert gap is not None and gap > 1e6


def test_clear_winner_skips_magnet_gate():
    """When top1/top2 >= 1.5, the magnet gate must early-out before demote logic."""
    from website.features.rag_pipeline.retrieval.hybrid import _apply_score_rank_demote
    cands = [
        _cand("clear-winner", 0.10, 0.90),
        _cand("a", 0.55, 0.50),
        _cand("b", 0.50, 0.45),
        _cand("c", 0.45, 0.40),
    ]
    pre = [c.rrf_score for c in cands]
    _apply_score_rank_demote(cands, query_class=QueryClass.THEMATIC, query_text="topic")
    post = [c.rrf_score for c in cands]
    # gap = 0.90 / 0.50 = 1.8 >= 1.5 -> bypass; nothing demoted
    assert pre == post


def test_close_competition_gate_can_fire():
    """Gap < 1.5 -> normal magnet-gate logic fires and demotes the magnet."""
    from website.features.rag_pipeline.retrieval.hybrid import _apply_score_rank_demote
    cands = [
        _cand("magnet", 0.10, 0.65),
        _cand("a", 0.55, 0.60),
        _cand("b", 0.50, 0.55),
        _cand("c", 0.45, 0.50),
    ]
    _apply_score_rank_demote(cands, query_class=QueryClass.THEMATIC, query_text="topic")
    # gap = 0.65 / 0.60 ~ 1.083 < 1.5; gate fires; magnet demoted below at least one
    sorted_by_score = sorted(cands, key=lambda c: c.rrf_score, reverse=True)
    assert sorted_by_score[0].node_id != "magnet"


def test_should_skip_retry_uses_confidence_gap():
    """_retry_gap_bypass_threshold() returns the 1.5 default."""
    from website.features.rag_pipeline.orchestrator import _retry_gap_bypass_threshold
    assert _retry_gap_bypass_threshold() == 1.5


# ---------------------------------------------------------------------------
# Phase D D2 — _top1_top2_gap score-key parameterization
# ---------------------------------------------------------------------------


def _scored(node_id, rrf_score, final_score, rerank_score=None):
    c = RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id=node_id,
        chunk_idx=0,
        name=node_id,
        source_type=SourceType.WEB,
        url="",
        content="",
    )
    c.rrf_score = rrf_score
    c.final_score = final_score
    c.rerank_score = rerank_score
    return c


def test_top1_top2_gap_default_key_is_rrf_score_byte_identical():
    """Default call path unchanged: gap computed over rrf_score."""
    from website.features.rag_pipeline.retrieval.hybrid import _top1_top2_gap
    cands = [
        _scored("a", rrf_score=0.90, final_score=0.10),
        _scored("b", rrf_score=0.30, final_score=0.95),
    ]
    # Default reads rrf_score -> 0.90 / 0.30 == 3.0 (NOT the final_score order).
    assert _top1_top2_gap(cands) == pytest.approx(0.90 / 0.30)


def test_top1_top2_gap_final_score_key_reorders_top2():
    """score_key='final_score' ranks by the post-rerank field."""
    from website.features.rag_pipeline.retrieval.hybrid import _top1_top2_gap
    cands = [
        _scored("a", rrf_score=0.90, final_score=0.51),
        _scored("b", rrf_score=0.30, final_score=0.50),
    ]
    # Over final_score: 0.51 / 0.50 ~= 1.02 (close competition, NOT a winner).
    gap = _top1_top2_gap(cands, score_key="final_score")
    assert gap == pytest.approx(0.51 / 0.50)


def test_d2_rerank_reorder_does_not_wrongly_skip_retry():
    """Regression: post-rerank top-2 reorder must NOT trip the clear-winner
    retry skip.

    The raw pre-fusion rrf_score order is a runaway winner (0.95 vs 0.10 ->
    gap 9.5 >= 1.5) but the cross-encoder reordered the meaningful ranking so
    final_score is a near-tie (0.50 vs 0.49 -> gap ~1.02 < 1.5). Pre-fix the
    skip gated on rrf_score and WRONGLY short-circuited the retry; post-fix it
    gates on final_score and lets the retry proceed.
    """
    from website.features.rag_pipeline.orchestrator import (
        QueryMetadata,
        _should_skip_retry,
    )
    used = [
        _scored("a", rrf_score=0.95, final_score=0.49, rerank_score=0.49),
        _scored("b", rrf_score=0.10, final_score=0.50, rerank_score=0.50),
    ]
    skip, reason = _should_skip_retry(
        answer_text="some unsupported answer text without refusal phrasing",
        used_candidates=used,
        query_class=QueryClass.THEMATIC,
        metadata=QueryMetadata(),
        first_verdict="unsupported",
    )
    assert skip is False
    assert reason != "skip_clear_winner"


def test_d2_genuine_final_score_winner_still_skips():
    """Counterpart: a genuine post-rerank clear winner still skips retry."""
    from website.features.rag_pipeline.orchestrator import (
        QueryMetadata,
        _should_skip_retry,
    )
    used = [
        _scored("a", rrf_score=0.30, final_score=0.95, rerank_score=0.95),
        _scored("b", rrf_score=0.90, final_score=0.10, rerank_score=0.10),
    ]
    skip, reason = _should_skip_retry(
        answer_text="some unsupported answer text without refusal phrasing",
        used_candidates=used,
        query_class=QueryClass.THEMATIC,
        metadata=QueryMetadata(),
        first_verdict="unsupported",
    )
    # final_score gap = 0.95 / 0.10 = 9.5 >= 1.5 -> clear-winner skip fires.
    assert skip is True
    assert reason == "skip_clear_winner"
