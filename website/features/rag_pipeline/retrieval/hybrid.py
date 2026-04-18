"""Hybrid retrieval over Supabase RPCs."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from website.features.rag_pipeline.errors import EmptyScopeError
from website.features.rag_pipeline.types import QueryClass, RetrievalCandidate, ScopeFilter, SourceType, ChunkKind
from website.core.supabase_kg.client import get_supabase_client

_DEPTH_BY_CLASS = {
    QueryClass.LOOKUP: 1,
    QueryClass.VAGUE: 1,
    QueryClass.MULTI_HOP: 2,
    QueryClass.THEMATIC: 2,
    QueryClass.STEP_BACK: 2,
}

# Query-class-aware fusion weights (semantic, fulltext, graph). LOOKUP queries
# benefit from stronger lexical match on proper nouns and titles, MULTI_HOP
# and STEP_BACK queries benefit from graph expansion, THEMATIC leans semantic.
# Weights sum to ~1.0 per class to keep RRF score magnitudes comparable.
_WEIGHTS_BY_CLASS: dict[QueryClass, tuple[float, float, float]] = {
    QueryClass.LOOKUP: (0.35, 0.50, 0.15),
    QueryClass.VAGUE: (0.55, 0.25, 0.20),
    QueryClass.MULTI_HOP: (0.40, 0.25, 0.35),
    QueryClass.THEMATIC: (0.60, 0.20, 0.20),
    QueryClass.STEP_BACK: (0.50, 0.20, 0.30),
}
_DEFAULT_WEIGHTS: tuple[float, float, float] = (0.5, 0.3, 0.2)


class HybridRetriever:
    def __init__(self, embedder: Any, supabase: Any | None = None):
        self._supabase = supabase or get_supabase_client()
        self._embedder = embedder

    async def retrieve(
        self,
        *,
        user_id: UUID,
        query_variants: list[str],
        sandbox_id: UUID | None,
        scope_filter: ScopeFilter,
        query_class: QueryClass,
        limit: int = 30,
    ) -> list[RetrievalCandidate]:
        effective_nodes = await self._resolve_nodes(user_id, sandbox_id, scope_filter)
        if effective_nodes is not None and len(effective_nodes) == 0:
            raise EmptyScopeError("Scope resolved to zero Zettels")

        embeddings = await asyncio.gather(*[
            self._embedder.embed_query_with_cache(query) for query in query_variants
        ])
        graph_depth = _DEPTH_BY_CLASS[query_class]
        sem_w, fts_w, graph_w = _WEIGHTS_BY_CLASS.get(query_class, _DEFAULT_WEIGHTS)

        async def _search(query_text: str, query_vec: list[float]) -> list[dict]:
            response = self._supabase.rpc(
                "rag_hybrid_search",
                {
                    "p_user_id": str(user_id),
                    "p_query_text": query_text,
                    "p_query_embedding": query_vec,
                    "p_effective_nodes": effective_nodes,
                    "p_limit": limit,
                    "p_semantic_weight": sem_w,
                    "p_fulltext_weight": fts_w,
                    "p_graph_weight": graph_w,
                    "p_rrf_k": 60,
                    "p_graph_depth": graph_depth,
                },
            ).execute()
            return response.data or []

        results = await asyncio.gather(*[
            _search(query_text, query_vec)
            for query_text, query_vec in zip(query_variants, embeddings)
        ])
        return self._dedup_and_fuse(results)

    async def _resolve_nodes(
        self,
        user_id: UUID,
        sandbox_id: UUID | None,
        scope_filter: ScopeFilter,
    ) -> list[str] | None:
        if sandbox_id is None and not any(
            [scope_filter.node_ids, scope_filter.tags, scope_filter.source_types]
        ):
            return None
        response = self._supabase.rpc(
            "rag_resolve_effective_nodes",
            {
                "p_user_id": str(user_id),
                "p_sandbox_id": str(sandbox_id) if sandbox_id else None,
                "p_node_ids": scope_filter.node_ids,
                "p_tags": scope_filter.tags,
                "p_tag_mode": scope_filter.tag_mode,
                "p_source_types": [item.value for item in scope_filter.source_types] if scope_filter.source_types else None,
            },
        ).execute()
        return [row["node_id"] for row in (response.data or [])]

    def _dedup_and_fuse(self, multi_variant: list[list[dict]]) -> list[RetrievalCandidate]:
        by_key = {}
        variant_hits = {}
        for variant_results in multi_variant:
            seen_in_variant = set()
            for row in variant_results:
                key = (row["kind"], row["node_id"], row.get("chunk_id"))
                seen_in_variant.add(key)
                if key not in by_key:
                    by_key[key] = _row_to_candidate(row)
                    variant_hits[key] = 0
                else:
                    by_key[key].rrf_score = max(by_key[key].rrf_score, float(row.get("rrf_score") or 0.0))
            for key in seen_in_variant:
                variant_hits[key] += 1
        for key, candidate in by_key.items():
            candidate.rrf_score += 0.05 * (variant_hits[key] - 1)
        return sorted(by_key.values(), key=lambda candidate: candidate.rrf_score, reverse=True)


def _row_to_candidate(row: dict) -> RetrievalCandidate:
    source_value = str(row.get("source_type") or "web").lower()
    try:
        source_type = SourceType(source_value)
    except ValueError:
        source_type = SourceType.WEB
    kind_value = str(row.get("kind") or "chunk").lower()
    kind = ChunkKind.SUMMARY if kind_value == "summary" else ChunkKind.CHUNK
    return RetrievalCandidate(
        kind=kind,
        node_id=row["node_id"],
        chunk_id=row.get("chunk_id"),
        chunk_idx=int(row.get("chunk_idx") or 0),
        name=str(row.get("name") or row.get("title") or row["node_id"]),
        source_type=source_type,
        url=str(row.get("url") or ""),
        content=str(row.get("content") or row.get("summary") or ""),
        tags=list(row.get("tags") or []),
        metadata=dict(row.get("metadata") or {}),
        rrf_score=float(row.get("rrf_score") or 0.0),
    )

