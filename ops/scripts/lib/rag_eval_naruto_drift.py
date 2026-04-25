"""Halt the rag_eval CLI on unexplained Naruto KG drift (spec §11)."""
from __future__ import annotations


class NarutoDriftError(Exception):
    pass


def check_naruto_drift(
    *,
    baseline: dict,
    current: dict,
    applied_mutation_count: int,
    node_tolerance_pct: float = 10.0,
    edge_tolerance_pct: float = 20.0,
) -> None:
    """Raise if KG drifted beyond tolerance unexplained by applied mutations.

    Each applied mutation accounts for ~1 node or edge change; we subtract that
    from the observed delta before comparing against tolerance.
    """
    base_nodes = baseline.get("node_count", 0)
    base_edges = baseline.get("link_count", 0)
    cur_nodes = current.get("node_count", 0)
    cur_edges = current.get("link_count", 0)

    raw_node_delta = abs(cur_nodes - base_nodes)
    raw_edge_delta = abs(cur_edges - base_edges)
    explained_node_delta = max(raw_node_delta - applied_mutation_count, 0)
    explained_edge_delta = max(raw_edge_delta - applied_mutation_count, 0)

    if base_nodes:
        node_pct = (explained_node_delta / base_nodes) * 100.0
        if node_pct > node_tolerance_pct:
            raise NarutoDriftError(
                f"Naruto KG node count drifted {explained_node_delta} (unexplained) "
                f"= {node_pct:.1f}% > {node_tolerance_pct}% tolerance. Halting."
            )
    if base_edges:
        edge_pct = (explained_edge_delta / base_edges) * 100.0
        if edge_pct > edge_tolerance_pct:
            raise NarutoDriftError(
                f"Naruto KG edge count drifted {explained_edge_delta} (unexplained) "
                f"= {edge_pct:.1f}% > {edge_tolerance_pct}% tolerance. Halting."
            )
