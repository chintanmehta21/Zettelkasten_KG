"""WAVE-C 1c-A.2 — Unit tests for multi-signal connection strength scorer.

Locked decisions covered:
- D-KG-1 weights: embedding=0.55 + tag=0.25 + structural=0.15 + temporal=0.05
- D-KG-2 edge-creation threshold: ≥ 0.50 (B3: re-tuned from 0.55 after the
  raw-cosine clamp replaced the (cos+1)/2 compression)
- Per-node neighborhood percentile rank (NOT global percentile)
- Pure function: no DB / no network / no global state
"""
from __future__ import annotations

import math

import pytest

from website.features.kg_features.scoring import (
    WEIGHTS,
    EDGE_CREATION_THRESHOLD,
    EDGE_RENDER_THRESHOLD,
    compute_connection_strength,
)


# ── Invariants ──────────────────────────────────────────────────────────


def test_weights_sum_to_one() -> None:
    """D-KG-1 invariant: all four signal weights must sum to exactly 1.0."""
    assert math.isclose(sum(WEIGHTS.values()), 1.0, abs_tol=1e-9)


def test_weights_match_locked_decision() -> None:
    """Pin the exact D-KG-1 weights so future edits trip CI.

    Phase 3-α (#operator-approved 2026-05-23): rebalanced from
    (0.55, 0.25, 0.15, 0.05) → (0.65, 0.20, 0.10, 0.05) to keep dense
    semantic pairs above the 0.50 creation threshold without a shared tag.
    """
    assert WEIGHTS == {
        "embedding": 0.65,
        "tag": 0.20,
        "structural": 0.10,
        "temporal": 0.05,
    }


def test_thresholds_match_locked_decisions() -> None:
    """D-KG-2 (edge create ≥ 0.50, B3-retuned) and D-KG-3 (edge render ≥ 0.7)."""
    assert EDGE_CREATION_THRESHOLD == 0.50
    assert EDGE_RENDER_THRESHOLD == 0.7


# ── Determinism ─────────────────────────────────────────────────────────


def test_score_is_deterministic() -> None:
    """Same inputs → same output, every time. Pure function invariant."""
    a = "node-a"
    b = "node-b"
    s1 = compute_connection_strength(
        a,
        b,
        embeddings={"node-a": [0.1, 0.2, 0.3], "node-b": [0.1, 0.2, 0.3]},
        tags={"node-a": ["python"], "node-b": ["python", "fastapi"]},
        structural={"node-a": {"node-b": 1}, "node-b": {"node-a": 1}},
        temporal_days=3.0,
    )
    s2 = compute_connection_strength(
        a,
        b,
        embeddings={"node-a": [0.1, 0.2, 0.3], "node-b": [0.1, 0.2, 0.3]},
        tags={"node-a": ["python"], "node-b": ["python", "fastapi"]},
        structural={"node-a": {"node-b": 1}, "node-b": {"node-a": 1}},
        temporal_days=3.0,
    )
    assert s1 == s2


def test_score_in_unit_interval() -> None:
    """Output must always be in [0, 1] regardless of input magnitudes."""
    score = compute_connection_strength(
        "a",
        "b",
        embeddings={"a": [1.0, 0.0], "b": [1.0, 0.0]},
        tags={"a": ["x"], "b": ["x"]},
        structural={"a": {"b": 100}, "b": {"a": 100}},
        temporal_days=0.0,
    )
    assert 0.0 <= score <= 1.0


# ── Graceful degradation ────────────────────────────────────────────────


def test_empty_tags_does_not_raise() -> None:
    """No tags on either side → tag signal contributes 0 (Jaccard = 0/0 → 0)."""
    score = compute_connection_strength(
        "a",
        "b",
        embeddings={"a": [1.0, 0.0], "b": [0.0, 1.0]},
        tags={"a": [], "b": []},
        structural={"a": {}, "b": {}},
        temporal_days=365.0,
    )
    # Orthogonal embeddings + no tags + no co-occurrence + far apart → tiny
    assert score >= 0.0
    assert score < 0.3


def test_missing_node_in_embeddings_returns_zero_signal() -> None:
    """Missing embedding entry → embedding signal degrades to 0, not crash."""
    score = compute_connection_strength(
        "a",
        "b",
        embeddings={},
        tags={"a": ["python"], "b": ["python"]},
        structural={},
        temporal_days=0.0,
    )
    # Phase 3-α: tag weight is 0.20 (was 0.25); temporal=exp(-1/30)≈0.967
    # via M1 floor; embedding signal absent. Composite ≈ 0.20 + 0.05*0.967 ≈ 0.25.
    assert 0.20 <= score <= 0.30


