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
from datetime import datetime, timezone
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
#   effective = shared_chunk_cooccur + round(_ADAMIC_AA_WEIGHT * adamic_adar)
# _ADAMIC_AA_WEIGHT is conservative (0.5) so AA only nudges the integer "count":
# a strong AA (~2.0 over several rare common neighbours) contributes round(1.0)=1
# — i.e. at most "one extra co-mention" worth — keeping shared-chunk overlap
# dominant whenever it is non-zero, while still letting AA register on a graph
# that has edges but no shared chunks yet.
_ADAMIC_AA_WEIGHT = 0.5

# Hard cap on the structural fan-out queries so per-add cost stays a small
# constant independent of workspace size (D-KG-1 scale guard / index-backed).
_STRUCTURAL_QUERY_LIMIT = 5000

# Hard cap on the Adamic-Adar common-neighbour set whose true degree we
# resolve (Q3 IN-list). Keeps the per-add query cost a small constant even
# for a pathologically dense new node; AA is a secondary signal so a capped
# neighbour set is an acceptable bounded approximation.
_AA_NEIGHBOUR_CAP = 500


def _top_k() -> int:
    try:
        k = int(os.getenv("KG_POPULATION_TOP_K", str(_DEFAULT_TOP_K)))
    except (TypeError, ValueError):
        return _DEFAULT_TOP_K
    return max(1, min(k, 200))


_NODE_TYPE = "zettel"
_RELATION_TYPE = "co_occurs"  # similarity-derived edge (kg.kg_edge_relation enum)


def _slugify(text: str, *, max_len: int = 96) -> str:
    out = []
    prev_dash = False
    for ch in text.strip().lower():
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

    Combination: ``effective = cooccur + round(_ADAMIC_AA_WEIGHT * aa)``.
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
        effective = co + round(_ADAMIC_AA_WEIGHT * a)
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
        "tag": round(_sc._jaccard(a_tags, b_tags), 4),
        "structural": round(struct_squashed, 4),
        "structural_shared_chunks": int(struct_co),
        "structural_adamic_adar": round(float(struct_aa), 4),
        "temporal": round(_sc._temporal_signal(tdays), 4),
        "composite": round(strength, 4),
    }
    return strength, matched_via


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

    from website.core.supabase_v2.repositories.kg_repository import KGRepository
    from website.core.supabase_v2.repositories.pipelines_repository import (
        PipelinesRepository,
    )
    from website.features.kg_features.embeddings import (
        find_similar_nodes,
        generate_embedding,
    )
    from website.features.kg_features.pseudo_tags import derive_pseudo_tags
    from website.features.kg_features.scoring import EDGE_CREATION_THRESHOLD

    metrics: dict = {"candidates": 0, "scored": 0, "edges": 0, "skipped": False}

    pipelines = PipelinesRepository(supabase_client)
    kg = KGRepository(supabase_client)

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
        node_embedding = await asyncio.to_thread(generate_embedding, embed_input)

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

        # ---- 4. Bounded candidate set (top-K similar workspace nodes) --
        if not node_embedding:
            logger.info(
                "kg-populate no embedding; node upserted, no edges zettel=%s",
                canonical_zettel_id,
            )
            await asyncio.to_thread(
                pipelines.finish_run,
                run_id=run_id,
                status="succeeded",
                metrics=metrics,
            )
            return metrics

        k = _top_k()
        candidates = await asyncio.to_thread(
            find_similar_nodes,
            supabase_client,
            str(profile_id),  # match_kg_nodes resolves owner -> workspaces
            node_embedding,
            0.0,  # collect K nearest; D-KG-1 owns the create cutoff
            k,
        )
        # Drop the just-created node + hard-cap at K (defensive — the RPC
        # already LIMITs, but never score more than K candidates).
        candidates = [
            c for c in candidates if int(c.get("node_id", -1)) != node_id
        ][:k]
        metrics["candidates"] = len(candidates)

        if not candidates:
            await asyncio.to_thread(
                pipelines.finish_run,
                run_id=run_id,
                status="succeeded",
                metrics=metrics,
            )
            return metrics

        # Batch-load candidate scoring inputs from kg_nodes.metadata, fenced
        # to THIS workspace (tenant isolation: never reads workspace B).
        cand_ids = [int(c["node_id"]) for c in candidates]
        meta_resp = await asyncio.to_thread(
            lambda: supabase_client.schema("kg")
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

        # ---- 4b. STRUCTURAL signal (D-KG-1 slot, restored) ------------
        # Computed ONCE over the whole candidate set (bounded constant
        # query count, NOT per-candidate). Failure degrades to None ==
        # pre-restore behaviour; never raises (fire-and-forget hook).
        structural_map, structural_sub = await asyncio.to_thread(
            _structural_map,
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

            # Single source of truth: the SAME pure scorer the backfill
            # uses (score_edge), so the live hook and the one-shot strength
            # backfill can never diverge. Output is byte-identical to the
            # block this previously inlined.
            strength, matched_via = score_edge(
                a_key=new_key,
                a_embedding=node_embedding,
                a_tags=augmented_tags,
                a_created_at_iso=created_at_iso,
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

            await asyncio.to_thread(
                lambda cid=cid, mv=matched_via, s=strength: kg.upsert_edge(
                    workspace_id=workspace_id,
                    src_node_id=node_id,
                    dst_node_id=cid,
                    relation_type=_RELATION_TYPE,
                    connection_strength=round(s, 3),
                    # workspace_strength = D-KG-1 over WORKSPACE-scoped data
                    # (candidates come from the owner's workspaces only).
                    workspace_strength=round(s, 3),
                    # global_strength left NULL: cross-workspace scoring
                    # would need an expensive all-tenant scan; design says
                    # NULL is acceptable (stored-for-future, never rendered).
                    global_strength=None,
                    matched_via=mv,
                    evidence_canonical_zettel_id=canonical_zettel_id,
                )
            )
            metrics["edges"] += 1

        await asyncio.to_thread(
            pipelines.finish_run,
            run_id=run_id,
            status="succeeded",
            metrics=metrics,
        )
        logger.info(
            "kg-populate done zettel=%s node=%s candidates=%d edges=%d",
            canonical_zettel_id,
            node_id,
            metrics["candidates"],
            metrics["edges"],
        )
        return metrics
    except Exception as exc:
        logger.warning(
            "kg-populate failed zettel=%s: %s", canonical_zettel_id, exc
        )
        metrics["error"] = type(exc).__name__
        try:
            await asyncio.to_thread(
                pipelines.finish_run,
                run_id=run_id,
                status="failed",
                metrics=metrics,
                error=str(exc),
            )
        except Exception as fin_exc:  # pragma: no cover - best effort
            logger.warning("kg-populate run finalize failed: %s", fin_exc)
        return metrics
