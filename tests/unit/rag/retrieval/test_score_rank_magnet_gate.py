"""iter-10 P3: score-rank-correlation magnet gate.

A node is a magnet if its top-1 ranking is disproportionate to its retrieval
percentile. We compute the percentile rank of each candidate's BASE rrf
(BEFORE all class boosts) and demote any candidate whose post-boost rank is
> 1 quartile higher than its base percentile in THEMATIC/STEP_BACK class.
"""
from website.features.rag_pipeline.retrieval.hybrid import _apply_score_rank_demote
from website.features.rag_pipeline.types import (
    ChunkKind,
    QueryClass,
    RetrievalCandidate,
    SourceType,
)


def _cand(node_id: str, base_rrf: float, final_rrf: float) -> RetrievalCandidate:
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
    c.metadata = {"_base_rrf_score": base_rrf}
    return c


def test_thematic_demotes_magnet_with_low_base_rrf():
    """Magnet narrowly led on final rrf; the 0.85 demote factor must reverse
    the order so a real thematic candidate wins top-1."""
    cands = [
        _cand("magnet-2chunk", 0.10, 0.65),  # narrow lead from a +0.55 boost
        _cand("real-thematic-a", 0.55, 0.60),
        _cand("real-thematic-b", 0.50, 0.55),
        _cand("real-thematic-c", 0.45, 0.50),
    ]
    _apply_score_rank_demote(cands, query_class=QueryClass.THEMATIC, query_text="general topic")
    cands_sorted = sorted(cands, key=lambda c: c.rrf_score, reverse=True)
    assert cands_sorted[0].node_id != "magnet-2chunk"


def test_lookup_does_not_demote_magnet():
    """LOOKUP must NEVER apply the gate; proper-noun lookups legitimately
    boost a single high-relevance node to top-1."""
    cands = [
        _cand("magnet-2chunk", 0.10, 0.65),
        _cand("other-a", 0.55, 0.60),
        _cand("other-b", 0.50, 0.55),
        _cand("other-c", 0.45, 0.50),
    ]
    _apply_score_rank_demote(cands, query_class=QueryClass.LOOKUP, query_text="proper noun query")
    cands_sorted = sorted(cands, key=lambda c: c.rrf_score, reverse=True)
    assert cands_sorted[0].node_id == "magnet-2chunk"


def test_thematic_no_demote_when_no_disproportion():
    cands = [
        _cand("a", 0.80, 0.85),
        _cand("b", 0.70, 0.75),
        _cand("c", 0.60, 0.65),
        _cand("d", 0.50, 0.55),
    ]
    _apply_score_rank_demote(cands, query_class=QueryClass.THEMATIC, query_text="topic")
    cands_sorted = sorted(cands, key=lambda c: c.rrf_score, reverse=True)
    assert cands_sorted[0].node_id == "a"


def test_step_back_class_also_gated():
    cands = [
        _cand("magnet", 0.10, 0.65),
        _cand("real-a", 0.55, 0.60),
        _cand("real-b", 0.50, 0.55),
        _cand("real-c", 0.45, 0.50),
    ]
    _apply_score_rank_demote(cands, query_class=QueryClass.STEP_BACK, query_text="step back")
    cands_sorted = sorted(cands, key=lambda c: c.rrf_score, reverse=True)
    assert cands_sorted[0].node_id != "magnet"


def test_vague_class_NOT_gated():
    """VAGUE has its own vague_low_entity gate; do not double-gate."""
    cands = [_cand("magnet", 0.10, 0.85)]
    _apply_score_rank_demote(cands, query_class=QueryClass.VAGUE, query_text="vague")
    assert cands[0].rrf_score == 0.85


def test_multi_hop_NOT_gated():
    cands = [
        _cand("magnet", 0.10, 0.65),
        _cand("a", 0.55, 0.60),
        _cand("b", 0.50, 0.55),
        _cand("c", 0.45, 0.50),
    ]
    _apply_score_rank_demote(cands, query_class=QueryClass.MULTI_HOP, query_text="step back")
    cands_sorted = sorted(cands, key=lambda c: c.rrf_score, reverse=True)
    assert cands_sorted[0].node_id == "magnet"


def test_title_overlap_secondary_demote():
    """Even within THEMATIC, a candidate whose top-1 win came from
    title-overlap boost (>=0.10) gets a multiplicative demote."""
    cands = [
        _cand("title-magnet", 0.30, 0.80),
        _cand("a", 0.32, 0.34),
        _cand("b", 0.31, 0.33),
        _cand("c", 0.30, 0.32),
    ]
    cands[0].metadata["_title_overlap_boost"] = 0.15
    before = cands[0].rrf_score
    _apply_score_rank_demote(cands, query_class=QueryClass.THEMATIC, query_text="topic")
    assert cands[0].rrf_score < before


def test_pool_too_small_skips_gate():
    """Pools <4 candidates have unstable rank percentile; skip gate."""
    cands = [_cand("magnet", 0.10, 0.85), _cand("other", 0.50, 0.55)]
    _apply_score_rank_demote(cands, query_class=QueryClass.THEMATIC, query_text="topic")
    assert cands[0].rrf_score == 0.85  # unchanged