def test_missing_embedding_dim_mismatch_returns_zero_signal() -> None:
    """Embedding length mismatch → safe-zero, not numpy broadcasting error."""
    score = compute_connection_strength(
        "a",
        "b",
        embeddings={"a": [1.0, 0.0], "b": [1.0, 0.0, 0.0]},  # mismatched length
        tags={"a": ["x"], "b": ["x"]},
        structural={"a": {}, "b": {}},
        temporal_days=0.0,
    )
    assert 0.0 <= score <= 1.0


# ── Component contributions ────────────────────────────────────────────


def test_identical_embeddings_max_embedding_signal() -> None:
    """Cosine(v, v) = 1.0 → embedding signal contributes 0.65 (Phase 3-α weights),
    AND triggers the cos>=0.80 fast-path so the composite is floored at 0.85."""
    score = compute_connection_strength(
        "a",
        "b",
        embeddings={"a": [0.6, 0.8], "b": [0.6, 0.8]},
        tags={"a": [], "b": []},
        structural={"a": {}, "b": {}},
        temporal_days=365.0,
    )
    # Phase 3-α: composite would be 0.65 + ε, fast-path floors at 0.85.
    assert 0.84 <= score <= 0.86


def test_identical_tag_set_max_tag_signal() -> None:
    """Jaccard({a,b,c}, {a,b,c}) = 1.0 → tag signal contributes 0.20 (Phase 3-α)."""
    score = compute_connection_strength(
        "n1",
        "n2",
        embeddings={},
        tags={"n1": ["a", "b", "c"], "n2": ["a", "b", "c"]},
        structural={},
        temporal_days=365.0,
    )
    # Phase 3-α: only tag fires (~0.20) + small temporal residual (~ε).
    assert 0.18 <= score <= 0.22


def test_temporal_decay_recent_higher() -> None:
    """Same-day temporal signal ≥ year-old temporal signal."""
    same_day = compute_connection_strength(
        "a",
        "b",
        embeddings={},
        tags={},
        structural={},
        temporal_days=0.0,
    )
    year_old = compute_connection_strength(
        "a",
        "b",
        embeddings={},
        tags={},
        structural={},
        temporal_days=365.0,
    )
    assert same_day >= year_old


# ── Edge-creation gate ────────────────────────────────────────────────


def test_below_creation_threshold_predicate_excludes() -> None:
    """Score < 0.50 must NOT qualify for edge creation."""
    assert 0.49 < EDGE_CREATION_THRESHOLD
    assert not (0.49 >= EDGE_CREATION_THRESHOLD)


def test_at_creation_threshold_predicate_includes() -> None:
    """Score == 0.50 IS the creation cutoff (≥, not >)."""
    assert 0.50 >= EDGE_CREATION_THRESHOLD


def test_render_threshold_strict_subset_of_creation() -> None:
    """Render threshold (0.7) > creation threshold (0.50) by construction."""
    assert EDGE_RENDER_THRESHOLD > EDGE_CREATION_THRESHOLD


# ── B3: raw-cosine clamp kernel (no (cos+1)/2 affine rescale) ──────────


def test_b3_cosine_kernel_clamps_not_rescales() -> None:
    """B3 regression: ``_cosine_similarity`` must clamp to ``max(0, cos)``,
    NOT affine-rescale via ``(cos+1)/2``. The old rescale floored unrelated
    pairs at 0.5 and compressed related pairs into 0.55-0.70, degenerating
    the composite and collapsing edge tiers (defect B3)."""
    from website.features.kg_features.scoring import _cosine_similarity

    # Identical → 1.0 (both kernels agree here).
    assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    # Orthogonal → 0.0 under clamp (old rescale wrongly gave 0.5).
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    # Antipodal → 0.0 under clamp (old rescale wrongly gave 0.0 too, but via
    # a different path; pin it explicitly so a rescale regression is caught).
    assert _cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(0.0)
    # A genuinely related pair keeps its TRUE similarity (~0.97), not the
    # compressed ~0.98→rescaled band — spread is preserved for tiering.
    sim = _cosine_similarity([1.0, 0.25], [1.0, 0.05])
    assert sim > 0.95
    # Pathological inputs still collapse to 0.0 silently.
    assert _cosine_similarity([], [1.0]) == 0.0
    assert _cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_b3_orthogonal_embeddings_contribute_zero_not_half() -> None:
    """End-to-end: orthogonal embeddings must add 0 to the composite (was
    0.55 * 0.5 = 0.275 under the old rescale — a phantom edge-strength
    floor that created spurious edges between unrelated nodes)."""
    score = compute_connection_strength(
        "a",
        "b",
        embeddings={"a": [1.0, 0.0], "b": [0.0, 1.0]},
        tags={"a": [], "b": []},
        structural={"a": {}, "b": {}},
        temporal_days=365.0,
    )
    # Only the (near-zero) temporal term remains; the embedding term is 0.
    assert score < 0.05
