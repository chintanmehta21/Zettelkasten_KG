from unittest.mock import MagicMock
import networkx as nx

from website.features.rag_pipeline.evaluation.kg_snapshot import (
    snapshot_kasten,
    compute_health_delta,
)
from website.features.rag_pipeline.evaluation.types import KGSnapshot


def test_snapshot_kasten_uses_subgraph():
    nodes = [
        {"id": "yt-a", "tags": ["psychedelics"]},
        {"id": "yt-b", "tags": ["psychedelics", "neuroscience"]},
        {"id": "yt-c", "tags": ["unrelated"]},
    ]
    edges = [
        {"source_node_id": "yt-a", "target_node_id": "yt-b", "relation": "psychedelics"},
    ]
    snap = snapshot_kasten(kasten_node_ids=["yt-a", "yt-b"], all_nodes=nodes, all_edges=edges)
    assert snap.node_count == 2  # only Kasten nodes counted? actually + 1-hop neighbors
    # Actually per spec: kasten + 1-hop neighbors
    # yt-a, yt-b are in kasten, no 1-hop neighbors outside (yt-c is unconnected)
    assert "yt-a" in snap.kasten_node_ids
    assert snap.edge_count == 1


def test_compute_health_delta():
    a = KGSnapshot(kasten_node_ids=["yt-a"], neighborhood_node_ids=["yt-a", "yt-b"],
                   node_count=2, edge_count=1, mean_degree=1.0, orphan_count=0, tag_count=2,
                   tag_histogram={"psychedelics": 2})
    b = KGSnapshot(kasten_node_ids=["yt-a", "yt-c"], neighborhood_node_ids=["yt-a", "yt-b", "yt-c"],
                   node_count=3, edge_count=3, mean_degree=2.0, orphan_count=0, tag_count=3,
                   tag_histogram={"psychedelics": 3, "neuroscience": 1})
    delta = compute_health_delta(prev=a, curr=b)
    assert delta["edges_added"] == 2
    assert delta["mean_degree_delta"] == 1.0
