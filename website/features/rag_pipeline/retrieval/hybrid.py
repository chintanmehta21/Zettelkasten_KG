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
# iter-02 retune: the rag_eval YouTube baseline showed THEMATIC queries dominate
# this corpus (5/5 seed Qs classify as THEMATIC), graph_score lift on rerank
# was +14.4pt while retrieval lift was 0. Boosting graph in retrieval to claw
# back some of that lift while keeping semantic dominant.
_WEIGHTS_BY_CLASS: dict[QueryClass, tuple[float, float, float]] = {
    QueryClass.LOOKUP: (0.35, 0.50, 0.15),
    QueryClass.VAGUE: (0.55, 0.25, 0.20),
    QueryClass.MULTI_HOP: (0.40, 0.25, 0.35),
    QueryClass.THEMATIC: (0.55, 0.20, 0.25),  # iter-02: +0.05 graph at retrieval
    QueryClass.STEP_BACK: (0.50, 0.20, 0.30),
}
_DEFAULT_WEIGHTS: tuple[float, float, float] = (0.5, 0.3, 0.2)

# iter-03 retune: revert per-node chunk cap from 2 -> 3. iter-02 showed that
# cap=2 starved the synthesis stage (faithfulness 1.0 -> 0.5, hallucination
# 0 -> 0.2) because the LLM extrapolated past shrunken contexts.
# Restoring breadth at the chunk level; precision is now policed at the
# context-assembly stage via a similarity floor (see context/assembler.py).
_MAX_CHUNKS_PER_NODE = 3


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

        query_variants = _dedupe_variants(query_variants)

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
        return self._dedup_and_fuse(results, query_variants=query_variants)

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

    def _dedup_and_fuse(
        self,
        multi_variant: list[list[dict]],
        *,
        query_variants: list[str] | None = None,
    ) -> list[RetrievalCandidate]:
        by_key = {}
        variant_hits = {}
        for variant_results in multi_variant:
            seen_in_variant = set()
            for row in variant_results:
                if not row.get("node_id"):
                    # Defensive: rag_hybrid_search occasionally returns aggregate
                    # rows with null node_id (e.g. when summary-mode rolls up a
                    # group). These can't be cited, so drop them at the edge.
                    continue
                key = (row["kind"], row["node_id"], row.get("chunk_id"))
                seen_in_variant.add(key)
                if key not in by_key:
                    by_key[key] = _row_to_candidate(row)
                    variant_hits[key] = 0
                else:
                    by_key[key].rrf_score = max(by_key[key].rrf_score, float(row.get("rrf_score") or 0.0))
            for key in seen_in_variant:
                variant_hits[key] += 1

        normalized_variants = [
            _normalize_for_match(v) for v in (query_variants or []) if v and v.strip()
        ]

        kinds_by_node: dict[str, set[str]] = {}
        for candidate in by_key.values():
            kinds_by_node.setdefault(candidate.node_id, set()).add(candidate.kind.value)

        for key, candidate in by_key.items():
            candidate.rrf_score += 0.05 * (variant_hits[key] - 1)
            # Title/name-match boost — queries that mention a zettel name
            # verbatim should reliably surface that zettel even when dense /
            # FTS signals are weak (e.g. stub bodies, rare embeddings).
            boost = _title_match_boost(candidate.name, normalized_variants)
            if boost > 0:
                candidate.rrf_score += boost
            # Sibling consensus — when both a summary and chunk(s) surface for
            # the same node, that cross-kind agreement is a stronger relevance
            # signal than a single stream. Small bump so it nudges, not skews.
            if len(kinds_by_node.get(candidate.node_id, set())) > 1:
                candidate.rrf_score += 0.03
        ordered = sorted(by_key.values(), key=lambda candidate: candidate.rrf_score, reverse=True)
        return _cap_per_node(ordered, _MAX_CHUNKS_PER_NODE)


def _cap_per_node(
    candidates: list[RetrievalCandidate],
    max_chunks_per_node: int,
) -> list[RetrievalCandidate]:
    """Keep at most ``max_chunks_per_node`` chunk candidates per ``node_id`` so
    a single verbose node cannot crowd out the top-K handed to the reranker.
    Summary-kind candidates are unaffected — one summary + N chunks per node
    still pass through."""
    seen_chunk_count: dict[str, int] = {}
    kept: list[RetrievalCandidate] = []
    for candidate in candidates:
        if candidate.kind is ChunkKind.CHUNK:
            count = seen_chunk_count.get(candidate.node_id, 0)
            if count >= max_chunks_per_node:
                continue
            seen_chunk_count[candidate.node_id] = count + 1
        kept.append(candidate)
    return kept


def _dedupe_variants(variants: list[str]) -> list[str]:
    """Drop empty / duplicate query variants (case- and whitespace-insensitive)
    while preserving the original order. The expander sometimes emits the raw
    query alongside a paraphrase that collapses to the same normalized form,
    which would otherwise double the RPC load and inflate consensus boosts."""
    seen: set[str] = set()
    kept: list[str] = []
    for variant in variants or []:
        if not variant or not str(variant).strip():
            continue
        normalized = _normalize_for_match(variant)
        if normalized in seen:
            continue
        seen.add(normalized)
        kept.append(variant)
    return kept


def _normalize_for_match(text: str) -> str:
    """Lowercase and collapse whitespace so title matching is punctuation-
    insensitive without requiring exact casing from the user's query."""
    import re
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _title_match_boost(name: str, normalized_variants: list[str]) -> float:
    """Return a boost if any query variant appears as a substring of the
    candidate's name (or vice-versa for short names). Boost is graded so
    full equality beats partial containment."""
    if not name or not normalized_variants:
        return 0.0
    normalized_name = _normalize_for_match(name)
    if not normalized_name:
        return 0.0
    best = 0.0
    for variant in normalized_variants:
        if not variant:
            continue
        if variant == normalized_name:
            best = max(best, 0.40)
        elif variant in normalized_name or normalized_name in variant:
            # Partial containment — meaningful when user paraphrases a title.
            ratio = min(len(variant), len(normalized_name)) / max(
                len(variant), len(normalized_name)
            )
            best = max(best, 0.20 * ratio)
    return best


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

