"""chunk+embed handler: the heaviest piece of Add Zettel persistence,
moved off the critical path by Wave-3 (PR #39).

Re-uses the existing ``website.core.persist.build_canonical_chunks`` so
the chunker, token-budget cap, embed-or-skip contract, and model-version
stamp can never diverge from the live inline path (or the
``ops/scripts/backfill_rechunk_v2.py`` recovery script). The handler is a
thin orchestrator: claim payload -> build chunks -> write via the
existing v2 RPC -> done.

Payload schema (the dict stored in ``core.zettel_enrichment_jobs.payload``):
    {
        "canonical_zettel_id": "<uuid>",
        "workspace_zettel_id": "<uuid|null>",
        "detailed_summary":   "...",
        "summarized_payload": { ...the dict we'd otherwise have passed
                                  inline to build_canonical_chunks... }
    }

The handler returns nothing on success; raises on failure (the worker
catches and routes to enrich_requeue / enrich_finalize as appropriate).
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from website.core.persist import build_canonical_chunks
from website.core.supabase_v2.client import get_v2_client
from website.core.supabase_v2.repositories.content_repository import (
    ContentRepository as V2ContentRepository,
)

logger = logging.getLogger(
    "website.features.summarization_engine.lazy_enrichment.handlers.chunk_embed"
)


async def handle(payload: dict[str, Any]) -> None:
    """Build canonical chunks for the zettel and write them via the v2
    content repository's chunk-only path.

    Idempotent at the data layer: writing chunks for a canonical_zettel
    that already has chunks is a no-op via the chunk-row upsert key
    (canonical_zettel_id, chunk_idx); but we additionally guard with the
    partial unique index on the job table so a duplicate enqueue cannot
    even fire this handler twice for the same (canonical_zettel_id, kind).
    """
    canonical_zettel_id = payload.get("canonical_zettel_id")
    if not canonical_zettel_id:
        raise ValueError("chunk_embed handler: payload missing canonical_zettel_id")
    detailed_summary = str(payload.get("detailed_summary") or "")
    summarized_payload = dict(payload.get("summarized_payload") or {})

    chunks = await build_canonical_chunks(
        payload=summarized_payload, detailed_summary=detailed_summary
    )
    if not chunks:
        # Two legitimate outcomes covered by the existing persist logic:
        #  (1) empty source text -> nothing to chunk (zettel was already
        #      persisted with quality_flag handled in persist.py).
        #  (2) batch-embed failure -> the embed-or-skip contract forbids a
        #      NULL-embedding row; backfill_rechunk_v2.py recovers later.
        logger.warning(
            "chunk_embed handler produced 0 chunks for canonical=%s — "
            "backfill_rechunk_v2.py will recover if applicable.",
            canonical_zettel_id,
        )
        return

    # Chunk-only write via ContentRepository.upsert_chunks (already used by
    # ops/scripts/backfill_rechunk_v2.py — single source of truth for the
    # ON CONFLICT(canonical_zettel_id, chunk_idx) upsert + dense-idx prune).
    repo = V2ContentRepository(get_v2_client())
    canonical_uuid = UUID(str(canonical_zettel_id))
    chunk_ids = repo.upsert_chunks(canonical_uuid, chunks)

    # The inline persist path used to call upsert_workspace_chunk_membership
    # right after upsert_chunks. Replicate that here so cross-workspace
    # retrieval surfaces these chunks for the owning workspace.
    workspace_zettel_id = payload.get("workspace_zettel_id")
    workspace_id = payload.get("workspace_id")
    if workspace_zettel_id and workspace_id and chunk_ids:
        repo.upsert_workspace_chunk_membership(
            workspace_id=UUID(str(workspace_id)),
            workspace_zettel_id=UUID(str(workspace_zettel_id)),
            canonical_chunk_ids=chunk_ids,
        )
    logger.info(
        "chunk_embed handler wrote %d chunks for canonical=%s",
        len(chunks),
        canonical_zettel_id,
    )
