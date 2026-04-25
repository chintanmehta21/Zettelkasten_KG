from unittest.mock import patch, MagicMock
from website.features.rag_pipeline.evaluation.ablation import compute_graph_lift
from website.features.rag_pipeline.evaluation.types import ComponentScores


def test_compute_graph_lift_positive():
    with_graph = ComponentScores(chunking=80, retrieval=85, reranking=80, synthesis=88)
    ablated = ComponentScores(chunking=80, retrieval=75, reranking=70, synthesis=85)
    weights = {"chunking": 0.10, "retrieval": 0.25, "reranking": 0.20, "synthesis": 0.45}
    lift = compute_graph_lift(with_graph=with_graph, ablated=ablated, weights=weights)
    assert lift.retrieval > 0
    assert lift.composite > 0


def test_compute_graph_lift_negative_when_kg_hurts():
    with_graph = ComponentScores(chunking=80, retrieval=70, reranking=70, synthesis=80)
    ablated = ComponentScores(chunking=80, retrieval=80, reranking=75, synthesis=85)
    weights = {"chunking": 0.10, "retrieval": 0.25, "reranking": 0.20, "synthesis": 0.45}
    lift = compute_graph_lift(with_graph=with_graph, ablated=ablated, weights=weights)
    assert lift.retrieval < 0
    assert lift.composite < 0
