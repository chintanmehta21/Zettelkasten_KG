from website.features.rag_pipeline.rerank.cascade import _resolve_fusion_weights
from website.features.rag_pipeline.types import QueryClass


def test_resolve_fusion_weights_zero_override():
    rerank, graph, rrf = _resolve_fusion_weights(QueryClass.LOOKUP, graph_weight_override=0.0)
    assert graph == 0.0
    assert abs(rerank + rrf - 1.0) < 1e-6


def test_resolve_fusion_weights_no_override_keeps_class_weights():
    rerank, graph, rrf = _resolve_fusion_weights(QueryClass.LOOKUP, graph_weight_override=None)
    # E4 F3 (docs/research/e4_component_fix_proposal.md Finding 2): LOOKUP
    # rebalanced (0.70,0.15,0.15) -> (0.80,0.10,0.10) to stop graph+rrf
    # outvoting a correctly-top-ranked gold. This pins the CONSTANT (not
    # behavior); updated to the new approved value.
    assert (rerank, graph, rrf) == (0.80, 0.10, 0.10)
