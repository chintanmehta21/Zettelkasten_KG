import json
from pathlib import Path
import pytest

from ops.scripts.lib.rag_eval_diff import (
    determinism_gate,
    DeterminismError,
    write_improvement_delta,
)


def test_determinism_gate_passes_within_3pt():
    determinism_gate(prev_composite=70.0, current_composite=72.5, tolerance=3.0)


def test_determinism_gate_blocks_drift():
    with pytest.raises(DeterminismError):
        determinism_gate(prev_composite=70.0, current_composite=75.0, tolerance=3.0)


def test_write_improvement_delta(tmp_path):
    iter_dir = tmp_path / "iter-02"
    iter_dir.mkdir()
    delta = write_improvement_delta(
        iter_dir=iter_dir,
        prev_composite=70.0,
        curr_composite=78.0,
        prev_components={"chunking": 75, "retrieval": 70, "reranking": 65, "synthesis": 80},
        curr_components={"chunking": 80, "retrieval": 80, "reranking": 78, "synthesis": 85},
        graph_lift_prev={"composite": 0.0, "retrieval": 0.0, "reranking": 0.0},
        graph_lift_curr={"composite": 5.0, "retrieval": 7.0, "reranking": 4.0},
        review_estimate=76.0,
    )
    written = json.loads((iter_dir / "improvement_delta.json").read_text(encoding="utf-8"))
    assert written["composite"]["absolute"] == 8.0
    assert written["review_divergence_band"] == "AGREEMENT"
