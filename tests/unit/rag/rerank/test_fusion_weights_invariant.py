"""_FUSION_WEIGHTS invariant + factoid-rebalance guard (E4 Fix F3).

Pins the approved per-class (rerank, graph, rrf) tuples, the sum==1.0
invariant for EVERY class, and the byte-identity of MULTI_HOP / STEP_BACK
(Phase-D graph-heavy by design — unchanged by F3). Also asserts the Phase-D
graph-override redistribution preserves the sum==1 invariant on the rebalanced
factoid tuples so _resolve_fusion_weights still composes.
"""
from __future__ import annotations

import pytest

from website.features.rag_pipeline.rerank.cascade import (
    _DEFAULT_FUSION_WEIGHTS,
    _FUSION_WEIGHTS,
    _resolve_fusion_weights,
)
from website.features.rag_pipeline.types import QueryClass


# E4 F3 approved factoid-class rebalance (proposal docs/research/
# e4_component_fix_proposal.md Finding 2). MULTI_HOP / STEP_BACK UNCHANGED.
_APPROVED = {
    QueryClass.LOOKUP: (0.80, 0.10, 0.10),
    QueryClass.VAGUE: (0.65, 0.20, 0.15),
    QueryClass.THEMATIC: (0.62, 0.25, 0.13),
    QueryClass.MULTI_HOP: (0.40, 0.45, 0.15),
    QueryClass.STEP_BACK: (0.45, 0.40, 0.15),
}


@pytest.mark.parametrize("qc,expected", list(_APPROVED.items()))
def test_fusion_weights_match_approved_tuples(qc, expected):
    assert _FUSION_WEIGHTS[qc] == expected


@pytest.mark.parametrize("qc", list(QueryClass))
def test_every_class_tuple_sums_to_exactly_one(qc):
    w = _FUSION_WEIGHTS.get(qc, _DEFAULT_FUSION_WEIGHTS)
    assert sum(w) == pytest.approx(1.0, abs=1e-9)


def test_default_fusion_weights_unchanged():
    # DEFAULT is NOT a factoid class and is not in scope for F3.
    assert _DEFAULT_FUSION_WEIGHTS == (0.60, 0.25, 0.15)
    assert sum(_DEFAULT_FUSION_WEIGHTS) == pytest.approx(1.0)


def test_multi_hop_and_step_back_byte_identical():
    # Phase-D graph-heavy classes must stay verbatim (no F3 touch).
    assert _FUSION_WEIGHTS[QueryClass.MULTI_HOP] == (0.40, 0.45, 0.15)
    assert _FUSION_WEIGHTS[QueryClass.STEP_BACK] == (0.45, 0.40, 0.15)


@pytest.mark.parametrize("qc", list(_APPROVED))
def test_graph_override_redistribution_still_sums_to_one(qc):
    # Phase-D KG-ablation path: override graph weight, remaining mass
    # redistributed across rerank/rrf preserving ratio -> Σ == 1.0.
    rerank, graph, rrf = _resolve_fusion_weights(qc, graph_weight_override=0.0)
    assert graph == 0.0
    assert rerank + rrf == pytest.approx(1.0, abs=1e-9)
    rerank2, graph2, rrf2 = _resolve_fusion_weights(qc, graph_weight_override=0.30)
    assert graph2 == 0.30
    assert rerank2 + graph2 + rrf2 == pytest.approx(1.0, abs=1e-9)
