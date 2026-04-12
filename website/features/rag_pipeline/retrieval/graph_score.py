"""Graph centrality scoring over retrieval candidates."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import networkx as nx

from website.features.rag_pipeline.types import RetrievalCandidate
from website.core.supabase_kg.client import get_supabase_client


class LocalizedPageRankScorer:
    """Compute a small induced-subgraph PageRank score for candidates."""

    def __init__(self, damping: float = 0.85, supabase: Any | None = None):
        self._supabase = supabase or get_supabase_client()
        self._damping = damping

    async def score(self, *, user_id: UUID, candidates: list[RetrievalCandidate]) -> None:
        node_ids = list({candidate.node_id for candidate in candidates})
        if len(node_ids) < 2:
            for candidate in candidates:
                candidate.graph_score = 0.0
            return

        response = self._supabase.rpc(
            "rag_subgraph_for_pagerank",
            {"p_user_id": str(user_id), "p_node_ids": node_ids},
        ).execute()
        edges = response.data or []

        graph = nx.Graph()
        graph.add_nodes_from(node_ids)
        for edge in edges:
            graph.add_edge(
                edge["source_node_id"],
                edge["target_node_id"],
                weight=edge.get("weight") or 1.0,
            )

        if graph.number_of_edges() == 0:
            for candidate in candidates:
                candidate.graph_score = 0.0
            return

        pagerank = nx.pagerank(graph, alpha=self._damping, weight="weight")
        max_score = max(pagerank.values()) or 1.0
        for candidate in candidates:
            candidate.graph_score = pagerank.get(candidate.node_id, 0.0) / max_score

