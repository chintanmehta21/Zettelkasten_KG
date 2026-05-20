"""Thin service-role wrappers around the migration-60 RPCs.

Mirrors the defensive posture of ``website.core.operations_repo``: every
function logs and returns a falsy/None on ANY error so the Add Zettel
critical path NEVER 5xxs because of the enrichment store. Sync by design;
callers dispatch via ``asyncio.to_thread`` when they need an awaitable.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from website.core.supabase_v2.client import get_v2_client

logger = logging.getLogger("website.features.summarization_engine.lazy_enrichment.repo")

_SCHEMA = "core"

# Kinds (the `kind` text column). Single string source so handler dispatch
# and the enqueue site can't drift.
KIND_CHUNK_EMBED: str = "chunk_embed"
KIND_KG_POPULATE: str = "kg_populate"  # reserved for Wave-4 (KG queue migration)


def enqueue_chunk_embed(
    *,
    user_id: UUID,
    canonical_zettel_id: UUID,
    workspace_zettel_id: UUID | None,
    payload: dict[str, Any],
    max_attempts: int = 3,
    ttl_seconds: int = 86400,
) -> tuple[str | None, bool]:
    """Enqueue a chunk+embed enrichment job. Returns ``(job_id, is_new)``.

    Idempotent via the partial unique index on (canonical_zettel_id, kind).
    A duplicate enqueue for an already-active job returns the canonical
    job_id with ``is_new=False`` and the caller treats it as a no-op.

    On ANY error returns ``(None, False)`` — the Add Zettel critical path
    treats enqueue failure as a soft signal (backfill_rechunk_v2 will pick
    the zettel up later) instead of failing the user-visible operation.
    """
    try:
        client = get_v2_client()
        resp = client.schema(_SCHEMA).rpc(
            "enrich_enqueue",
            {
                "p_user_id": str(user_id),
                "p_canonical_zettel_id": str(canonical_zettel_id),
                "p_workspace_zettel_id": (
                    str(workspace_zettel_id) if workspace_zettel_id else None
                ),
                "p_kind": KIND_CHUNK_EMBED,
                "p_payload": payload,
                "p_max_attempts": max_attempts,
                "p_ttl_seconds": ttl_seconds,
            },
        ).execute()
        rows = resp.data or []
        if not rows:
            logger.warning(
                "enrich_enqueue returned empty (canonical=%s)", canonical_zettel_id
            )
            return None, False
        row = rows[0]
        return str(row.get("job_id") or "") or None, bool(row.get("is_new"))
    except Exception:
        logger.exception(
            "enqueue_chunk_embed failed (canonical=%s)", canonical_zettel_id
        )
        return None, False


def claim_next() -> dict[str, Any] | None:
    """Claim the oldest queued enrichment job for this worker.

    Returns the row dict (job_id, user_id, canonical_zettel_id,
    workspace_zettel_id, kind, payload, attempts, max_attempts) or None
    when the queue is empty. Atomic via ``FOR UPDATE SKIP LOCKED`` inside
    the RPC.
    """
    try:
        client = get_v2_client()
        resp = client.schema(_SCHEMA).rpc("enrich_claim_next", {}).execute()
        rows = resp.data or []
        if not rows:
            return None
        return dict(rows[0])
    except Exception:
        logger.exception("enrich_claim_next failed")
        return None


_FINALIZE_TARGETS = frozenset({"succeeded", "failed", "dead_letter"})


def finalize(
    *,
    job_id: str,
    target: str,
    error: dict[str, Any] | None = None,
) -> bool:
    """``running`` -> ``(succeeded | failed | dead_letter)`` transition.

    Returns True iff the state-guarded UPDATE fired. False on no-op (row
    already terminal, doesn't exist, or PostgREST hiccup).
    """
    if target not in _FINALIZE_TARGETS:
        raise ValueError(
            f"enrichment_repo.finalize: invalid target {target!r}, "
            f"must be one of {sorted(_FINALIZE_TARGETS)}"
        )
    try:
        client = get_v2_client()
        resp = client.schema(_SCHEMA).rpc(
            "enrich_finalize",
            {"p_job_id": job_id, "p_target": target, "p_error": error},
        ).execute()
        return _decode_scalar(resp.data, target)
    except Exception:
        logger.exception(
            "enrich_finalize(%s) failed (job=%s)", target, job_id
        )
        return False


def requeue(*, job_id: str, error: dict[str, Any] | None = None) -> str | None:
    """Transient-failure retry: ``running`` -> ``queued`` (or ``dead_letter``
    if attempts exhausted). Returns the new status, or None on no-op."""
    try:
        client = get_v2_client()
        resp = client.schema(_SCHEMA).rpc(
            "enrich_requeue",
            {"p_job_id": job_id, "p_error": error},
        ).execute()
        data = resp.data
        if data is None:
            return None
        if isinstance(data, str):
            return data
        if isinstance(data, list) and data:
            first = data[0]
            if first is None:
                return None
            if isinstance(first, dict):
                return next(iter(first.values()), None)
            return first
        if isinstance(data, dict):
            return next(iter(data.values()), None)
        return None
    except Exception:
        logger.exception("enrich_requeue failed (job=%s)", job_id)
        return None


def _decode_scalar(data: Any, expected: str) -> bool:
    """PostgREST returns a scalar RETURNING as either the bare value or a
    single-row list with the function name as key. Collapse to bool."""
    if data is None:
        return False
    if isinstance(data, str):
        return data == expected
    if isinstance(data, list):
        if not data:
            return False
        first = data[0]
        if first is None:
            return False
        if isinstance(first, dict):
            val = next(iter(first.values()), None)
            return val == expected
        return first == expected
    if isinstance(data, dict):
        val = next(iter(data.values()), None)
        return val == expected
    return False
