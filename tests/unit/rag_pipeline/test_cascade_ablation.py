from website.features.rag_pipeline.rerank.cascade import _resolve_fusion_weights
from website.features.rag_pipeline.types import QueryClass


def test_resolve_fusion_weights_zero_override():
    rerank, graph, rrf = _resolve_fusion_weights(QueryClass.LOOKUP, graph_weight_override=0.0)
    assert graph == 0.0
    assert abs(rerank + rrf - 1.0) < 1e-6


def test_resolve_fusion_weights_no_override_keeps_class_weights():
    rerank, graph, rrf = _resolve_fusion_weights(QueryClass.LOOKUP, graph_weight_override=None)
    # LOOKUP class weights are (0.70, 0.15, 0.15)
    assert (rerank, graph, rrf) == (0.70, 0.15, 0.15)
