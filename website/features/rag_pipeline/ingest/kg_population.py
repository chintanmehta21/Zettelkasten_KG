"""Phase B — KG-population async enrichment hook.

Root cause this fixes (see ``docs/research/phase_b_kg_quality_design.md``):
v2 Add Zettel persists only ``content.*``; the KG node/edge population path
was deleted in the DB-v2 purge and never rebuilt, so new zettels never
connect and the graph is a frozen tag-coincidence topology.

This module is the rebuilt population path. It is invoked fire-and-forget
from ``website.core.persist`` after the canonical zettel is written
(mirroring the rag-chunks ``asyncio.create_task`` pattern). Any failure
inside is logged and swallowed — KG population is best-effort enrichment
and MUST NOT propagate into (and 502) the Add Zettel response.

Pipeline per zettel:
  1. Idempotency gate via ``pipelines.pipeline_runs(kind='kg_extract')`` —
     skip if a 'succeeded' run already exists for this canonical zettel.
  2. Upsert the zettel's ``kg.kg_nodes`` row (+ node embedding stored in
     metadata for cheap candidate-side scoring).
  3. Bounded candidate set: top-K (default 25) most embedding-similar
     EXISTING workspace nodes via ``kg.match_kg_nodes`` (never all-pairs).
  4. Score each candidate with the locked D-KG-1 scorer
     (``kg_features.scoring.compute_connection_strength``) — wired AS-IS.
  5. Upsert a workspace-scoped edge for every candidate scoring
     >= ``EDGE_CREATION_THRESHOLD`` (reused from scoring.py — no new knob),
     writing two-level strength + ``matched_via`` provenance.

Workspace isolation: every read (match RPC ``p_user_id`` = owner profile;
candidate metadata select filtered by ``workspace_id``) and every write
(``upsert_node`` / ``upsert_edge`` forced non-NULL ``workspace_id``) is
fenced to the persisting workspace. A hook for workspace A never reads or
writes workspace B's nodes/edges.
"""

from __future__ import annotations

import logging
import math
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

logger = logging.getLogger("website.features.rag_pipeline.ingest.kg_population")

# Bounded candidate fan-out. NEVER all-pairs — scale-safe on the 1-vCPU /
# 10k+ target. Env-overridable (RAG/KG convention) but defaults to a small
# constant so a misconfig can't explode the per-ingest cost.
_DEFAULT_TOP_K = 25

# D-KG-1 STRUCTURAL signal restore (see docs/research/phase_b_kg_quality_design.md).
# PRIMARY = shared-chunk co-mention overlap (kg.chunk_node_mentions); it is the
# strongest "these two nodes are talked about together" evidence. SECONDARY =
# Adamic-Adar over kg.kg_edges (IDF-weighted common neighbours), a graded
# fallback/booster that is the ONLY structural signal on a cold graph (no shared
# chunks yet) and a light boost when both are present.
#
# Combination feeds the unchanged scorer kernel count/(count+2):
#   effective = shared_chunk_cooccur + _ADAMIC_AA_WEIGHT * adamic_adar   (M5 continuous)
# _ADAMIC_AA_WEIGHT is conservative (0.5) so AA gently nudges the count:
# a strong AA (~2.0 over several rare common neighbours) contributes 1.0
# extra co-mention's worth — keeping shared-chunk overlap dominant whenever
# it is non-zero, while letting AA register on a graph that has edges but
# no shared chunks yet. M5 (Phase 3 / Task 3.4): the combiner is now
# CONTINUOUS — the old `round()` was dropping fractional AA on long-tail
# neighbours; the scorer kernel was extended to accept floats so the raw
# `co + 0.5 * aa` flows straight through.
_ADAMIC_AA_WEIGHT = 0.5

# Hard cap on the structural fan-out queries so per-add cost stays a small
# constant independent of workspace size (D-KG-1 scale guard / index-backed).
_STRUCTURAL_QUERY_LIMIT = 5000

# Hard cap on the Adamic-Adar common-neighbour set whose true degree we
# resolve (Q3 IN-list). Keeps the per-add query cost a small constant even
# for a pathologically dense new node; AA is a secondary signal so a capped
# neighbour set is an acceptable bounded approximation.
_AA_NEIGHBOUR_CAP = 500

# Hard cap on the workspace-node row scan for the metadata-embedding kNN
# fallback (see ``_metadata_embedding_candidates``). The fallback ONLY fires
# when ``kg.match_kg_nodes`` returns nothing (a chunk-mention-less / cold
# workspace), and the scan is one workspace-fenced index-backed SELECT
# returning just ``(id, metadata->embedding)``; the cap keeps the per-node
# cost a small bounded constant even on the 10k+ target.
_METADATA_KNN_SCAN_CAP = 2000


def _top_k() -> int:
    try:
        k = int(os.getenv("KG_POPULATION_TOP_K", str(_DEFAULT_TOP_K)))
    except (TypeError, ValueError):
        return _DEFAULT_TOP_K
    return max(1, min(k, 200))


_NODE_TYPE = "zettel"
_RELATION_TYPE = "co_occurs"  # similarity-derived edge (kg.kg_edge_relation enum)


def _slugify(text: str, *, max_len: int = 96) -> str:
    # M6 (Phase 4 audit): NFKC-normalize first so the same visual title in
    # different Unicode forms (NFD vs NFC, full-width, ligatures) produces
    # the same slug — otherwise NFD ``e`` + combining acute is lowered to
    # ``e`` + non-alnum combining mark, which the loop below collapses to
    # ``e-``, breaking the kg.kg_nodes.slug stability invariant.
    import unicodedata  # noqa: PLC0415 - localised import to keep top lean
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip().lower()
    out = []
    prev_dash = False
    for ch in normalized:
        if ch.isalnum():
            out.append(ch)
            prev_dash = False
        elif not prev_dash:
            out.append("-")
            prev_dash = True
    slug = "".join(out).strip("-")[:max_len].strip("-")
    return slug or "zettel"


