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
import os
from datetime import datetime, timezone
from uuid import UUID

logger = logging.getLogger("website.features.rag_pipeline.ingest.kg_population")

# Bounded candidate fan-out. NEVER all-pairs — scale-safe on the 1-vCPU /
# 10k+ target. Env-overridable (RAG/KG convention) but defaults to a small
# constant so a misconfig can't explode the per-ingest cost.
_DEFAULT_TOP_K = 25


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
    from website.features.kg_features.scoring import (
        EDGE_CREATION_THRESHOLD,
        compute_connection_strength,
    )

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
            embeddings_map = {new_key: node_embedding, cand_key: cand_embedding}
            tags_map = {
                new_key: augmented_tags,
                cand_key: list(cmeta.get("tags") or []),
            }
            tdays = _temporal_days(created_at_iso, cmeta.get("created_at"))

            strength = compute_connection_strength(
                new_key,
                cand_key,
                embeddings=embeddings_map,
                tags=tags_map,
                structural=None,  # no co-occurrence store on the v2 path yet
                temporal_days=tdays,
            )
            metrics["scored"] += 1

            if strength < EDGE_CREATION_THRESHOLD:
                continue

            # matched_via: the per-signal sub-scores the scorer composes,
            # so the edge can be audited/re-explained without recompute.
            from website.features.kg_features import scoring as _sc

            emb_sub = _sc._cosine_similarity(node_embedding, cand_embedding)
            if (not node_embedding or not cand_embedding) and rpc_score is not None:
                emb_sub = float(rpc_score)
            matched_via = {
                "embedding": round(emb_sub, 4),
                "tag": round(
                    _sc._jaccard(augmented_tags, list(cmeta.get("tags") or [])), 4
                ),
                "structural": 0.0,
                "temporal": round(_sc._temporal_signal(tdays), 4),
                "composite": round(strength, 4),
            }

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
