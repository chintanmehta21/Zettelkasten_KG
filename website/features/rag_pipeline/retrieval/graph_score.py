"""Graph centrality scoring over retrieval candidates."""

from __future__ import annotations

import logging
import math
import os
from typing import Any
from uuid import UUID

import networkx as nx

from website.features.rag_pipeline.types import QueryClass, RetrievalCandidate
from website.core.supabase_v2.client import get_v2_client
from website.core.supabase_v2.repositories.rag_repository import RAGRepository
from website.features.rag_pipeline.retrieval._async_helpers import rpc_call


_logger = logging.getLogger(__name__)

_USAGE_EDGES_ENABLED = os.environ.get("RAG_USAGE_EDGES_ENABLED", "true").lower() == "true"

# Phase D P2-5: KG-aware retrieval for THEMATIC / MULTI_HOP. For these two
# classes ONLY, the localized-PageRank centrality is blended with a bounded
# in-subgraph proximity term (normalized degree over the SAME induced subgraph
# already built for PageRank — NO extra DB query). All other classes are
# byte-identical to the pre-Phase-D behaviour (pure pr_norm). The cold /
# failure / <2-node / 0-edge degrade contract (graph_score == 0.0) is
# preserved unchanged.
_PROX_PR_W: float = 0.7  # PageRank share of the blended graph_score
_PROX_W: float = 0.3  # in-subgraph proximity share
_PROX_GATED_CLASSES = (QueryClass.MULTI_HOP, QueryClass.THEMATIC)


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _usage_weight_bonus(
    rag_repo: RAGRepository,
    *,
    workspace_id: UUID,
    target_node_id: str,
    query_class: QueryClass | str,
) -> float:
    """Read decayed retrieval-signal weights for (workspace, target, query_class) and map to a bounded bonus.

    Phase 2.3 v2 purge: reads from `rag.retrieval_signal_weights` via the
    `rag.search_signal_weights` RPC (replaces the retired legacy v1
    materialised view). The decay-weight scoring math is byte-for-byte
    unchanged: rows' weights are summed and passed through the same sigmoid
    bound.

    P1 (Codex review #3262442111): ``workspace_id`` MUST be the resolved
    workspace UUID, NOT the auth-subject/profile UUID. ``rag.search_signal_weights``
    filters ``WHERE workspace_id = p_workspace_id``; the v2 client is
    service_role so a profile UUID does not raise but silently matches zero
    rows (bonus collapses to 0). The caller threads the workspace_id resolved
    once at runtime build (service.py::_build_runtime -> get_default_workspace_id).

    Returns a sigmoid-bounded value in [-0.05, +0.05] (≈0 when weight==0,
    approaching +0.05 as weight grows). Returns 0.0 on any failure so a missing
    underlying table (cold staging) or transient DB error never breaks the
    request path.
    """
    if not _USAGE_EDGES_ENABLED:
        return 0.0
    try:
        qc_value = query_class.value if hasattr(query_class, "value") else str(query_class)
        rows = rag_repo.search_signal_weights(
            workspace_id=workspace_id,
            target_chunk_ids=[target_node_id],
            query_class=qc_value,
        )
        weight = sum(float(r.get("weight") or 0.0) for r in rows)
        # Sigmoid-bounded bonus in (-0.05, +0.05); 0 when weight==0.
        return 0.10 / (1.0 + math.exp(-weight / 5.0)) - 0.05
    except Exception:
        return 0.0


