"""iter-10 Item 3: chunk_count_quartile tie-breaker.

When two candidates land on identical rrf_score, the class-conditional bias
picks the better one without changing behaviour for non-tied cases.
"""
from website.features.rag_pipeline.retrieval.hybrid import _tiebreak_key
from website.features.rag_pipeline.types import QueryClass


def test_higher_quartile_wins_when_rrf_tied_for_lookup():
    a = _tiebreak_key(0.5, 12, {"a": 12, "b": 2}, QueryClass.LOOKUP)
    b = _tiebreak_key(0.5,  2, {"a": 12, "b": 2}, QueryClass.LOOKUP)
    assert a > b


def test_thematic_inverts_quartile_preference():
    a = _tiebreak_key(0.5, 12, {"a": 12, "b": 2}, QueryClass.THEMATIC)
    b = _tiebreak_key(0.5,  2, {"a": 12, "b": 2}, QueryClass.THEMATIC)
    assert b > a


def test_tiebreak_does_not_change_order_when_rrf_differs():
    a = _tiebreak_key(0.6,  2, {"a": 2, "b": 12}, QueryClass.LOOKUP)
    b = _tiebreak_key(0.5, 12, {"a": 2, "b": 12}, QueryClass.LOOKUP)
    assert a > b


def test_step_back_inverts_like_thematic():
    a = _tiebreak_key(0.5, 12, {"a": 12, "b": 2}, QueryClass.STEP_BACK)
    b = _tiebreak_key(0.5,  2, {"a": 12, "b": 2}, QueryClass.STEP_BACK)
    assert b > a


def test_multi_hop_inverts_like_thematic():
    a = _tiebreak_key(0.5, 12, {"a": 12, "b": 2}, QueryClass.MULTI_HOP)
    b = _tiebreak_key(0.5,  2, {"a": 12, "b": 2}, QueryClass.MULTI_HOP)
    assert b > a


def test_vague_prefers_higher_quartile_like_lookup():
    a = _tiebreak_key(0.5, 12, {"a": 12, "b": 2}, QueryClass.VAGUE)
    b = _tiebreak_key(0.5,  2, {"a": 12, "b": 2}, QueryClass.VAGUE)
    assert a > b


def test_no_chunk_counts_returns_neutral_bias():
    a = _tiebreak_key(0.5, 0, {}, QueryClass.LOOKUP)
    assert a == (0.5, 0.0)


def test_bias_is_subfloor_so_real_score_diffs_dominate():
    """A 0.0001-scale bias must NEVER overcome a real rrf gap."""
    a = _tiebreak_key(0.51,  2, {"a": 2, "b": 12}, QueryClass.LOOKUP)
    b = _tiebreak_key(0.50, 12, {"a": 2, "b": 12}, QueryClass.LOOKUP)
    assert a > b
