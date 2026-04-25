"""Weighted composite + delta arithmetic + hash lock for rag_eval."""
from __future__ import annotations

import hashlib
from pathlib import Path

from website.features.rag_pipeline.evaluation.types import ComponentScores


class WeightsLockError(Exception):
    """Raised when composite_weights.yaml hash diverges from the locked iter-01 hash."""


def compute_composite(scores: ComponentScores, weights: dict[str, float]) -> float:
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"weights must sum to 1.0; got {total}")
    return (
        weights["chunking"] * scores.chunking
        + weights["retrieval"] * scores.retrieval
        + weights["reranking"] * scores.reranking
        + weights["synthesis"] * scores.synthesis
    )


def hash_weights_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_weights_unchanged(path: Path, locked_hash: str) -> None:
    current = hash_weights_file(path)
    if current != locked_hash:
        raise WeightsLockError(
            f"composite_weights.yaml hash drifted: locked={locked_hash[:8]} current={current[:8]}. "
            "Mid-loop weight changes are blocked. Revert or start a new per-source loop."
        )


def composite_delta(prev: float, curr: float) -> dict[str, float]:
    return {
        "absolute": curr - prev,
        "relative_pct": ((curr - prev) / prev * 100.0) if prev else 0.0,
    }