class LocalizedPageRankScorer:
    """Compute a small induced-subgraph PageRank score for candidates."""

    def __init__(
        self,
        damping: float = 0.85,
        supabase: Any | None = None,
        workspace_id: UUID | None = None,
    ):
        # v2 purge: default supabase client comes from the v2 client factory.
        # Tests / runtime callers can still inject a mock supabase-py-shaped
        # client to override.
        self._supabase = supabase or get_v2_client()
        self._damping = damping
        # P1 (Codex #3262442111): the resolved workspace UUID (NOT the
        # auth-subject/profile UUID). Threaded once from service.py::
        # _build_runtime via get_default_workspace_id(profile_id). Both
        # rag.subgraph_for_pagerank and rag.search_signal_weights filter
        # WHERE workspace_id = p_workspace_id; the v2 client is service_role
        # so a profile UUID does not error — it silently matches zero rows
        # (graph_score -> 0.0 for all traffic). When None (no resolvable
        # workspace), score() falls back to user_id, preserving the prior
        # behaviour (degrade to 0.0) rather than regressing.
        self._workspace_id = workspace_id
        # RAGRepository wraps the v2 search_signal_weights RPC; reuse the
        # same client so a single Supabase project handles both calls.
        self._rag_repo = RAGRepository(self._supabase)

    async def score(
        self,
        *,
        user_id: UUID,
        candidates: list[RetrievalCandidate],
        query_class: QueryClass | str | None = None,
    ) -> None:
        node_ids = list({candidate.node_id for candidate in candidates})
        if len(node_ids) < 2:
            for candidate in candidates:
                candidate.graph_score = 0.0
            return

        # P1 (Codex #3262442111): both rag.subgraph_for_pagerank and
        # rag.search_signal_weights are workspace-keyed
        # (WHERE workspace_id = p_workspace_id). ``user_id`` is the
        # auth-subject/profile UUID (service.py: kg_user_id = UUID(user_sub)),
        # NOT the workspace UUID — passing it matched zero rows under the
        # service_role client (silent graph_score=0.0 for all traffic). Use
        # the workspace_id resolved once at runtime build; fall back to
        # user_id only when no workspace was resolvable (preserves the prior
        # degrade-to-0.0 behaviour rather than regressing).
        ws_id = self._workspace_id or user_id

        # v2 purge (P1-1): schema-qualified call into `rag.subgraph_for_pagerank`
        # (supabase/website/_v2/45_rag_subgraph_for_pagerank.sql). The legacy
        # unqualified `rag_subgraph_for_pagerank` was a dropped v1 zombie that
        # threw on every call, silently degrading centrality to 0.0. Under v2
        # `candidate.node_id` is the canonical_chunk_id (str) so it maps to the
        # RPC's `p_chunk_ids uuid[]`. Failure path still degrades to 0.0
        # centrality, but now logs at WARNING instead of being silently
        # swallowed by the dropped-RPC exception.
        try:
            response = await rpc_call(self._supabase.schema("rag").rpc(
                "subgraph_for_pagerank",
                {"p_workspace_id": str(ws_id), "p_chunk_ids": node_ids},
            ))
            edges = response.data or []
        except Exception as exc:
            _logger.warning(
                "graph_score: rag.subgraph_for_pagerank failed (workspace=%s, "
                "candidates=%d); degrading graph_score to 0.0: %r",
                ws_id,
                len(node_ids),
                exc,
            )
            for candidate in candidates:
                candidate.graph_score = 0.0
            return

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
        else:
            pagerank = nx.pagerank(graph, alpha=self._damping, weight="weight")
            max_score = max(pagerank.values()) or 1.0
            # Phase D P2-5: class-gated proximity blend. Resolve the class to a
            # QueryClass enum (it may arrive as enum, str, or None) and only
            # enrich for THEMATIC / MULTI_HOP. Every other class falls through
            # to the byte-identical pure-pr_norm assignment below.
            _qc: QueryClass | None
            if isinstance(query_class, QueryClass):
                _qc = query_class
            elif isinstance(query_class, str):
                _qc = next(
                    (c for c in QueryClass if c.value == query_class), None
                )
            else:
                _qc = None
            _prox_gated = _qc in _PROX_GATED_CLASSES
            if _prox_gated:
                # Bounded proximity over the SAME induced subgraph (no extra
                # DB call): networkx degree_centrality is normalized to [0, 1]
                # by (n - 1), so it is a cheap, bounded short-range
                # connectivity proxy for query-anchor proximity.
                prox = nx.degree_centrality(graph)
                max_prox = max(prox.values()) or 1.0
            for candidate in candidates:
                pr_norm = pagerank.get(candidate.node_id, 0.0) / max_score
                if _prox_gated:
                    prox_norm = prox.get(candidate.node_id, 0.0) / max_prox
                    candidate.graph_score = _clamp01(
                        _PROX_PR_W * pr_norm + _PROX_W * prox_norm
                    )
                else:
                    candidate.graph_score = pr_norm

        # Usage-edge bonus: only applied when query_class is supplied (caller opts in).
        # Cached per target node_id within this call to avoid duplicate DB lookups
        # when multiple chunk-candidates share a node.
        if query_class is None:
            return

        bonus_cache: dict[str, float] = {}
        for candidate in candidates:
            if candidate.node_id not in bonus_cache:
                bonus_cache[candidate.node_id] = _usage_weight_bonus(
                    self._rag_repo,
                    workspace_id=ws_id,
                    target_node_id=candidate.node_id,
                    query_class=query_class,
                )
            candidate.graph_score = (candidate.graph_score or 0.0) + bonus_cache[candidate.node_id]
