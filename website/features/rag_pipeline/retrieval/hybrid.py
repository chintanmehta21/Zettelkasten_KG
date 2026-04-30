"""Hybrid retrieval over Supabase RPCs."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from website.features.rag_pipeline.errors import EmptyScopeError
from website.features.rag_pipeline.query.metadata import QueryMetadata
from website.features.rag_pipeline.retrieval.kasten_freq import (
    KastenFrequencyStore,
    compute_frequency_penalty,
)
from website.features.rag_pipeline.types import QueryClass, RetrievalCandidate, ScopeFilter, SourceType, ChunkKind
from website.core.supabase_kg.client import get_supabase_client

_log = logging.getLogger(__name__)

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
# iter-06 best-of: restore iter-03 THEMATIC weights (0.55, 0.20, 0.25). iter-03
# delivered synthesis 88.22 with these weights; iter-04's softer fulltext
# rebalance was probe-specific and slightly hurt synthesis because broader
# fulltext recall pulled in tag-only matches. Pair with cascade fusion below.
_WEIGHTS_BY_CLASS: dict[QueryClass, tuple[float, float, float]] = {
    QueryClass.LOOKUP: (0.35, 0.50, 0.15),
    QueryClass.VAGUE: (0.55, 0.25, 0.20),
    QueryClass.MULTI_HOP: (0.40, 0.25, 0.35),
    QueryClass.THEMATIC: (0.55, 0.20, 0.25),  # iter-06: revert to iter-03 best-of
    QueryClass.STEP_BACK: (0.50, 0.20, 0.30),
}
_DEFAULT_WEIGHTS: tuple[float, float, float] = (0.5, 0.3, 0.2)

# iter-03 retune: revert per-node chunk cap from 2 -> 3. iter-02 showed that
# cap=2 starved the synthesis stage (faithfulness 1.0 -> 0.5, hallucination
# 0 -> 0.2) because the LLM extrapolated past shrunken contexts.
# Restoring breadth at the chunk level; precision is now policed at the
# context-assembly stage via a similarity floor (see context/assembler.py).
_MAX_CHUNKS_PER_NODE = 3

# iter-04: xQuAD diversity-by-construction (Abdollahpouri et al. 2017).
# After all per-candidate score adjustments, we pick top-K slot-by-slot
# greedy-maximising lambda*rel - (1-lambda)*overlap_with_already_picked,
# where overlap is per-node_id (so a magnet that already has a chunk in
# the picked set gets demoted for subsequent slots). Replaces a flat
# sort that let one node monopolize the top of the candidate list.
_XQUAD_LAMBDA = 0.7

# iter-04 consensus-suppress threshold: if a candidate appears in >= this
# fraction of variants, suppress the per-variant consensus bump (it's a
# magnet, not a relevance signal). The bump is at line ~169.
_CONSENSUS_SUPPRESS_FRACTION = 0.5


class HybridRetriever:
    def __init__(
        self,
        embedder: Any,
        supabase: Any | None = None,
        *,
        kasten_freq_store: KastenFrequencyStore | None = None,
    ):
        self._supabase = supabase or get_supabase_client()
        self._embedder = embedder
        # iter-04: anti-magnet per-Kasten frequency prior. Optional; when
        # None we skip the prior (cold-start / single-Kasten dev paths).
        self._kasten_freq = kasten_freq_store or KastenFrequencyStore(self._supabase)

    async def retrieve(
        self,
        *,
        user_id: UUID,
        query_variants: list[str],
        sandbox_id: UUID | None,
        scope_filter: ScopeFilter,
        query_class: QueryClass,
        limit: int = 30,
        query_metadata: QueryMetadata | None = None,
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

        # iter-04: kick off the per-Kasten frequency lookup in parallel with
        # the hybrid RPCs so it's free latency-wise.
        freq_task = asyncio.create_task(
            self._kasten_freq.get_frequencies(sandbox_id)
        )

        results = await asyncio.gather(*[
            _search(query_text, query_vec)
            for query_text, query_vec in zip(query_variants, embeddings)
        ])

        kasten_freqs: dict[str, int] = {}
        try:
            kasten_freqs = await freq_task
        except Exception as exc:  # noqa: BLE001 — best-effort
            _log.debug("kasten_freq fetch failed: %s", exc)
            kasten_freqs = {}

        return self._dedup_and_fuse(
            results,
            query_variants=query_variants,
            query_metadata=query_metadata,
            query_class=query_class,
            kasten_freqs=kasten_freqs,
            effective_nodes=effective_nodes,
        )

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
        query_metadata: QueryMetadata | None = None,
        query_class: QueryClass | None = None,
        kasten_freqs: dict[str, int] | None = None,
        effective_nodes: list[str] | None = None,
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

        # iter-04 consensus-suppress: a node hit by EVERY variant in a 3+
        # variant fan-out is a topic-magnet (q10 root cause: web-tools-for
        # hit all 3 paraphrases of the Steve Jobs question and won by the
        # consensus bump alone). Suppress the bump only in that magnet
        # case — small 2-variant fan-outs and legit 2-of-3 matches still
        # get the original consensus boost.
        total_variants = max(len(multi_variant), 1)
        for key, candidate in by_key.items():
            hits = variant_hits[key]
            is_magnet = hits == total_variants and total_variants >= 3
            if hits > 1 and not is_magnet:
                candidate.rrf_score += 0.05 * (hits - 1)
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

        # Query-metadata-aware boosts (T10): recency, source-type, and
        # author-match. Skipped entirely when no QueryMetadata is supplied so
        # legacy callers see zero overhead and zero behavioral change.
        if query_metadata is not None and query_class is not None:
            total_boost = 0.0
            # Spec 2B.1: action-verb boost matches against the user's actual
            # question. The first deduped variant is the standalone form of
            # the user's query (rewriter passes it through verbatim when there
            # is no transformation), so use it as the source-of-truth string.
            primary_question = (query_variants or [""])[0] if query_variants else ""
            for candidate in by_key.values():
                rec = _recency_boost(candidate.metadata, query_class)
                src_st = getattr(candidate.source_type, "value", candidate.source_type)
                # _source_type_boost returns the *new* score (base + adjustments).
                # Subtract the unmodified base to derive the delta we apply.
                src_new = _source_type_boost(
                    base_score=0.0,
                    source_type=str(src_st or ""),
                    query_class=query_class,
                    question=primary_question,
                )
                src = src_new  # base was 0.0 -> the return is the delta
                aut = _author_match_boost(candidate, query_metadata)
                delta = rec + src + aut
                if delta:
                    candidate.rrf_score += delta
                    total_boost += delta
            if total_boost:
                _log.debug(
                    "dedup_and_fuse query-metadata boost total=%.4f over %d candidates",
                    total_boost,
                    len(by_key),
                )

        # iter-04 anti-magnet per-Kasten frequency prior. Multiplicatively
        # damps the score of nodes that have a high top-1 hit history within
        # this Kasten. Floor of 50 total hits prevents cold-start over-
        # penalisation; cap at 0.5 so a magnet can still rank where genuine
        # signal puts it.
        if kasten_freqs:
            total_hits = sum(kasten_freqs.values())
            for candidate in by_key.values():
                penalty = compute_frequency_penalty(
                    kasten_freqs.get(candidate.node_id, 0),
                    total_hits_in_kasten=total_hits,
                )
                if penalty < 1.0:
                    candidate.rrf_score *= penalty

        # sorted() is stable: ties preserve insertion order, which mirrors the
        # row order across query variants — critical for deterministic ranking
        # when multiple candidates land on identical final scores.
        ordered = sorted(by_key.values(), key=lambda candidate: candidate.rrf_score, reverse=True)

        # iter-04 xQuAD slot-by-slot selection (Abdollahpouri 2017). Replaces
        # the flat sort with a greedy diversity-by-construction picker:
        # at each slot, pick the candidate that maximises
        # lambda*rel - (1-lambda)*overlap_with_already_picked, where overlap
        # counts node_ids already in the picked set. Diversity-aware ranking
        # is what prevents one node monopolising the top-K (q5 fix).
        ordered = _xquad_select(ordered, lam=_XQUAD_LAMBDA)

        # iter-04: q5 cross-corpus thematic still misses members because xQuAD's
        # 0.3 demotion can't overcome a 1.5x score gap. Promote one chunk per Kasten member
        # to the front for THEMATIC-class queries.
        if (
            query_class is QueryClass.THEMATIC
            and effective_nodes
            and len(effective_nodes) >= 2
        ):
            ordered = _ensure_member_coverage(
                ordered, member_ids=effective_nodes, min_per_member=1,
            )

        return _cap_per_node(ordered, _MAX_CHUNKS_PER_NODE)


def _xquad_select(
    candidates: list[RetrievalCandidate],
    *,
    lam: float = 0.7,
) -> list[RetrievalCandidate]:
    """xQuAD slot-by-slot diversity selector.

    Greedy: at each slot, pick the candidate maximising
    ``lam * rel - (1 - lam) * already_picked_count_for_node``. ``rel`` is
    the candidate's current ``rrf_score`` (already includes all boosts and
    the frequency prior). The penalty is per-``node_id``, so a magnet with
    one chunk picked gets a -0.05 ish demotion when its second chunk would
    otherwise win the next slot.

    Returns a list with the same length as the input (no candidates are
    dropped — only reordered). Stable for ties via insertion order, since
    we iterate the input list in deterministic order.
    """
    if not candidates:
        return candidates
    if len(candidates) == 1:
        return list(candidates)
    remaining = list(candidates)
    picked: list[RetrievalCandidate] = []
    picked_node_counts: dict[str, int] = {}
    one_minus_lam = 1.0 - lam
    while remaining:
        best_idx = 0
        best_score = float("-inf")
        for i, candidate in enumerate(remaining):
            relevance = candidate.rrf_score
            overlap = picked_node_counts.get(candidate.node_id, 0)
            xq = lam * relevance - one_minus_lam * overlap
            if xq > best_score:
                best_score = xq
                best_idx = i
        chosen = remaining.pop(best_idx)
        picked.append(chosen)
        picked_node_counts[chosen.node_id] = picked_node_counts.get(chosen.node_id, 0) + 1
    return picked


def _ensure_member_coverage(
    candidates: list[RetrievalCandidate],
    *,
    member_ids: list[str],
    min_per_member: int = 1,
) -> list[RetrievalCandidate]:
    """iter-04: THEMATIC diversity floor — promote one chunk per Kasten member
    to the front of ``candidates`` so the top-K handed to the reranker covers
    every member that has any retrieved chunk. Members with zero retrieved
    chunks are silently skipped (cannot promote what isn't there). Members
    already represented in the top ``len(member_ids) * min_per_member`` slots
    are left where they are. The order within the promoted block follows
    score-descending (i.e. the best chunk per member, in score order across
    members). The remainder of the input list is appended in the order it
    arrived (xQuAD-ordered)."""
    if not candidates or not member_ids or min_per_member < 1:
        return candidates
    member_set = set(member_ids)
    # Best chunk per member, in input order (already xQuAD-ranked).
    promoted_per_member: dict[str, list[RetrievalCandidate]] = {}
    leftover: list[RetrievalCandidate] = []
    for cand in candidates:
        nid = cand.node_id
        if nid in member_set and len(promoted_per_member.get(nid, [])) < min_per_member:
            promoted_per_member.setdefault(nid, []).append(cand)
        else:
            leftover.append(cand)
    # Flatten promoted block in descending rrf_score so highest-quality member
    # picks lead the list (preserves xQuAD's relevance ordering across members).
    promoted: list[RetrievalCandidate] = []
    for chunks in promoted_per_member.values():
        promoted.extend(chunks)
    promoted.sort(key=lambda c: c.rrf_score, reverse=True)
    return promoted + leftover


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


def _recency_boost(metadata: dict | None, query_class: QueryClass) -> float:
    """Return a small positive score boost for chunks whose source content is
    recent. Pure helper — no I/O, never raises, never returns negative.

    The chunk-date field is read from ``metadata['timestamp']`` first, falling
    back to ``metadata['time_span']['end']`` so that both per-chunk timestamps
    and aggregate node-level spans are honored. Anything missing or
    unparseable yields 0.0. Future-dated chunks also yield 0.0 (so a clock
    skew can never penalise — and never inflate — a candidate).

    Magnitude: linear decay over a 730-day (~2yr) window. Per-class scale is
    0.10 for LOOKUP / VAGUE (recency matters most for "what / when" lookups
    and ambiguous queries) and 0.05 for THEMATIC / MULTI_HOP / STEP_BACK
    (older canonical content shouldn't be penalised heavily for synthesis
    queries). Returned value is bounded by ``scale`` so it never overpowers
    the base RRF score.
    """
    if not metadata:
        return 0.0
    ts = metadata.get("timestamp") or (metadata.get("time_span") or {}).get("end")
    if not ts:
        return 0.0
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - dt).days
    if age_days < 0:
        return 0.0
    scale = 0.10 if query_class in (QueryClass.LOOKUP, QueryClass.VAGUE) else 0.05
    return scale * max(0.0, 1.0 - age_days / 730.0)


# Spec 2B.1 / iter-03 plan §3.7: action-verb regex. When a LOOKUP query
# contains an action verb (build, install, set up, deploy, ...), the user is
# almost always looking for executable / step-by-step content. GitHub repos
# and generic web (docs, tutorials) tend to carry that; newsletter/YouTube
# usually carry editorial / discussion content. Small magnitudes — see boost
# table below — so the action-verb signal nudges without overpowering RRF.
_ACTION_VERBS_RE = re.compile(
    r"\b(build|start|open|run|install|set\s+up|spin\s+up|deploy|configure|create|launch|bootstrap|try|use)\b",
    re.IGNORECASE,
)


def _source_type_boost(
    *,
    base_score: float,
    source_type: str,
    query_class,
    question: str,
) -> float:
    """Return ``base_score`` adjusted by source-type / query-class affinities.

    Pure helper — no I/O, never raises. Returns the *new* score (NOT a delta)
    so callers can adopt the result directly. Magnitudes are deliberately small
    (0.02-0.05) so they nudge ordering without overpowering base RRF / title /
    recency signals.

    Affinities applied (cumulative — they can stack on the same candidate):

    1. Class-specific source affinity (legacy T10):
       - THEMATIC / STEP_BACK + youtube  -> +0.03 (long-form discussion content)
       - LOOKUP + reddit                 -> +0.02 (concrete Q&A)

    2. Action-verb affinity (spec 2B.1 / iter-03 plan §3.7) — only when the
       query is LOOKUP-class and contains an action verb (build, install, set
       up, deploy, ...):
       - github / web        -> +0.05  (step-by-step / docs / tutorials)
       - newsletter / youtube -> -0.02  (editorial / discussion, less actionable)
    """
    score = float(base_score)

    st = str(source_type or "").lower()

    # 1. Class-specific source affinity (legacy T10 behavior, preserved).
    qc = query_class
    qc_value = getattr(qc, "value", qc)
    qc_str = str(qc_value or "").lower()
    if qc_str in ("thematic", "step_back") and st == "youtube":
        score += 0.03
    if qc_str == "lookup" and st == "reddit":
        score += 0.02

    # 2. Action-verb affinity (spec 2B.1).
    if qc_str == "lookup" and _ACTION_VERBS_RE.search(question or ""):
        if st in ("github", "web"):
            score += 0.05
        elif st in ("newsletter", "youtube"):
            score -= 0.02

    return score


def _author_match_boost(candidate: RetrievalCandidate, query_meta) -> float:
    """Return a small boost when a query mentions an author/channel that the
    candidate is attributed to.

    Pure helper — no I/O, never raises, never returns negative. The candidate's
    attribution is read from ``metadata['author']`` first, falling back to
    ``metadata['channel']`` for sources (YouTube, podcasts) where the channel
    name is the canonical attribution. Match is a case-insensitive substring
    check in either direction so "karpathy" in the query matches an
    "Andrej Karpathy" attribution. The boost is a single 0.05 — never summed
    across multiple author hits — so it stays bounded and idempotent.
    """
    if candidate is None or not query_meta:
        return 0.0
    authors = getattr(query_meta, "authors", None) or []
    if not authors:
        return 0.0
    md = candidate.metadata or {}
    cand_author = md.get("author") or md.get("channel")
    if not cand_author:
        return 0.0
    cand_lower = str(cand_author).lower()
    for qa in authors:
        if not qa:
            continue
        if str(qa).lower() in cand_lower:
            return 0.05
    return 0.0


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

