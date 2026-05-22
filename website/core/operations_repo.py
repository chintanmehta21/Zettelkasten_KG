"""Shared async-operation store (Cloudflare-524 fix).

Thin service-role wrapper over ``core.operations`` built around the state-
guarded RPCs from migration 51 (``ops_accept`` / ``ops_start`` /
``ops_finalize``). Every function is defensive: on ANY error it logs and
returns a falsy/None value so the Add Zettel path NEVER 5xxs because of the
operation store. Sync by design — callable from the FastAPI request path via
``asyncio.to_thread`` and from the per-process worker coroutine.

Phase 5 (2026-05-20): the legacy ``create_accepted`` / ``mark_succeeded`` /
``mark_failed`` / ``_mark`` upsert helpers were deleted along with the in-
memory per-worker mirror in ``website/api/zettels_routes.py``. The DB row is
now the single source of truth across workers; idempotency is enforced by the
partial unique index ``ops_user_req_hash_active_uniq``.
"""
from __future__ import annotations

import logging
import time
from typing import Any
from uuid import UUID

from website.core.supabase_v2.client import get_v2_client

logger = logging.getLogger("website.core.operations_repo")

_SCHEMA = "core"
_TABLE = "operations"

# PR #39 / Wave-4 A5 (2026-05-20): retry policy for finalize() on transient
# PostgREST failures. A single hiccup at the very end of a pipeline used to
# leave the row stuck `running` until the 7-min reaper flipped it, even
# though the zettel itself persisted successfully. Three attempts with
# 0.5/1/2s exponential backoff covers the typical PostgREST blip without
# extending tail latency materially.
_FINALIZE_RETRY_BACKOFF_S: tuple[float, ...] = (0.5, 1.0, 2.0)


# ---------------------------------------------------------------------------
# Phase 2 (async-ops redesign): RPC-backed state-machine wrappers.
# accept / start / finalize / cancel are the ONLY callers of migration 51's
# state-guarded RPCs (ops_accept / ops_start / ops_finalize). Phase 5 (this
# file) deleted the prior legacy create_accepted / mark_* upsert helpers.
# ---------------------------------------------------------------------------


def _cancel_problem_dict(operation_id: str) -> dict[str, Any]:
    """RFC 9457 error body for cooperative cancellation.

    Phase 3: routes through the unified ``_problem_dict()`` builder in
    ``website.api._problem`` so sync 4xxs, async-finalized failures, AND
    cancel writes emit physically-identical problem shapes for clients
    that key off ``body.code`` / ``body.error.code``.
    """
    # Local import keeps the dependency graph one-way (api -> core) and
    # avoids any chance of circular import at module load.
    from website.api._problem import _problem_dict

    return _problem_dict(
        status_code=499,
        title="Operation cancelled",
        detail="The operation was cancelled by the client.",
        type_slug="operation_cancelled",
        operation_id=operation_id,
        instance=f"/api/zettels/operations/{operation_id}",
    )


def accept(
    *,
    user_id: UUID,
    operation_id: str,
    request_hash: str,
    accepted_body: dict[str, Any],
    ttl_seconds: int = 86400,
) -> tuple[str, bool] | None:
    """Idempotent accept via ``core.ops_accept`` RPC.

    Returns ``(canonical_operation_id, is_new)``. The RPC body returns exactly
    one row ``{operation_id, status, is_new}`` whether the INSERT fired or the
    partial-unique-index conflict path served the existing active row.

    ADR-2 (fail-closed): on ANY operations-store failure returns ``None``. The
    prior posture returned ``(operation_id, True)`` so the request never 5xxd,
    but that spawned background work the client could never poll (no durable
    row to read) — an infinite-pending UX. The caller now returns a retriable
    503 instead, so a store outage is an honest, recoverable error.
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
            # The RPC CTE guarantees one row; empty data means the store did
            # not durably record the operation. Fail closed.
            logger.error(
                "operations_repo.accept: ops_accept returned empty data (op=%s)",
                operation_id,
            )
            return None
        row = rows[0]
        return str(row.get("operation_id") or operation_id), bool(row.get("is_new"))
    except Exception:
        logger.exception("operations_repo.accept failed (op=%s)", operation_id)
        return None


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

    PR #39 / Wave-4 A5: retry on transient PostgREST failures up to 3 times
    with 0.5/1/2s backoff. The 7-min reaper covers exhausted attempts; the
    retry just narrows the window where the zettel is persisted but the
    operations row is stuck `running`.
    """
    if target not in _FINALIZE_TARGETS:
        raise ValueError(
            f"operations_repo.finalize: invalid target {target!r}, "
            f"must be one of {sorted(_FINALIZE_TARGETS)}"
        )
    last_exc: Exception | None = None
    attempts = len(_FINALIZE_RETRY_BACKOFF_S) + 1  # initial + N retries
    for attempt in range(attempts):
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
        except Exception as exc:  # noqa: BLE001 — retry transient class
            last_exc = exc
            if attempt < attempts - 1:
                sleep_s = _FINALIZE_RETRY_BACKOFF_S[attempt]
                logger.warning(
                    "operations_repo.finalize(%s) attempt %d/%d failed; "
                    "retrying in %.1fs (op=%s)",
                    target, attempt + 1, attempts, sleep_s, operation_id,
                    exc_info=True,
                )
                time.sleep(sleep_s)
                continue
            logger.exception(
                "operations_repo.finalize(%s) exhausted %d attempts (op=%s); "
                "stuck-running reaper will eventually flip the row",
                target, attempts, operation_id,
            )
            return False
    # Unreachable — the loop returns or breaks on the last attempt.
    # Defensive fallthrough to satisfy static analysers.
    if last_exc is not None:
        logger.error(
            "operations_repo.finalize(%s) fell through retry loop (op=%s): %s",
            target, operation_id, last_exc,
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
            .select("operation_id,user_id,status,response,error,created_at,updated_at")
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
