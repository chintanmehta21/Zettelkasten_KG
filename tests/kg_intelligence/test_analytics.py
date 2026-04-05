"""M3 — Graph Analytics (NetworkX) tests.

Covers:
- Triangle graph: all pagerank values positive, 1 community, 1 component.
- Empty graph: empty metrics, num_communities=0, num_components=0.
- Disconnected graph (4 nodes, 2 pairs): num_components=2.
"""

from __future__ import annotations

from website.features.kg_features.analytics import (
    GraphMetrics,
    compute_graph_metrics,
)


# ── Test 1 ───────────────────────────────────────────────────────────────────

def test_compute_metrics_on_triangle_graph(triangle_graph):
    """3-node triangle → all nodes have pagerank > 0, 1 component, at least
    1 community, betweenness + closeness populated.
    """
    metrics = compute_graph_metrics(triangle_graph)

    assert isinstance(metrics, GraphMetrics)
    assert set(metrics.pagerank.keys()) == {"a", "b", "c"}
    for node_id, score in metrics.pagerank.items():
        assert score > 0, f"pagerank for {node_id} should be positive"

    assert metrics.num_components == 1
    assert metrics.num_communities >= 1
    assert set(metrics.betweenness.keys()) == {"a", "b", "c"}
    assert set(metrics.closeness.keys()) == {"a", "b", "c"}
    assert metrics.computed_at  # ISO timestamp present


# ── Test 2 ───────────────────────────────────────────────────────────────────

def test_compute_metrics_on_empty_graph(empty_graph):
    """Empty KGGraph → zeroed metrics, no crash."""
    metrics = compute_graph_metrics(empty_graph)

    assert isinstance(metrics, GraphMetrics)
    assert metrics.pagerank == {}
    assert metrics.communities == {}
    assert metrics.betweenness == {}
    assert metrics.closeness == {}
    assert metrics.num_communities == 0
    assert metrics.num_components == 0
    assert metrics.computed_at  # still sets timestamp


# ── Test 3 ───────────────────────────────────────────────────────────────────

def test_compute_metrics_on_disconnected_graph(disconnected_graph):
    """4 nodes in 2 disconnected pairs → num_components == 2."""
    metrics = compute_graph_metrics(disconnected_graph)

    assert metrics.num_components == 2
    assert set(metrics.pagerank.keys()) == {"a", "b", "c", "d"}
    # Louvain on disconnected pairs usually yields >= 2 communities.
    assert metrics.num_communities >= 2
    # All nodes must have a community assignment.
    assert set(metrics.communities.keys()) == {"a", "b", "c", "d"}
