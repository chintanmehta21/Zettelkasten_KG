"""Determinism gate + improvement delta writer."""
from __future__ import annotations

import json
from pathlib import Path


class DeterminismError(Exception):
    pass


def determinism_gate(
    *, prev_composite: float, current_composite: float, tolerance: float = 3.0
) -> None:
    drift = abs(current_composite - prev_composite)
    if drift > tolerance:
        raise DeterminismError(
            f"Determinism gate: composite drifted {drift:.2f}pt vs prior iter's eval re-run "
            f"(tolerance {tolerance}pt). Halt and investigate evaluator changes."
        )


def _band(absolute_delta: float) -> str:
    a = abs(absolute_delta)
    if a <= 5.0:
        return "AGREEMENT"
    if a <= 10.0:
        return "MINOR_DISAGREEMENT"
    return "MAJOR_DISAGREEMENT"


def write_improvement_delta(
    *,
    iter_dir: Path,
    prev_composite: float,
    curr_composite: float,
    prev_components: dict,
    curr_components: dict,
    graph_lift_prev: dict,
    graph_lift_curr: dict,
    review_estimate: float | None,
) -> dict:
    out = {
        "composite": {
            "previous": prev_composite,
            "current": curr_composite,
            "absolute": curr_composite - prev_composite,
            "relative_pct": (
                (curr_composite - prev_composite) / prev_composite * 100.0
                if prev_composite
                else 0.0
            ),
        },
        "components": {
            k: {
                "previous": prev_components.get(k, 0),
                "current": curr_components.get(k, 0),
                "absolute": curr_components.get(k, 0) - prev_components.get(k, 0),
            }
            for k in ("chunking", "retrieval", "reranking", "synthesis")
        },
        "graph_lift": {
            "previous": graph_lift_prev,
            "current": graph_lift_curr,
            "delta": {
                k: graph_lift_curr.get(k, 0) - graph_lift_prev.get(k, 0)
                for k in ("composite", "retrieval", "reranking")
            },
        },
        "review_estimate": review_estimate,
        "review_divergence_band": (
            _band(curr_composite - review_estimate)
            if review_estimate is not None
            else None
        ),
    }
    (iter_dir / "improvement_delta.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )
    return out
