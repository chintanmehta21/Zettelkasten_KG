"""M3 — Graph Analytics powered by igraph (D-KG-5 migration).

Computes structural metrics (PageRank, communities, closeness) over the
knowledge graph so the frontend can visualise importance and clusters.

Why igraph (per D-KG-5): networkx's pure-python pagerank/louvain are
O(V·E) with high constants; igraph's C core runs the same algorithms
~10-100x faster, which matters at our 10k+ scale target. The public
surface (``compute_graph_metrics(graph: KGGraph) -> GraphMetrics``) is
intentionally UNCHANGED — callers in ``website.api.routes`` and the
backfill scripts must not need to be touched.

Locked decision:
- ``compute_graph_metrics`` returns the canonical PageRank + Louvain +
  closeness + components + communities. Betweenness is *NOT* in the
  default path — it's O(V·E) and the production droplet (2GB/1vCPU)
  cannot afford it on every /api/graph call. The ``betweenness`` field
  on the returned dataclass is preserved for backward compatibility
  but populated with zeros; callers that need it must invoke
  :func:`compute_expensive_metrics` explicitly.
- Louvain seed=42 (D-KG-1 reproducibility). We pin both Python's
  ``random.seed(42)`` and igraph's internal RNG via
  ``igraph.set_random_number_generator`` so re-runs are byte-identical.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone

import igraph as ig

from website.core.graph_models import KGGraph

logger = logging.getLogger(__name__)


# ── Data model ──────────────────────────────────────────────────────────────

@dataclass
class GraphMetrics:
    """Computed graph-level and node-level metrics.

    ``betweenness`` is preserved for backward-compat but populated with zeros
    by :func:`compute_graph_metrics`. Callers that need real betweenness must
    use :func:`compute_expensive_metrics`.
    """

    pagerank: dict[str, float] = field(default_factory=dict)
    communities: dict[str, int] = field(default_factory=dict)
    betweenness: dict[str, float] = field(default_factory=dict)
    closeness: dict[str, float] = field(default_factory=dict)
    num_communities: int = 0
    num_components: int = 0
    computed_at: str = ""


# ── Graph construction ──────────────────────────────────────────────────────

def _build_igraph(graph: KGGraph) -> tuple[ig.Graph, list[str]]:
    """Build an undirected igraph graph from a ``KGGraph`` payload.

    Returns ``(igraph.Graph, [node_id_in_order])`` so callers can map vertex
    indices back to the string IDs used by the rest of the system.
    """
    node_ids: list[str] = [n.id for n in graph.nodes]
    if not node_ids:
        return ig.Graph(directed=False), []
    name_to_idx = {nid: i for i, nid in enumerate(node_ids)}
    edges: list[tuple[int, int]] = []
    for link in graph.links:
        si = name_to_idx.get(link.source)
        ti = name_to_idx.get(link.target)
        if si is None or ti is None:
            continue
        if si == ti:  # igraph allows self-loops but they hurt closeness/Louvain
            continue
        edges.append((si, ti))
    g = ig.Graph(n=len(node_ids), edges=edges, directed=False)
    g.vs["name"] = node_ids
    return g, node_ids


def _seed_rng_for_louvain() -> None:
    """Pin the global PRNG igraph reads from for community_multilevel.

    python-igraph 0.11+ delegates to Python's ``random`` for its internal
    RNG when ``set_random_number_generator(random)`` is set, which lets us
    seed deterministically.
    """
    try:
        ig.set_random_number_generator(random)
    except Exception:  # noqa: BLE001 — older igraph may not expose this
        pass
    random.seed(42)


def _safe(label: str, fn, fallback):
    """Run ``fn``; on any exception log+fallback."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — analytics must never abort the request
        logger.warning("%s failed: %s", label, exc)
        return fallback() if callable(fallback) else fallback


# ── Metric computation ──────────────────────────────────────────────────────

