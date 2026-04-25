"""KG snapshot + delta utilities."""
from __future__ import annotations

from collections import Counter

import networkx as nx

from website.features.rag_pipeline.evaluation.types import KGSnapshot


def snapshot_kasten(
    *,
    kasten_node_ids: list[str],
    all_nodes: list[dict],
    all_edges: list[dict],
) -> KGSnapshot:
    """Snapshot the Kasten + 1-hop neighborhood as a KGSnapshot."""
    nodes_by_id = {n["id"]: n for n in all_nodes}
    kasten_set = set(kasten_node_ids)

    # 1-hop neighbors via edges
    neighbors: set[str] = set(kasten_set)
    edges_in_scope: list[dict] = []
    for e in all_edges:
        s, t = e["source_node_id"], e["target_node_id"]
        if s in kasten_set or t in kasten_set:
            neighbors.add(s)
            neighbors.add(t)
            edges_in_scope.append(e)

    g = nx.Graph()
    g.add_nodes_from(neighbors)
    for e in edges_in_scope:
        g.add_edge(e["source_node_id"], e["target_node_id"])

    degrees = dict(g.degree())
    orphans = [n for n, d in degrees.items() if d == 0 and n in kasten_set]
    mean_degree = (sum(degrees.values()) / len(degrees)) if degrees else 0.0

    tag_hist: Counter[str] = Counter()
    for nid in neighbors:
        for tag in nodes_by_id.get(nid, {}).get("tags", []):
            tag_hist[tag] += 1

    return KGSnapshot(
        kasten_node_ids=sorted(kasten_set),
        neighborhood_node_ids=sorted(neighbors),
        node_count=len(neighbors),
        edge_count=len(edges_in_scope),
        mean_degree=round(mean_degree, 3),
        orphan_count=len(orphans),
        tag_count=len(tag_hist),
        tag_histogram=dict(tag_hist),
    )


def compute_health_delta(*, prev: KGSnapshot, curr: KGSnapshot) -> dict:
    return {
        "node_count_delta": curr.node_count - prev.node_count,
        "edges_added": max(curr.edge_count - prev.edge_count, 0),
        "edges_removed": max(prev.edge_count - curr.edge_count, 0),
        "mean_degree_delta": curr.mean_degree - prev.mean_degree,
        "orphan_delta": curr.orphan_count - prev.orphan_count,
        "tag_count_delta": curr.tag_count - prev.tag_count,
        "new_tags": sorted(set(curr.tag_histogram) - set(prev.tag_histogram)),
        "removed_tags": sorted(set(prev.tag_histogram) - set(curr.tag_histogram)),
    }
