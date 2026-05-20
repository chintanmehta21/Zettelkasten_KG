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
    """Insert-only ``accepted`` row; no-op if any row already exists.

    ON CONFLICT DO NOTHING (ignore_duplicates=True). This write is best-effort
    and may be delayed; the terminal mark_succeeded/mark_failed upsert can land
    first. An overwriting upsert would then revert a terminal row back to
    status='accepted' (false 202-forever on cross-worker polls). Insert-only
    means: no row -> create the bridge accepted row; ANY existing row (prior
    accepted OR terminal) -> leave it untouched.
    """
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
            ignore_duplicates=True,
        ).execute()
        return True
    except Exception:
        logger.exception("operations_repo.create_accepted failed (op=%s)", operation_id)
        return False


def _mark(
    *,
    user_id: UUID,
    operation_id: str,
    request_hash: str,
    status: str,
    payload: dict[str, Any],
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
        # UPSERT, not blind .update(): create_accepted is best-effort, so the
        # accepted row may never have been written. A filtered .update() would
        # then match zero rows -> silent no-op -> the completed op is never
        # persisted and a cross-worker poll returns not-found forever. Upsert
        # on (user_id, operation_id) makes the terminal write self-sufficient;
        # request_hash is threaded from the caller to satisfy the NOT NULL
        # column on the insert branch (and is overwritten with the same value
        # on the conflict branch — idempotency-safe, request_hash is never a
        # stored-row lookup key, only an in-memory idempotency-cache key).
        client.schema(_SCHEMA).table(_TABLE).upsert(
            {
                "user_id": str(user_id),
                "operation_id": operation_id,
                "request_hash": request_hash,
                "status": status,
                **cols,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="user_id,operation_id",
        ).execute()
        return True
    except Exception:
        logger.exception(
            "operations_repo._mark(%s) failed (op=%s)", status, operation_id
        )
        return False


def mark_succeeded(
    *, user_id: UUID, operation_id: str, request_hash: str, response: dict[str, Any]
) -> bool:
    return _mark(
        user_id=user_id, operation_id=operation_id, request_hash=request_hash,
        status="succeeded", payload=response,
    )


def mark_failed(
    *, user_id: UUID, operation_id: str, request_hash: str, response: dict[str, Any]
) -> bool:
    """`response` is the failed AddZettelResponse payload; written to the `error` column by `_mark`."""
    return _mark(
        user_id=user_id, operation_id=operation_id, request_hash=request_hash,
        status="failed", payload=response,
    )


# ---------------------------------------------------------------------------
# Phase 2 (async-ops redesign): RPC-backed state-machine wrappers.
# These coexist with the legacy create_accepted / mark_succeeded / mark_failed
# above; Phase 5 deletes the legacy fns. New code MUST use accept/start/
# finalize/cancel — they are the only callers of migration 51's state-guarded
# RPCs (ops_accept / ops_start / ops_finalize).
# ---------------------------------------------------------------------------


def _cancel_problem_dict(operation_id: str) -> dict[str, Any]:
    """Minimal RFC 9457-ish error body for cancellation.

    Phase 2 stub; Phase 3 replaces with the unified ``_problem_dict()`` helper
    in zettels_routes. Kept here so ``cancel(...)`` is self-sufficient.
    """
    return {
        "type": "https://zettelkasten.in/problems/operation-cancelled",
        "title": "Operation cancelled",
        "status": 499,
        "detail": "The operation was cancelled by the client.",
        "instance": f"/api/zettels/operations/{operation_id}",
        "code": "operation_cancelled",
    }


def accept(
    *,
    user_id: UUID,
    operation_id: str,
    request_hash: str,
    accepted_body: dict[str, Any],
    ttl_seconds: int = 86400,
) -> tuple[str, bool]:
    """Idempotent accept via ``core.ops_accept`` RPC.

    Returns ``(canonical_operation_id, is_new)``. The RPC body returns exactly
    one row ``{operation_id, status, is_new}`` whether the INSERT fired or the
    partial-unique-index conflict path served the existing active row.

    Defensive: on ANY error returns ``(operation_id, True)`` so the request
    path never 5xxs because of the operations store (mirrors the existing
    legacy posture).
    """
    try:
        client = get_v2_client()
        resp = client.schema(_SCHEMA).rpc(
            "ops_accept",
            {
                "p_user_id": str(user_id),
                "p_operation_id": operation_id,
                "p_request_hash": request_hash,
                "p_accepted": accepted_body,
                "p_ttl_seconds": ttl_seconds,
            },
        ).execute()
        rows = resp.data or []
        if not rows:
            # Should never happen — the RPC CTE guarantees one row. Fall back
            # to is_new=True so the caller spawns the task.
            logger.warning(
                "operations_repo.accept: ops_accept returned empty data (op=%s)",
                operation_id,
            )
            return operation_id, True
        row = rows[0]
        return str(row.get("operation_id") or operation_id), bool(row.get("is_new"))
    except Exception:
        logger.exception("operations_repo.accept failed (op=%s)", operation_id)
        return operation_id, True


def start(*, user_id: UUID, operation_id: str) -> bool:
    """``queued -> running`` transition via ``core.ops_start`` RPC.

    Returns True iff the state-guarded UPDATE fired (RPC returned a non-null
    status). False if the row is already running, terminal, or nonexistent.
    """
    try:
        client = get_v2_client()
        resp = client.schema(_SCHEMA).rpc(
            "ops_start",
            {"p_user_id": str(user_id), "p_operation_id": operation_id},
        ).execute()
        data = resp.data
        # Scalar text RETURNING: postgrest returns either the bare scalar
        # ('running' / None) or a single-row list with the function-name key.
        # Both shapes collapse to "transition fired" iff we can pull a non-null
        # 'running' from `data`.
        if data is None:
            return False
        if isinstance(data, str):
            return data == "running"
        if isinstance(data, list):
            if not data:
                return False
            first = data[0]
            if first is None:
                return False
            if isinstance(first, dict):
                # `{'ops_start': 'running'}` or `{'ops_start': None}`
                val = next(iter(first.values()), None)
                return val == "running"
            return first == "running"
        if isinstance(data, dict):
            val = next(iter(data.values()), None)
            return val == "running"
        return False
    except Exception:
        logger.exception("operations_repo.start failed (op=%s)", operation_id)
        return False


_FINALIZE_TARGETS = frozenset({"succeeded", "failed", "cancelled"})


def finalize(
    *,
    user_id: UUID,
    operation_id: str,
    target: str,
    response: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> bool:
    """``(queued|running) -> terminal`` transition via ``core.ops_finalize``.

    ``target`` must be one of succeeded/failed/cancelled. Returns True iff the
    state-guarded UPDATE fired (RPC returned non-null status). False on no-op
    (row already terminal — bug-class killer for duplicate-finalize races).
    """
    if target not in _FINALIZE_TARGETS:
        raise ValueError(
            f"operations_repo.finalize: invalid target {target!r}, "
            f"must be one of {sorted(_FINALIZE_TARGETS)}"
        )
    try:
        client = get_v2_client()
        resp = client.schema(_SCHEMA).rpc(
            "ops_finalize",
            {
                "p_user_id": str(user_id),
                "p_operation_id": operation_id,
                "p_target": target,
                "p_response": response,
                "p_error": error,
            },
        ).execute()
        data = resp.data
        # Same scalar-text decoding as start(): True iff a non-null status
        # made it back from RETURNING.
        if data is None:
            return False
        if isinstance(data, str):
            return data == target
        if isinstance(data, list):
            if not data:
                return False
            first = data[0]
            if first is None:
                return False
            if isinstance(first, dict):
                val = next(iter(first.values()), None)
                return val == target
            return first == target
        if isinstance(data, dict):
            val = next(iter(data.values()), None)
            return val == target
        return False
    except Exception:
        logger.exception(
            "operations_repo.finalize(%s) failed (op=%s)", target, operation_id
        )
        return False


def count_in_flight_for_user(*, user_id: UUID) -> int:
    """Number of ``queued`` or ``running`` operations for ``user_id``.

    Used by the per-user async backpressure gate (Phase 4). Fail-open: any
    error returns 0 so backpressure NEVER 5xxs the accept path.
    """
    try:
        client = get_v2_client()
        resp = (
            client.schema(_SCHEMA)
            .table(_TABLE)
            .select("operation_id", count="exact", head=True)
            .eq("user_id", str(user_id))
            .in_("status", ["queued", "running"])
            .execute()
        )
        return int(getattr(resp, "count", 0) or 0)
    except Exception:
        logger.exception(
            "operations_repo.count_in_flight_for_user failed (user=%s)", user_id
        )
        return 0


def cancel(*, user_id: UUID, operation_id: str) -> bool:
    """Cancel an in-flight op via ``finalize(target='cancelled', ...)``.

    Idempotent under duplicate cancel: a row already terminal returns False
    (the RPC's WHERE guard makes the UPDATE a no-op).
    """
    return finalize(
        user_id=user_id,
        operation_id=operation_id,
        target="cancelled",
        response=None,
        error=_cancel_problem_dict(operation_id),
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
