"""KG ablation: graph_lift = composite_with_graph - composite_ablated."""
from __future__ import annotations

from website.features.rag_pipeline.evaluation.composite import compute_composite
from website.features.rag_pipeline.evaluation.types import ComponentScores, GraphLift


def compute_graph_lift(
    *,
    with_graph: ComponentScores,
    ablated: ComponentScores,
    weights: dict[str, float],
) -> GraphLift:
    return GraphLift(
        composite=compute_composite(with_graph, weights) - compute_composite(ablated, weights),
        retrieval=with_graph.retrieval - ablated.retrieval,
        reranking=with_graph.reranking - ablated.reranking,
    )
