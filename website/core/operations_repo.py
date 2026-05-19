"""Shared async-operation store (Cloudflare-524 fix).

Thin service-role wrapper over ``core.operations``. Every function is
defensive: on ANY error it logs and returns a falsy/None value so the Add
Zettel path NEVER 5xxs because of the operation store (the in-memory store
is the single-worker fallback). Sync by design — callable from the FastAPI
request path via ``asyncio.to_thread`` and from the task done-callback.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from website.core.supabase_v2.client import get_v2_client

logger = logging.getLogger("website.core.operations_repo")

_SCHEMA = "core"
_TABLE = "operations"


def create_accepted(
    *,
    user_id: UUID,
    operation_id: str,
    request_hash: str,
    accepted_body: dict[str, Any],
) -> bool:
    """Upsert an ``accepted`` row. Idempotent on (user_id, operation_id)."""
    try:
        client = get_v2_client()
        client.schema(_SCHEMA).table(_TABLE).upsert(
            {
                "user_id": str(user_id),
                "operation_id": operation_id,
                "request_hash": request_hash,
                "status": "accepted",
                "response": accepted_body,
                "error": None,
            },
            on_conflict="user_id,operation_id",
        ).execute()
        return True
    except Exception:
        logger.exception("operations_repo.create_accepted failed (op=%s)", operation_id)
        return False


def _mark(
    *, user_id: UUID, operation_id: str, status: str, payload: dict[str, Any]
) -> bool:
    try:
        client = get_v2_client()
        # Status-consistent write: a failed row must NOT keep the stale
        # accepted body in `response` (any consumer reading `response or
        # error` would otherwise serve the accepted body for a failed op).
        if status == "succeeded":
            cols = {"response": payload, "error": None}
        else:
            cols = {"error": payload, "response": None}
        client.schema(_SCHEMA).table(_TABLE).update(
            {"status": status, **cols, "updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("user_id", str(user_id)).eq("operation_id", operation_id).execute()
        return True
    except Exception:
        logger.exception(
            "operations_repo._mark(%s) failed (op=%s)", status, operation_id
        )
        return False


def mark_succeeded(
    *, user_id: UUID, operation_id: str, response: dict[str, Any]
) -> bool:
    return _mark(
        user_id=user_id, operation_id=operation_id,
        status="succeeded", payload=response,
    )


def mark_failed(
    *, user_id: UUID, operation_id: str, response: dict[str, Any]
) -> bool:
    """`response` is the failed AddZettelResponse payload; written to the `error` column by `_mark`."""
    return _mark(
        user_id=user_id, operation_id=operation_id,
        status="failed", payload=response,
    )


def get_operation(*, user_id: UUID, operation_id: str) -> dict[str, Any] | None:
    """Return the operation row scoped to ``user_id`` (BOLA-safe), or None.

    On a transient client/DB error it returns None (indistinguishable from a
    genuine miss) and the caller falls back to the in-memory store — by design,
    the error is logged via logger.exception.
    """
    try:
        client = get_v2_client()
        resp = (
            client.schema(_SCHEMA)
            .table(_TABLE)
            .select("operation_id,user_id,status,response,error")
            .eq("user_id", str(user_id))
            .eq("operation_id", operation_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception:
        logger.exception(
            "operations_repo.get_operation failed (op=%s)", operation_id
        )
        return None
