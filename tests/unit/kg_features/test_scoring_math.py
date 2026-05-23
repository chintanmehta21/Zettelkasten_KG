"""Scoring math fixes — M1 temporal floor, M3 Jaccard asymmetric, M5 AA continuous."""
import math

from website.features.kg_features.scoring import (
    _jaccard,
    _structural_signal,
    _temporal_signal,
    compute_connection_strength,
)


# M1: minimum-age floor so batch ingest doesn't max temporal to 1.0
def test_temporal_signal_zero_days_caps_below_one():
    """Burst-ingest same-minute pair gets <= ~0.967, not 1.0."""
    sig = _temporal_signal(0.0)
    assert sig < 1.0
    assert sig > 0.95


def test_temporal_signal_30d_stable():
    """Halflife unchanged — 30d still ~0.37."""
    assert 0.35 < _temporal_signal(30.0) < 0.40


def test_temporal_signal_none_returns_zero():
    assert _temporal_signal(None) == 0.0


# M3: Jaccard returns None for asymmetric empty
def test_jaccard_both_empty_returns_zero():
    assert _jaccard([], []) == 0.0


def test_jaccard_one_empty_returns_none():
    """One side has tags, the other doesn't — signal-absent, not signal-zero."""
    assert _jaccard(["python"], []) is None
    assert _jaccard([], ["rust"]) is None


def test_jaccard_disjoint_returns_zero():
    assert _jaccard(["python"], ["rust"]) == 0.0


def test_jaccard_perfect_overlap_returns_one():
    assert _jaccard(["python", "async"], ["async", "python"]) == 1.0


# M3 weight redistribution: tag=None must redistribute 0.25 weight proportionally
def test_compute_strength_redistributes_when_tag_signal_absent():
    """When one side has tags and the other doesn't, the composite score
    must not collapse to (0.25 * 0) lost share. Redistributing the 0.25
    proportionally across emb/struct/temp keeps the absent-tag score
    within ~0.05 of the with-tag score for the same other signals."""
    emb = [0.5] * 8
    score_with_tag = compute_connection_strength(
        "a", "b",
        embeddings={"a": emb, "b": emb},
        tags={"a": ["python"], "b": ["python"]},
        structural={},
        temporal_days=0.0,
    )
    score_tag_absent = compute_connection_strength(
        "a", "b",
        embeddings={"a": emb, "b": emb},
        tags={"a": ["python"], "b": []},  # asymmetric — tag is None
        structural={},
        temporal_days=0.0,
    )
    # Both well above EDGE_CREATION_THRESHOLD (0.50); redistribution keeps
    # the score from collapsing.
    assert score_tag_absent > 0.75
    assert score_with_tag > 0.75
    # The absent-tag score should be CLOSE to (within ~0.06 of) the
    # with-tag score for the same non-tag signals.
    assert abs(score_with_tag - score_tag_absent) < 0.06


# M5: _structural_signal must accept float-valued co-occurrence
def test_structural_signal_accepts_floats():
    """Adamic-Adar combiner produces fractional values (co + 0.5 * aa)."""
    structural = {"a": {"b": 1.5}, "b": {"a": 1.5}}  # fractional
    sig = _structural_signal("a", "b", structural)
    # 1.5 / (1.5 + 2.0) ≈ 0.4286
    assert 0.42 < sig < 0.44


def test_structural_signal_zero_count_returns_zero():
    assert _structural_signal("a", "b", {}) == 0.0