def _node_metadata(
    *,
    canonical_zettel_id: UUID,
    embedding: list[float],
    tags: list[str],
    created_at_iso: str,
) -> dict:
    """Compact per-node scoring inputs.

    Stored on ``kg.kg_nodes.metadata`` so candidate-side D-KG-1 scoring
    needs ONE batched select (no deep chunk→zettel→workspace join per
    candidate). Bounded: embedding is 768 floats, tags are deduped.
    """
    return {
        "canonical_zettel_id": str(canonical_zettel_id),
        "embedding": list(embedding) if embedding else [],
        "tags": sorted({str(t).strip() for t in tags if str(t).strip()}),
        "created_at": created_at_iso,
    }


def _temporal_days(a_iso: str | None, b_iso: str | None) -> float:
    if not a_iso or not b_iso:
        return 0.0
    try:
        a = datetime.fromisoformat(a_iso.replace("Z", "+00:00"))
        b = datetime.fromisoformat(b_iso.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return abs((a - b).total_seconds()) / 86400.0


def _shared_chunk_cooccurrence(
    *,
    new_node_id: int,
    candidate_ids: list[int],
    supabase_client,
) -> dict[int, int]:
    """PRIMARY structural signal: distinct shared canonical chunks.

    ONE bounded, index-backed query over kg.chunk_node_mentions
    (supabase/website/_v2/03_kg_schema.sql:48-58, idx_chunk_node_mentions_node)
    for the new node ∪ its ≤K candidates (≤26 ids). Mirrors the exact
    ``.in_("kg_node_id", ids)`` pattern in
    kg_repository.py:145-196 (list_node_zettel_mapping).

    Returns ``{candidate_id: shared_chunk_count}``. Workspace isolation: the
    table has no workspace column, but every id passed in is already
    workspace-fenced (the new node is upserted into THIS workspace; candidates
    are filtered to this workspace's kg_nodes upstream), so no cross-tenant
    chunk can enter the set.
    """
    ids = list({int(new_node_id), *[int(c) for c in candidate_ids]})
    if len(ids) <= 1:
        return {}
    resp = (
        supabase_client.schema("kg")
        .table("chunk_node_mentions")
        .select("kg_node_id,canonical_chunk_id")
        .in_("kg_node_id", ids)
        .limit(_STRUCTURAL_QUERY_LIMIT)
        .execute()
    )
    node_chunks: dict[int, set[str]] = {}
    for row in resp.data or []:
        try:
            nid = int(row["kg_node_id"])
        except (TypeError, ValueError, KeyError):
            continue
        cid = row.get("canonical_chunk_id")
        if cid is None:
            continue
        node_chunks.setdefault(nid, set()).add(str(cid))
    new_chunks = node_chunks.get(int(new_node_id), set())
    if not new_chunks:
        return {}
    out: dict[int, int] = {}
    for cand in candidate_ids:
        inter = len(new_chunks & node_chunks.get(int(cand), set()))
        if inter > 0:
            out[int(cand)] = inter
    return out


def _adamic_adar(
    *,
    new_node_id: int,
    candidate_ids: list[int],
    workspace_id: UUID,
    supabase_client,
) -> dict[int, float]:
    """SECONDARY structural signal: Adamic-Adar over kg.kg_edges.

    AA(u,v) = Σ_{w ∈ N(u) ∩ N(v)} 1/log(deg(w)), guarding deg(w) <= 1 (log
    domain / divide-by-zero). Bounded & workspace-scoped, a small CONSTANT
    number of index-backed selects (all on idx_kg_edges_workspace_src / _dst,
    all .limit()-capped, all fenced to ``workspace_id``):

      Q1+Q2: edges where a seed (new node ∪ candidates) is src / dst — gives
             N(new) and N(cand) for the candidate set (2 selects).
      Q3:    a src + dst select pair over the *common-neighbour* set only —
             gives the TRUE degree of each w (2 selects, skipped entirely
             when there is no common neighbour). Seed-incident edges alone
             undercount deg(w) (only w's edges that touch a seed are
             visible), which would inflate 1/log(deg) and wrongly trip the
             deg<=1 guard. The common-neighbour set is bounded by deg(new)
             and hard-capped at ``_AA_NEIGHBOUR_CAP``; Q3 is NOT a
             per-neighbour fan-out, NO recursion, NO all-pairs.

    Total: 4 selects (2 when no common neighbour), candidate-count-indep.

    Cold graph (no edges) → ``{}`` (0 contribution).
    """
    seeds = list({int(new_node_id), *[int(c) for c in candidate_ids]})
    if len(seeds) <= 1:
        return {}
    ws = str(workspace_id)

    # Two bounded selects: edges where a seed is the src, and where it is the
    # dst. Both hit the (workspace_key, src/dst) composite indexes.
    edges: list[tuple[int, int]] = []
    for col in ("src_node_id", "dst_node_id"):
        resp = (
            supabase_client.schema("kg")
            .table("kg_edges")
            .select("src_node_id,dst_node_id")
            .eq("workspace_id", ws)
            .in_(col, seeds)
            .limit(_STRUCTURAL_QUERY_LIMIT)
            .execute()
        )
        for row in resp.data or []:
            try:
                s = int(row["src_node_id"])
                d = int(row["dst_node_id"])
            except (TypeError, ValueError, KeyError):
                continue
            if s == d:
                continue
            edges.append((s, d))

    if not edges:
        return {}

    # Undirected adjacency over the bounded incident-edge set.
    adj: dict[int, set[int]] = {}
    for s, d in edges:
        adj.setdefault(s, set()).add(d)
        adj.setdefault(d, set()).add(s)

    new_neighbors = adj.get(int(new_node_id), set())
    if not new_neighbors:
        return {}

    # Union of all common neighbours across candidates (deduped, capped).
    common_by_cand: dict[int, set[int]] = {}
    all_common: set[int] = set()
    for cand in candidate_ids:
        cid = int(cand)
        common = new_neighbors & adj.get(cid, set())
        if common:
            common_by_cand[cid] = common
            all_common |= common
    if not all_common:
        return {}
    # Hard-cap the neighbour fan-out so Q3's IN-list stays a small constant
    # even for a pathologically dense new node (scale guard).
    capped_common = set(sorted(all_common)[:_AA_NEIGHBOUR_CAP])

    # Q3: true degree of each common neighbour — one bounded select over
    # edges incident to the (capped) common-neighbour set, workspace-fenced.
    deg: dict[int, int] = {}
    nbr_adj: dict[int, set[int]] = {}
    common_seeds = list(capped_common)
    for col in ("src_node_id", "dst_node_id"):
        resp = (
            supabase_client.schema("kg")
            .table("kg_edges")
            .select("src_node_id,dst_node_id")
            .eq("workspace_id", ws)
            .in_(col, common_seeds)
            .limit(_STRUCTURAL_QUERY_LIMIT)
            .execute()
        )
        for row in resp.data or []:
            try:
                s = int(row["src_node_id"])
                d = int(row["dst_node_id"])
            except (TypeError, ValueError, KeyError):
                continue
            if s == d:
                continue
            nbr_adj.setdefault(s, set()).add(d)
            nbr_adj.setdefault(d, set()).add(s)
    for w in capped_common:
        deg[w] = len(nbr_adj.get(w, set()))

    out: dict[int, float] = {}
    for cid, common in common_by_cand.items():
        score = 0.0
        for w in common:
            if w not in capped_common:
                continue
            dw = deg.get(w, 0)
            if dw <= 1:  # log(1)=0 → undefined IDF weight; skip
                continue
            score += 1.0 / math.log(dw)
        if score > 0.0:
            out[cid] = score
    return out


def _structural_map(
    *,
    new_key: str,
    new_node_id: int,
    candidates: list[dict],
    cand_meta: dict[int, dict],
    workspace_id: UUID,
    supabase_client,
) -> tuple[dict[str, dict[str, int]], dict[int, tuple[int, float]]]:
    """Build the D-KG-1 ``structural`` arg + per-candidate audit sub-values.

    Returns ``(structural, sub)`` where ``structural`` is the scorer-shaped
    ``{node_key: {neighbor_key: effective_count}}`` (symmetric) and ``sub`` is
    ``{cand_id: (shared_chunk_cooccur, adamic_adar)}`` for matched_via.

    Combination: ``effective = cooccur + _ADAMIC_AA_WEIGHT * aa`` (M5 continuous).
    Shared-chunk co-mention is PRIMARY (dominant whenever non-zero); AA is the
    graded fallback that carries the cold/no-shared-chunk case and lightly
    boosts when both fire. Any failure → empty (caller falls back to
    structural=None == today's behaviour). NEVER raises.
    """
    cand_ids = [int(c["node_id"]) for c in candidates if int(c["node_id"]) in cand_meta]
    if not cand_ids:
        return {}, {}
    try:
        cooccur = _shared_chunk_cooccurrence(
            new_node_id=new_node_id,
            candidate_ids=cand_ids,
            supabase_client=supabase_client,
        )
        aa = _adamic_adar(
            new_node_id=new_node_id,
            candidate_ids=cand_ids,
            workspace_id=workspace_id,
            supabase_client=supabase_client,
        )
    except Exception as exc:  # fire-and-forget: degrade, never raise
        logger.warning("kg-populate structural signal failed (degrading): %s", exc)
        return {}, {}

    structural: dict[str, dict[str, int]] = {}
    sub: dict[int, tuple[int, float]] = {}
    for cid in cand_ids:
        co = int(cooccur.get(cid, 0))
        a = float(aa.get(cid, 0.0))
        # M5: continuous AA — never rounds away small fractional contributions.
        # The scorer kernel `count/(count+2)` now accepts floats, so we can
        # feed the raw `co + 0.5 * aa` directly.
        effective = co + _ADAMIC_AA_WEIGHT * a
        sub[cid] = (co, a)
        if effective <= 0:
            continue
        cand_key = f"c{cid}"
        structural.setdefault(new_key, {})[cand_key] = effective
        structural.setdefault(cand_key, {})[new_key] = effective
    return structural, sub


def score_edge(
    *,
    a_key: str,
    a_embedding: list[float],
    a_tags: list[str],
    a_created_at_iso: str | None,
    b_key: str,
    b_embedding: list[float],
    b_tags: list[str],
    b_created_at_iso: str | None,
    structural_arg: dict | None,
    structural_sub: tuple[int, float],
    rpc_score: float | None = None,
) -> tuple[float, dict]:
    """Pure D-KG-1 scoring for ONE node pair + its ``matched_via`` provenance.

    Single source of truth shared by the live KG-population hook
    (``populate_kg_for_zettel``) and the one-shot strength backfill
    (``ops/scripts/backfill_kg_edge_strength.py``) so the two paths can
    never diverge. Pure / deterministic: no DB, no network — the caller
    supplies the already-gathered signals (embeddings, tags, timestamps,
    and the prebuilt structural arg/sub from ``_structural_map``).

    ``structural_sub`` is ``(shared_chunk_cooccur, adamic_adar)`` for the
    (a,b) pair (the same tuple ``_structural_map`` returns per candidate).
    ``rpc_score`` is the optional ``kg.match_kg_nodes`` cosine fallback used
    only when one side has no stored embedding (live hook path); the
    backfill path leaves it ``None`` and relies on stored vectors.

    Returns ``(strength, matched_via)`` — byte-identical to the block the
    hook previously inlined, so wiring it in does not change live behaviour.
    """
    from website.features.kg_features import scoring as _sc
    from website.features.kg_features.scoring import compute_connection_strength

    embeddings_map = {a_key: a_embedding, b_key: b_embedding}
    tags_map = {a_key: a_tags, b_key: b_tags}
    tdays = _temporal_days(a_created_at_iso, b_created_at_iso)

    strength = compute_connection_strength(
        a_key,
        b_key,
        embeddings=embeddings_map,
        tags=tags_map,
        structural=structural_arg,
        temporal_days=tdays,
    )

    emb_sub = _sc._cosine_similarity(a_embedding, b_embedding)
    if (not a_embedding or not b_embedding) and rpc_score is not None:
        emb_sub = float(rpc_score)
    struct_co, struct_aa = structural_sub
    struct_squashed = _sc._structural_signal(a_key, b_key, structural_arg or {})
    matched_via = {
        "embedding": round(emb_sub, 4),
        # M3: _jaccard returns None for asymmetric-empty (signal-absent).
        # Surface as null in matched_via so the metric is distinguishable
        # from a true 0.0 (both sides empty / disjoint).
        "tag": (
            round(_sc._jaccard(a_tags, b_tags), 4)
            if _sc._jaccard(a_tags, b_tags) is not None
            else None
        ),
        "structural": round(struct_squashed, 4),
        "structural_shared_chunks": int(struct_co),
        "structural_adamic_adar": round(float(struct_aa), 4),
        "temporal": round(_sc._temporal_signal(tdays), 4),
        "composite": round(strength, 4),
    }
    return strength, matched_via


def _metadata_embedding_candidates(
    *,
    workspace_id: UUID,
    node_id: int,
    node_embedding: list[float],
    k: int,
    supabase_client,
) -> list[dict]:
    """Workspace-fenced node↔node kNN over ``kg.kg_nodes.metadata.embedding``.

    Fallback candidate selector used ONLY when ``kg.match_kg_nodes`` returns
    nothing. That RPC scores similarity off ``content.canonical_chunks``
    reached via ``kg.chunk_node_mentions``; a workspace whose nodes were
    upserted WITHOUT chunk mentions (or whose chunks have NULL embeddings —
    observed live for Naruto: 0 chunk_node_mentions, 19 chunks all
    embedding-NULL) therefore has NO discoverable peers via the RPC even
    though every node carries a valid 768-d ``metadata.embedding``. This
    fallback closes that gap by computing cosine directly over the stored
    node-metadata vectors, so the D-KG-1 edge-create path produces edges on
    a chunk-mention-less / cold workspace exactly as it does on a normal one.

    Returns the same shape ``find_similar_nodes`` returns —
    ``[{"node_id": int, "score": float in [0,1]}]`` sorted by descending
    cosine — so the caller is unchanged. Workspace isolation: the SELECT is
    fenced to ``workspace_id`` (a peer from another tenant can never appear);
    the row scan is hard-capped (``_METADATA_KNN_SCAN_CAP``) so the per-node
    cost stays a bounded constant on the 10k+ target. Never raises — any
    failure degrades to ``[]`` (== today's behaviour, no edges) so the
    fire-and-forget hook stays a no-op on failure.
    """
    if not node_embedding:
        return []
    try:
        import math as _math

        resp = (
            supabase_client.schema("kg")
            .table("kg_nodes")
            .select("id,metadata")
            .eq("workspace_id", str(workspace_id))
            .limit(_METADATA_KNN_SCAN_CAP)
            .execute()
        )
        rows = list(resp.data or [])
    except Exception as exc:
        logger.warning(
            "kg-populate metadata-knn fallback select failed (degrading): %s",
            exc,
        )
        return []

    qa = [float(x) for x in node_embedding]
    na = _math.sqrt(sum(v * v for v in qa))
    if na <= 0.0:
        return []

    scored: list[tuple[float, int]] = []
    for r in rows:
        try:
            rid = int(r["id"])
        except (TypeError, ValueError, KeyError):
            continue
        if rid == int(node_id):
            continue
        meta = r.get("metadata") or {}
        emb = meta.get("embedding") or []
        if not emb or len(emb) != len(qa):
            continue
        try:
            vb = [float(x) for x in emb]
        except (TypeError, ValueError):
            continue
        nb = _math.sqrt(sum(v * v for v in vb))
        if nb <= 0.0:
            continue
        dot = sum(a * b for a, b in zip(qa, vb))
        cos = dot / (na * nb)
        # B3: clamp raw cosine to [0,1] (no (cos+1)/2 rescale) so this
        # matches scoring._cosine_similarity's domain — it can become the
        # emb_sub signal via the rpc_score fallback when raw vectors are
        # absent, so the two cosine sites must move together.
        score = max(0.0, min(1.0, cos))
        scored.append((score, rid))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [{"node_id": rid, "score": s} for s, rid in scored[:k]]


# B2: mention-row write tuning. The PRIMARY structural signal + B1's primary
# render path both key off kg.chunk_node_mentions. NO production path wrote
# these rows (only the offline backfill), so Naruto had 58 kg_edges / 20
# kg_nodes / 0 mentions → B1 dropped every edge AND shared-chunk co-occurrence
# was dead 0/58. This hook now links the zettel's kg_node to every
# content.canonical_chunk of that zettel.
#
# mention_type='derived': the link is derived from the persisted chunking of
# the zettel (not entity-extracted/'extracted', not user-'tagged', not
# 'authored') — within the 03_kg_schema.sql CHECK set.
_MENTION_TYPE = "derived"
# Bounded read cap on a single zettel's chunk fan-out (post the parallel
# multi-chunk persist fix a zettel has many chunks; still a small constant
# per ingest, index-backed via idx_canonical_chunks_zettel).
_MENTION_CHUNK_LIMIT = 2000


def _write_chunk_node_mentions(
    *,
    node_id: int,
    canonical_zettel_id: UUID,
    supabase_client,
) -> int:
    """B2: link a zettel's kg_node to its content.canonical_chunks.

    Reads the chunk ids for ``canonical_zettel_id`` (bounded, index-backed
    via idx_canonical_chunks_zettel) and idempotently upserts one
    kg.chunk_node_mentions row per chunk
    (PK = canonical_chunk_id, kg_node_id, mention_type — re-ingest is a
    no-op, never duplicates). Workspace/profile scoping is implicit and
    safe: ``node_id`` was just upserted into THIS workspace and the chunk
    ids belong to THIS canonical zettel only — no other tenant's chunk or
    node can enter the set. Returns the number of mention rows written.

    Fire-and-forget-safe: any failure is logged and swallowed (returns 0);
    it MUST NOT raise into the kg-populate hook (best-effort enrichment).
    """
    try:
        resp = (
            supabase_client.schema("content")
            .table("canonical_chunks")
            .select("id")
            .eq("canonical_zettel_id", str(canonical_zettel_id))
            .limit(_MENTION_CHUNK_LIMIT)
            .execute()
        )
        chunk_ids: list[str] = []
        for row in resp.data or []:
            cid = row.get("id")
            if cid is not None:
                chunk_ids.append(str(cid))
        if not chunk_ids:
            return 0
        # Dedupe chunk ids defensively; one row per (chunk, node, type).
        rows = [
            {
                "canonical_chunk_id": cid,
                "kg_node_id": int(node_id),
                "mention_type": _MENTION_TYPE,
                "score": None,
                "metadata": {},
            }
            for cid in dict.fromkeys(chunk_ids)
        ]
        (
            supabase_client.schema("kg")
            .table("chunk_node_mentions")
            .upsert(
                rows,
                on_conflict="canonical_chunk_id,kg_node_id,mention_type",
            )
            .execute()
        )
        return len(rows)
    except Exception as exc:  # fire-and-forget: log + skip, never raise
        logger.warning(
            "kg-populate chunk_node_mentions write failed zettel=%s node=%s "
            "(degrading, edges/node already persisted): %s",
            canonical_zettel_id,
            node_id,
            exc,
        )
        return 0


def _score_and_upsert_edges_for_node(
    *,
    workspace_id: UUID,
    profile_id: UUID,
    node_id: int,
    node_embedding: list[float],
    node_tags: list[str],
    node_created_at_iso: str,
    supabase_client,
    metrics: dict,
    evidence_canonical_zettel_id: UUID | None,
) -> dict:
    """Bounded candidate selection + D-KG-1 scoring + edge upsert for ONE node.

    SINGLE SOURCE OF TRUTH for steps 3b-5 of the live ingest hook. Both the
    fire-and-forget hook (``populate_kg_for_zettel``) and the one-shot
    existing-node backfill (``populate_kg_edges_for_existing_node``) call
    THIS function so the two paths can never diverge. Synchronous (callers
    wrap it in ``asyncio.to_thread`` exactly as the prior inlined block was
    wrapped at each Supabase round-trip — net behaviour byte-identical to the
    pre-refactor hook body).

    Workspace isolation: ``find_similar_nodes`` is keyed off the owner
    ``profile_id`` (its workspace fence); the candidate-metadata SELECT and
    every structural query are fenced to ``workspace_id``; ``upsert_edge``
    forces a non-NULL ``workspace_id``. Mutates + returns ``metrics``.
    """
    from website.core.supabase_v2.repositories.kg_repository import KGRepository
    from website.features.kg_features.embeddings import find_similar_nodes
    from website.features.kg_features.scoring import EDGE_CREATION_THRESHOLD

    kg = KGRepository(supabase_client)

    k = _top_k()
    candidates = find_similar_nodes(
        supabase_client,
        str(profile_id),  # match_kg_nodes resolves owner -> workspaces
        node_embedding,
        0.0,  # collect K nearest; D-KG-1 owns the create cutoff
        k,
    )
    # Drop the node itself + hard-cap at K (defensive — the RPC already
    # LIMITs, but never score more than K candidates).
    candidates = [
        c for c in candidates if int(c.get("node_id", -1)) != node_id
    ][:k]

    # FALLBACK: ``kg.match_kg_nodes`` scores similarity off
    # ``content.canonical_chunks`` via ``kg.chunk_node_mentions``. A
    # workspace whose nodes were upserted WITHOUT chunk mentions (or whose
    # chunks have NULL embeddings) yields ZERO RPC candidates even though
    # every node has a valid ``metadata.embedding`` (observed live: Naruto
    # ws fc336067…, 10 nodes, 0 chunk_node_mentions → 0 edges). When the RPC
    # finds nothing, discover peers by node↔node cosine over the stored
    # node-metadata vectors instead. Workspace-fenced + bounded; the live
    # hook's primary RPC path/contract is untouched (this only runs when the
    # RPC returned nothing, so a chunk-backed workspace behaves exactly as
    # before).
    if not candidates:
        candidates = _metadata_embedding_candidates(
            workspace_id=workspace_id,
            node_id=node_id,
            node_embedding=node_embedding,
            k=k,
            supabase_client=supabase_client,
        )

    metrics["candidates"] = len(candidates)

    if not candidates:
        return metrics

    # Batch-load candidate scoring inputs from kg_nodes.metadata, fenced to
    # THIS workspace (tenant isolation: never reads workspace B).
    cand_ids = [int(c["node_id"]) for c in candidates]
    meta_resp = (
        supabase_client.schema("kg")
        .table("kg_nodes")
        .select("id,metadata")
        .eq("workspace_id", str(workspace_id))
        .in_("id", cand_ids)
        .execute()
    )
    cand_meta = {
        int(r["id"]): (r.get("metadata") or {})
        for r in (meta_resp.data or [])
    }

    new_key = "new"

    # STRUCTURAL signal (D-KG-1 slot). Computed ONCE over the whole candidate
    # set (bounded constant query count, NOT per-candidate). Failure degrades
    # to None == pre-restore behaviour; never raises.
    structural_map, structural_sub = _structural_map(
        new_key=new_key,
        new_node_id=node_id,
        candidates=candidates,
        cand_meta=cand_meta,
        workspace_id=workspace_id,
        supabase_client=supabase_client,
    )
    structural_arg = structural_map or None

    for cand in candidates:
        cid = int(cand["node_id"])
        cmeta = cand_meta.get(cid)
        if cmeta is None:
            # Candidate not in this workspace's kg_nodes -> isolation
            # guard; skip (never cross-tenant).
            continue
        cand_key = f"c{cid}"

        # D-KG-1 inputs. Embedding signal: prefer the RPC cosine score
        # (already [0,1], free), fall back to stored vectors.
        rpc_score = cand.get("score")
        cand_embedding = list(cmeta.get("embedding") or [])

        strength, matched_via = score_edge(
            a_key=new_key,
            a_embedding=node_embedding,
            a_tags=node_tags,
            a_created_at_iso=node_created_at_iso,
            b_key=cand_key,
            b_embedding=cand_embedding,
            b_tags=list(cmeta.get("tags") or []),
            b_created_at_iso=cmeta.get("created_at"),
            structural_arg=structural_arg,  # shared-chunk + Adamic-Adar
            structural_sub=structural_sub.get(cid, (0, 0.0)),
            rpc_score=rpc_score,
        )
        metrics["scored"] += 1

        if strength < EDGE_CREATION_THRESHOLD:
            continue

        kg.upsert_edge(
            workspace_id=workspace_id,
            src_node_id=node_id,
            dst_node_id=cid,
            relation_type=_RELATION_TYPE,
            connection_strength=round(strength, 3),
            # workspace_strength = D-KG-1 over WORKSPACE-scoped data
            # (candidates come from the owner's workspaces only).
            workspace_strength=round(strength, 3),
            # global_strength left NULL: cross-workspace scoring would need
            # an expensive all-tenant scan; design says NULL is acceptable
            # (stored-for-future, never rendered).
            global_strength=None,
            matched_via=matched_via,
            evidence_canonical_zettel_id=evidence_canonical_zettel_id,
        )
        metrics["edges"] += 1

    return metrics


async def populate_kg_for_zettel(
    *,
    workspace_id: UUID,
    profile_id: UUID,
    canonical_zettel_id: UUID,
    title: str,
    summary: str,
    tags: list[str],
    url: str | None,
    source_type: str | None,
    supabase_client,
    metadata: dict | None = None,
) -> dict:
    """Populate kg nodes/edges for one freshly-persisted zettel.

    Returns a small metrics dict (also written to the pipeline run). Never
    raises — every failure path logs and returns a metrics dict with an
    ``error`` key so the fire-and-forget caller stays a no-op on failure.
    """
    import asyncio
    import time as _time

    from website.core.supabase_v2.repositories.kg_repository import KGRepository
    from website.core.supabase_v2.repositories.pipelines_repository import (
        PipelinesRepository,
    )
    from website.features.kg_features.embeddings import (
        EmbeddingFailureReason,
        generate_embedding_typed,
    )
    from website.features.kg_features.pseudo_tags import derive_pseudo_tags

    metrics: dict = {"candidates": 0, "scored": 0, "edges": 0, "skipped": False}

    pipelines = PipelinesRepository(supabase_client)
    kg = KGRepository(supabase_client)

    # T4.6: wall-time histogram observed at every return path. Best-effort.
    _t0 = _time.perf_counter()

    def _observe_duration() -> None:
        try:
            from website.core.kg_metrics import kg_populate_duration_seconds
            kg_populate_duration_seconds.observe(_time.perf_counter() - _t0)
        except Exception:  # noqa: BLE001 — metrics best-effort, never fatal.
            pass

    # ---- 1. Idempotency gate -------------------------------------------
    try:
        if await asyncio.to_thread(
            pipelines.has_succeeded_run,
            workspace_id=workspace_id,
            kind="kg_extract",
            canonical_zettel_id=canonical_zettel_id,
        ):
            logger.info(
                "kg-populate skip (succeeded run exists) zettel=%s", canonical_zettel_id
            )
            metrics["skipped"] = True
            # M1 (Phase 4 audit): idempotency-skip is a TERMINAL outcome — emit
            # it on the same counter as the LD-8 states so dashboards aren't
            # under-counting re-ingests.
            try:
                from website.core.kg_metrics import kg_populate_runs_total
                kg_populate_runs_total.labels(outcome="skipped_idempotent").inc()
            except Exception:  # noqa: BLE001 — metrics best-effort, never fatal.
                pass
            _observe_duration()
            return metrics
        run_id = await asyncio.to_thread(
            pipelines.start_run,
            workspace_id=workspace_id,
            kind="kg_extract",
            canonical_zettel_id=canonical_zettel_id,
        )
    except Exception as exc:
        logger.warning("kg-populate idempotency gate failed: %s", exc)
        metrics["error"] = "idempotency_gate_failed"
        _observe_duration()
        return metrics

    try:
        # ---- 2. Pseudo-tags (augment, never override user tags) --------
        user_tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
        pseudo = derive_pseudo_tags(
            url=url, source_type=source_type, metadata=metadata
        )
        # User tags first; pseudo-tags appended (augment), deduped.
        augmented_tags = list(dict.fromkeys([*user_tags, *pseudo]))

        created_at_iso = datetime.now(timezone.utc).isoformat()
        embed_input = f"{title}\n\n{summary}".strip()[:2000]
        # LD-8: typed embedding so the kg-populate state machine can pick the
        # right pipeline_runs terminal state (retryable rate-limit vs terminal
        # empty-input). Empty embedding does NOT abort — node upsert + mention
        # writes still happen so the structural signal lands even when cosine
        # is unavailable. Retry classification is recorded on the run row.
        embed_result = await asyncio.to_thread(
            generate_embedding_typed, embed_input
        )
        node_embedding = embed_result.vectors[0] if embed_result.ok else []
        if not embed_result.ok:
            metrics["embedding_failure_reason"] = (
                embed_result.reason.value if embed_result.reason else "unknown"
            )

        # ---- 3. Upsert this zettel's kg node --------------------------
        node_id = await asyncio.to_thread(
            lambda: kg.upsert_node(
                workspace_id=workspace_id,
                node_type=_NODE_TYPE,
                canonical_name=title.strip() or str(canonical_zettel_id),
                slug=_slugify(title or str(canonical_zettel_id)),
                metadata=_node_metadata(
                    canonical_zettel_id=canonical_zettel_id,
                    embedding=node_embedding,
                    tags=augmented_tags,
                    created_at_iso=created_at_iso,
                ),
            )
        )

        # ---- 3b. B2: link this node to the zettel's canonical chunks ----
        # Writes kg.chunk_node_mentions so (a) /api/graph's PRIMARY edge-
        # endpoint resolution works for this zettel going forward and (b)
        # the PRIMARY structural signal (shared-chunk co-occurrence) is fed
        # for future ingests. Best-effort: never raises, runs regardless of
        # whether an embedding exists (mentions are edge-independent).
        mentions_written = await asyncio.to_thread(
            _write_chunk_node_mentions,
            node_id=node_id,
            canonical_zettel_id=canonical_zettel_id,
            supabase_client=supabase_client,
        )
        metrics["chunk_mentions"] = mentions_written

        # ---- 4. Bounded candidate set (top-K similar workspace nodes) --
        if not node_embedding:
            logger.info(
                "kg-populate no embedding; node upserted, no edges zettel=%s",
                canonical_zettel_id,
            )
            # LD-8: classify the no-embedding outcome by upstream reason.
            #   EMPTY_INPUT → succeeded_empty (clean run, no candidates).
            #     The summary was empty/whitespace; replaying won't help.
            #     24h retry window matches the "user might edit the zettel" path.
            #   RATE_LIMIT / NETWORK / RPC_ERROR → failed_retryable (1h backoff;
            #     quota likely recovers within the hour).
            #   EMPTY_VECTOR → failed_retryable (provider returned [] — treat
            #     as transient).
            now_utc = datetime.now(timezone.utc)
            if embed_result.reason == EmbeddingFailureReason.EMPTY_INPUT:
                state = "succeeded_empty"
                retry_after = now_utc + timedelta(hours=24)
                error_msg = None
            else:
                state = "failed_retryable"
                retry_after = now_utc + timedelta(hours=1)
                error_msg = metrics.get("embedding_failure_reason") or "no_embedding"
            await asyncio.to_thread(
                pipelines.finish_run_with_state,
                run_id=run_id,
                state=state,
                metrics=metrics,
                error=error_msg,
                retry_eligible_after=retry_after,
            )
            _observe_duration()
            return metrics

        # ---- 4+5. Bounded candidate scoring + edge upsert -------------
        # Delegated to the shared synchronous core (single source of truth
        # with the existing-node backfill, so the two paths can never
        # diverge). One to_thread around the whole bounded-constant
        # sequence preserves the prior "never block the loop on Supabase
        # I/O" contract; the produced metrics / candidate cap / isolation /
        # threshold gating / edge payloads are byte-identical to the block
        # this previously inlined (proven by this module's unit suite).
        await asyncio.to_thread(
            _score_and_upsert_edges_for_node,
            workspace_id=workspace_id,
            profile_id=profile_id,
            node_id=node_id,
            node_embedding=node_embedding,
            node_tags=augmented_tags,
            node_created_at_iso=created_at_iso,
            supabase_client=supabase_client,
            metrics=metrics,
            evidence_canonical_zettel_id=canonical_zettel_id,
        )

        # LD-8: edges > 0 is a truly-terminal success; edges == 0 on a
        # clean run is "succeeded_empty" — retryable after 24h so candidate
        # availability can recover (newly-ingested neighbours, scorer-cache
        # warmth, etc.). Both are valid terminal states, but only `succeeded`
        # blocks future retries in `has_succeeded_run`.
        edge_count = int(metrics.get("edges", 0) or 0)
        if edge_count > 0:
            await asyncio.to_thread(
                pipelines.finish_run_with_state,
                run_id=run_id,
                state="succeeded",
                metrics=metrics,
            )
        else:
            await asyncio.to_thread(
                pipelines.finish_run_with_state,
                run_id=run_id,
                state="succeeded_empty",
                metrics=metrics,
                retry_eligible_after=datetime.now(timezone.utc) + timedelta(hours=24),
            )
        logger.info(
            "kg-populate done zettel=%s node=%s candidates=%d edges=%d",
            canonical_zettel_id,
            node_id,
            metrics["candidates"],
            metrics["edges"],
        )
        _observe_duration()
        return metrics
    except Exception as exc:
        logger.warning(
            "kg-populate failed zettel=%s: %s", canonical_zettel_id, exc
        )
        metrics["error"] = type(exc).__name__
        # LD-8: most kg-populate exceptions are transient (rate limit, RPC,
        # network), so default to failed_retryable with 1h backoff. The
        # retry-sweep will replay these. Truly-permanent failures (corrupt
        # input, schema violations) need explicit classification — out of
        # scope for Phase 3; Phase 4 may add a typed exception hierarchy.
        try:
            await asyncio.to_thread(
                pipelines.finish_run_with_state,
                run_id=run_id,
                state="failed_retryable",
                metrics=metrics,
                error=str(exc),
                retry_eligible_after=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        except Exception as fin_exc:  # pragma: no cover - best effort
            logger.warning("kg-populate run finalize failed: %s", fin_exc)
        _observe_duration()
        return metrics


def populate_kg_edges_for_existing_node(
    *,
    workspace_id: UUID,
    profile_id: UUID,
    kg_node_id: int,
    supabase_client,
) -> dict:
    """Create the missing edges for ONE already-existing kg node.

    Why this exists (operator-reported, verified live): the create_kasten
    CLI used to cancel the fire-and-forget ``populate_kg_for_zettel`` task at
    loop teardown, so ~10 Naruto kg_nodes were upserted but their candidate
    scoring / edge-upsert step never ran (10 kg_nodes, 0 kg_edges). The
    teardown race is fixed for FUTURE ingests (persist drain), but re-ingest
    is idempotent (``pipelines.pipeline_runs(kind='kg_extract')`` dedup), so
    those existing nodes stay edgeless forever. This entrypoint runs the
    EXACT same scoring+upsert core the live hook runs, but seeded from an
    existing node id instead of a freshly-persisted zettel.

    Synchronous (the one-shot backfill is a sync script) and pure-delegating:
    it reuses ``_score_and_upsert_edges_for_node`` — the SAME shared core the
    live hook calls — so the backfill and the hook can never diverge.

    Cold node: existing nodes may have been upserted with an empty embedding
    (``metadata.embedding == []``). kNN candidate selection needs a vector,
    so we regenerate it from the node's stored title/tags (``canonical_name``
    + ``metadata.tags``) and persist it back into ``metadata`` (best-effort)
    so future passes / the live hook reuse it. If embedding generation is
    unavailable (rate-limit / quota / network → empty list), the node is
    skipped gracefully with ``metrics['skipped']=True`` — never crashes the
    batch.

    Workspace isolation: the node-metadata SELECT is fenced to
    ``workspace_id`` (a node id from another tenant resolves to nothing →
    treated as missing/skip); every downstream query/write in the shared
    core is workspace-fenced. Returns a metrics dict
    (``{candidates, scored, edges, skipped}`` + optional ``error``); never
    raises (per-node isolation is the caller's contract, but we also guard
    here so one bad node cannot abort the batch).
    """
    from website.features.kg_features.embeddings import generate_embedding_typed

    metrics: dict = {
        "candidates": 0,
        "scored": 0,
        "edges": 0,
        "skipped": False,
    }
    try:
        # ---- Load this existing node's scoring inputs, ws-fenced --------
        resp = (
            supabase_client.schema("kg")
            .table("kg_nodes")
            .select("id,canonical_name,metadata,created_at")
            .eq("workspace_id", str(workspace_id))
            .eq("id", int(kg_node_id))
            .limit(1)
            .execute()
        )
        rows = list(resp.data or [])
        if not rows:
            # Not in this workspace (or gone) -> isolation guard; skip.
            logger.info(
                "kg-backfill node id=%s not in workspace %s; skipping",
                kg_node_id,
                workspace_id,
            )
            metrics["skipped"] = True
            return metrics

        row = rows[0]
        meta = dict(row.get("metadata") or {})
        node_tags = [
            str(t).strip()
            for t in (meta.get("tags") or [])
            if str(t).strip()
        ]
        # Prefer metadata.created_at (what the hook stores); fall back to
        # the row's created_at so temporal still has a signal.
        node_created_at_iso = meta.get("created_at") or row.get("created_at")

        node_embedding = list(meta.get("embedding") or [])
        if not node_embedding:
            # X8 (Phase 4 / Task 4.5): regenerate using the LIVE-INGEST embed
            # shape (`"title\n\nsummary"`) so cosines are comparable across the
            # corpus. Fetch the canonical zettel's ai_summary first; degrade
            # gracefully to title-only with a clear meta marker.
            canonical_name = str(row.get("canonical_name") or "").strip()
            summary_text = ""
            canonical_zettel_id = meta.get("canonical_zettel_id")
            if canonical_zettel_id:
                try:
                    cz_resp = (
                        supabase_client.schema("content")
                        .table("canonical_zettels")
                        .select("title,ai_summary")
                        .eq("id", str(canonical_zettel_id))
                        .limit(1)
                        .execute()
                    )
                    cz_rows = list(cz_resp.data or [])
                    if cz_rows:
                        canonical_name = (
                            str(cz_rows[0].get("title") or "")
                            or canonical_name
                        )
                        summary_text = str(cz_rows[0].get("ai_summary") or "")
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "X8 backfill summary lookup failed node=%s: %s",
                        kg_node_id, exc,
                    )
            embed_input = (
                f"{canonical_name}\n\n{summary_text}".strip()[:2000]
            )
            if not embed_input:
                logger.info(
                    "kg-backfill node id=%s has no embed_input; skipping",
                    kg_node_id,
                )
                metrics["skipped"] = True
                return metrics
            # Mark the embed shape so downstream readers can spot mixed-shape
            # graphs (cold-only nodes embedded with title-only are slightly
            # less reliable than full-shape nodes).
            meta["embedding_input_shape"] = (
                "title_summary" if summary_text else "title_only"
            )
            embed_result = generate_embedding_typed(embed_input)
            if not embed_result.ok:
                logger.info(
                    "kg-backfill node id=%s embedding %s; skipping",
                    kg_node_id, embed_result.reason,
                )
                metrics["skipped"] = True
                return metrics
            node_embedding = embed_result.vectors[0]
            # Persist the regenerated vector back so future passes / the
            # live hook reuse it (best-effort: a write failure must not
            # block edge creation — the in-memory vector is enough now).
            try:
                meta["embedding"] = node_embedding
                supabase_client.schema("kg").table("kg_nodes").update(
                    {"metadata": meta}
                ).eq("workspace_id", str(workspace_id)).eq(
                    "id", int(kg_node_id)
                ).execute()
            except Exception as exc:  # pragma: no cover - best effort
                logger.warning(
                    "kg-backfill node id=%s embedding persist failed "
                    "(continuing with in-memory vector): %s",
                    kg_node_id,
                    exc,
                )

        # ---- Same scoring + edge-upsert core the live hook runs ---------
        _score_and_upsert_edges_for_node(
            workspace_id=workspace_id,
            profile_id=profile_id,
            node_id=int(kg_node_id),
            node_embedding=node_embedding,
            node_tags=node_tags,
            node_created_at_iso=node_created_at_iso,
            supabase_client=supabase_client,
            metrics=metrics,
            # Existing node has no single originating zettel for THIS pass;
            # leave evidence NULL (the column is nullable; the live hook
            # sets it only because it has the just-ingested zettel id).
            evidence_canonical_zettel_id=None,
        )
        logger.info(
            "kg-backfill node id=%s ws=%s candidates=%d edges=%d",
            kg_node_id,
            workspace_id,
            metrics["candidates"],
            metrics["edges"],
        )
        return metrics
    except Exception as exc:
        logger.warning(
            "kg-backfill node id=%s ws=%s failed: %s",
            kg_node_id,
            workspace_id,
            exc,
        )
        metrics["error"] = type(exc).__name__
        return metrics