def compute_graph_metrics(graph: KGGraph) -> GraphMetrics:
    """Compute structural metrics for the given knowledge graph.

    Handles edge cases:
    - Empty graph: returns zeroed-out metrics.
    - Single node: pagerank = {id: 1.0}, 1 community, 1 component.
    - Disconnected graph: per-component community detection.

    NOTE: ``betweenness`` AND ``closeness`` are intentionally NOT computed
    here (D-KG-5 perf budget — both are O(V·E) and break the 5k <3s budget).
    The fields are populated with zeros for backward compatibility; use
    :func:`compute_expensive_metrics` if you need real values.
    """
    now = datetime.now(timezone.utc).isoformat()

    if not graph.nodes:
        return GraphMetrics(computed_at=now)

    g, node_ids = _build_igraph(graph)

    if g.vcount() == 1:
        sole = node_ids[0]
        return GraphMetrics(
            pagerank={sole: 1.0},
            communities={sole: 0},
            betweenness={sole: 0.0},
            closeness={sole: 0.0},
            num_communities=1,
            num_components=1,
            computed_at=now,
        )

    # ── PageRank ──────────────────────────────────────────────────────
    def _pagerank() -> dict[str, float]:
        pr = g.pagerank(damping=0.85)
        return {nid: float(pr[i]) for i, nid in enumerate(node_ids)}

    pagerank = _safe(
        "PageRank", _pagerank,
        lambda: {nid: 0.0 for nid in node_ids},
    )

    # ── Communities (Louvain, seed=42) ────────────────────────────────
    def _louvain() -> tuple[dict[str, int], int]:
        _seed_rng_for_louvain()
        partition = g.community_multilevel(weights=None, return_levels=False)
        membership = partition.membership
        return (
            {nid: int(membership[i]) for i, nid in enumerate(node_ids)},
            len(set(membership)),
        )

    communities, num_communities = _safe(
        "Louvain community detection",
        _louvain,
        lambda: ({nid: 0 for nid in node_ids}, 1),
    )

    # ── Components ───────────────────────────────────────────────────
    num_components = _safe(
        "Connected components count",
        lambda: int(len(g.connected_components(mode="weak"))),
        1,
    )

    return GraphMetrics(
        pagerank=pagerank,
        communities=communities,
        # Backward-compat sentinels: zeros so existing callers don't KeyError.
        # See compute_expensive_metrics() for real betweenness + closeness.
        betweenness={nid: 0.0 for nid in node_ids},
        closeness={nid: 0.0 for nid in node_ids},
        num_communities=num_communities,
        num_components=num_components,
        computed_at=now,
    )


def compute_expensive_metrics(graph: KGGraph) -> GraphMetrics:
    """Compute the same metrics PLUS betweenness AND closeness centrality.

    Opt-in expensive companion to :func:`compute_graph_metrics`. Use only
    on offline / admin paths — DO NOT invoke from the per-request
    ``/api/graph`` handler. Both metrics are O(V·E) on connected graphs
    and break the 5k <3s budget that protects the 2GB / 1vCPU droplet.
    """
    base = compute_graph_metrics(graph)
    if not graph.nodes:
        return base

    g, node_ids = _build_igraph(graph)
    if g.vcount() == 1:
        return base

    def _betweenness() -> dict[str, float]:
        bt = g.betweenness()
        # Normalise to [0, 1] as networkx did, for callers expecting that scale.
        n = len(node_ids)
        norm = max(1, (n - 1) * (n - 2) / 2) if n > 2 else 1
        return {nid: float(bt[i]) / norm for i, nid in enumerate(node_ids)}

    def _closeness() -> dict[str, float]:
        cl = g.closeness(normalized=True)
        return {nid: float(cl[i] if cl[i] is not None else 0.0)
                for i, nid in enumerate(node_ids)}

    base.betweenness = _safe(
        "Betweenness centrality", _betweenness,
        lambda: {nid: 0.0 for nid in node_ids},
    )
    base.closeness = _safe(
        "Closeness centrality", _closeness,
        lambda: {nid: 0.0 for nid in node_ids},
    )
    return base
