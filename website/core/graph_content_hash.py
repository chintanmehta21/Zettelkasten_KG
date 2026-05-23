"""LD-9 / A1: BLAKE3 content-hash memoization for graph analytics.

Key: ``blake3(sorted_node_ids || sorted_edge_tuples)``. Two graphs with
identical topology produce identical hashes. ``TTL=600s``, ``maxsize=50``
per LD-9. Fits the 2 GB / 1 vCPU droplet: 50 entries × ~250 KB metric
payload ≈ 12.5 MB.

LD-10: enrichment is computed on the FULL graph (no min_strength filter),
so the hash MUST exclude per-edge ``connection_strength`` / ``tier`` —
otherwise a re-scored same-topology graph misses the cache.

Degrades cleanly when ``blake3`` / ``cachetools`` are missing (unit-test
mode without ops/requirements installed): hash returns the empty string
and the cache is a no-op LRU.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from blake3 import blake3 as _blake3  # type: ignore[import-untyped]
    _BLAKE3_AVAILABLE = True
except ImportError:  # pragma: no cover - degrade gracefully
    _BLAKE3_AVAILABLE = False
    _blake3 = None  # type: ignore[assignment]

try:
    from cachetools import TTLCache  # type: ignore[import-untyped]
    _CACHETOOLS_AVAILABLE = True
except ImportError:  # pragma: no cover - degrade gracefully
    _CACHETOOLS_AVAILABLE = False

    class TTLCache(dict):  # type: ignore[no-redef]
        def __init__(self, maxsize: int, ttl: int) -> None:
            super().__init__()


_ANALYTICS_CACHE: TTLCache = TTLCache(maxsize=50, ttl=600)


def compute_graph_hash(graph_dict: dict) -> str:
    """Deterministic hash of (nodes, edges) topology.

    Excludes per-node metric fields (pagerank, community, betweenness, etc.)
    and edge properties that don't affect topology (connection_strength, tier,
    description) so a re-scored same-topology graph still hits the cache.
    """
    if not _BLAKE3_AVAILABLE:
        return ""
    nodes = sorted(
        str(n.get("id", "")) for n in graph_dict.get("nodes", [])
        if isinstance(n, dict)
    )
    edges = sorted(
        (
            str(link.get("source", "")),
            str(link.get("target", "")),
            str(link.get("relation", "")),
        )
        for link in graph_dict.get("links", [])
        if isinstance(link, dict)
    )
    payload = json.dumps({"n": nodes, "e": edges}, separators=(",", ":"))
    return _blake3(payload.encode("utf-8")).hexdigest()


def get_cached_metrics(graph_hash: str) -> Any:
    """Return cached metrics or ``None`` on miss / empty hash."""
    if not graph_hash:
        return None
    return _ANALYTICS_CACHE.get(graph_hash)


def put_cached_metrics(graph_hash: str, metrics: Any) -> None:
    """Cache ``metrics`` under ``graph_hash`` if hashing is available."""
    if not graph_hash:
        return
    _ANALYTICS_CACHE[graph_hash] = metrics


def invalidate_all() -> None:
    """Admin / test helper — clears the per-process analytics cache."""
    _ANALYTICS_CACHE.clear()
