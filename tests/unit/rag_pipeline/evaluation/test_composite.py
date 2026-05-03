import math

import pytest
from pathlib import Path

from website.features.rag_pipeline.evaluation.composite import (
    compute_composite,
    hash_weights_file,
    verify_weights_unchanged,
    WeightsLockError,
)
from website.features.rag_pipeline.evaluation.types import ComponentScores


def test_compute_composite_default_weights():
    scores = ComponentScores(chunking=80.0, retrieval=60.0, reranking=70.0, synthesis=90.0)
    weights = {"chunking": 0.10, "retrieval": 0.25, "reranking": 0.20, "synthesis": 0.45}
    composite = compute_composite(scores, weights)
    expected = 0.10*80 + 0.25*60 + 0.20*70 + 0.45*90
    assert abs(composite - expected) < 1e-6


def test_compute_composite_rejects_non_summing_weights():
    scores = ComponentScores(chunking=50, retrieval=50, reranking=50, synthesis=50)
    with pytest.raises(ValueError, match="weights"):
        compute_composite(scores, {"chunking": 0.5, "retrieval": 0.5, "reranking": 0.5, "synthesis": 0.5})


def test_hash_weights_file_stable(tmp_path):
    path = tmp_path / "weights.yaml"
    path.write_text("chunking: 0.10\nretrieval: 0.25\nreranking: 0.20\nsynthesis: 0.45\n", encoding="utf-8")
    h1 = hash_weights_file(path)
    h2 = hash_weights_file(path)
    assert h1 == h2
    path.write_text("chunking: 0.20\nretrieval: 0.25\nreranking: 0.10\nsynthesis: 0.45\n", encoding="utf-8")
    assert hash_weights_file(path) != h1


def test_verify_weights_unchanged_blocks_drift(tmp_path):
    path = tmp_path / "weights.yaml"
    path.write_text("chunking: 0.10\nretrieval: 0.25\nreranking: 0.20\nsynthesis: 0.45\n", encoding="utf-8")
    locked = hash_weights_file(path)
    verify_weights_unchanged(path, locked)  # no-op on match
    path.write_text("chunking: 0.30\nretrieval: 0.20\nreranking: 0.10\nsynthesis: 0.40\n", encoding="utf-8")
    with pytest.raises(WeightsLockError):
        verify_weights_unchanged(path, locked)


def test_composite_raises_on_nan_component():
    """iter-08 Phase 7.F: NaN component must raise (pydantic-enforced at construction)."""
    weights = {"chunking": 0.10, "retrieval": 0.25, "reranking": 0.20, "synthesis": 0.45}
    # Pydantic rejects NaN at construction via ge/le constraints.
    with pytest.raises(Exception):
        scores = ComponentScores(
            chunking=math.nan, retrieval=50.0, reranking=50.0, synthesis=50.0
        )
        compute_composite(scores, weights)
    # Defence-in-depth: bypass pydantic via construct() and confirm
    # compute_composite still raises on non-finite components.
    bypass = ComponentScores.model_construct(
        chunking=math.nan, retrieval=50.0, reranking=50.0, synthesis=50.0
    )
    with pytest.raises(ValueError, match="non-finite"):
        compute_composite(bypass, weights)


def test_composite_raises_on_none_component():
    """iter-08 Phase 7.F: None component must raise (pydantic-enforced at construction)."""
    weights = {"chunking": 0.10, "retrieval": 0.25, "reranking": 0.20, "synthesis": 0.45}
    with pytest.raises(Exception):
        scores = ComponentScores(
            chunking=None, retrieval=50.0, reranking=50.0, synthesis=50.0
        )
        compute_composite(scores, weights)
    # Defence-in-depth: bypass pydantic and confirm explicit guard catches None.
    bypass = ComponentScores.model_construct(
        chunking=None, retrieval=50.0, reranking=50.0, synthesis=50.0
    )
    with pytest.raises(ValueError, match="non-finite"):
        compute_composite(bypass, weights)
