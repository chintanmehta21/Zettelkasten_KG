"""Async-operations shared infrastructure (zettels + sandboxes + future).

Generic pieces used by every async POST route family:

* ``retry_after_for_age`` — server-guided poll backoff that grows with op age.
* ``terminal_cache_headers`` — private cache-control + ETag for terminal rows.
* ``run_worker`` — pipeline-agnostic background worker (start → run → finalize).
* ``render_operation_status`` — generic GET-status renderer reading from
  ``core.operations``.

Each route layer still owns its own per-process ``_LIVE_TASKS`` strong-ref
dict (cancel target) and a route-family-specific ``failure_mapper`` callable
that shapes the failed-state body with the appropriate ``type_slug`` /
``instance``. The cross-worker truth lives in ``core.operations``; access
flows through ``website.core.operations_repo``.

Locked decision D3 (2026-05-23): all async POSTs converge on this contract
so future endpoints don't fork the async-ops machinery.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi.responses import JSONResponse

from website.api._problem import _problem_dict
from website.core import operations_repo

logger = logging.getLogger("website.api._async_ops")

NO_STORE_HEADERS: dict[str, str] = {"Cache-Control": "no-store"}


def retry_after_for_age(created_at_raw: Any, *, default: str = "3") -> str:
    """Server-guided poll backoff (zettels_routes ADR-1 parity).

    Retry-After grows with operation age so short jobs poll fast (snappy UX)
    while long jobs poll sparsely (low droplet load). Falls back to ``default``
    if the timestamp is unparseable.
    """
    try:
        created = datetime.fromisoformat(
            str(created_at_raw).replace("Z", "+00:00")
        )
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_s = (datetime.now(timezone.utc) - created).total_seconds()
    except Exception:  # noqa: BLE001 — defensive parse
        return default
    if age_s < 20:
        return "2"
    if age_s < 60:
        return "4"
    if age_s < 180:
        return "10"
    return "20"


def terminal_cache_headers(
    operation_id: str, status: str, updated_at: Any
) -> dict[str, str]:
    """ETag + private cache-control for terminal operation responses.

    Mirrors ``zettels_routes._terminal_cache_headers``. Terminal rows
    (succeeded/failed/cancelled/expired) are IMMUTABLE — once finalize fires
    the row never mutates — so the browser can cache the response for 5
    minutes. ``private`` = browser-only cache (per-user-scoped, must NOT
    leak across tenants via CDN). ETag derived from
    ``(op_id, status, updated_at)`` so any rewrite invalidates client caches.
    """
    etag_input = f"{operation_id}|{status}|{updated_at or ''}".encode("utf-8")
    etag = '"' + hashlib.sha256(etag_input).hexdigest()[:16] + '"'
    return {
        "Cache-Control": "private, max-age=300",
        "ETag": etag,
    }


async def run_worker(
    *,
    user_id: UUID,
    operation_id: str,
    pipeline: Callable[[], Awaitable[dict[str, Any]]],
    failure_mapper: Callable[[BaseException, str], dict[str, Any]],
    operation_context_cm: Callable[[str], AbstractContextManager[None]] | None = None,
) -> None:
    """Pipeline-agnostic background worker for any async POST family.

    State-machine: ops_start → run pipeline → ops_finalize(succeeded|failed|
    cancelled). All transitions are state-guarded RPCs — a stale finalize
    against an already-terminal row is a silent no-op (kills the duplicate-
    finalize / blind-update bug class by construction).

    ``failure_mapper(exc, operation_id) -> body`` is the route-family-specific
    shaper that maps the in-flight exception into the failed-state envelope
    body (with a structured RFC 9457 ``error`` dict). Examples:

    * zettels: ``_failed_response_for`` returns ``AddZettelResponse(status=
      "failed", error=...)``.
    * sandboxes: ``_failed_kasten_response`` returns a Kasten-shaped envelope.

    ``operation_context_cm`` (typically ``website.core.request_context.
    operation_context``) is wrapped around the pipeline coroutine when supplied
    so deep log lines correlate to the op id.
    """
    try:
        await asyncio.to_thread(
            operations_repo.start,
            user_id=user_id,
            operation_id=operation_id,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "operations_repo.start raised in run_worker (op=%s)", operation_id
        )

    try:
        if operation_context_cm is not None:
            with operation_context_cm(operation_id):
                result = await pipeline()
        else:
            result = await pipeline()
    except asyncio.CancelledError:
        failed_body = failure_mapper(asyncio.CancelledError(), operation_id)
        try:
            await asyncio.to_thread(
                operations_repo.finalize,
                user_id=user_id,
                operation_id=operation_id,
                target="cancelled",
                response=failed_body,
                error=failed_body.get("error"),
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "operations_repo.finalize(cancelled) raised (op=%s)",
                operation_id,
            )
        raise
    except Exception as exc:
        logger.exception(
            "Background async operation failed (op=%s)", operation_id
        )
        failed_body = failure_mapper(exc, operation_id)
        try:
            await asyncio.to_thread(
                operations_repo.finalize,
                user_id=user_id,
                operation_id=operation_id,
                target="failed",
                response=failed_body,
                error=failed_body.get("error"),
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "operations_repo.finalize(failed) raised (op=%s)", operation_id
            )
        return

    # Success: stamp the canonical operation_id on the result and persist.
    if isinstance(result, dict):
        result["operation_id"] = operation_id
    try:
        await asyncio.to_thread(
            operations_repo.finalize,
            user_id=user_id,
            operation_id=operation_id,
            target="succeeded",
            response=result,
            error=None,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "operations_repo.finalize(succeeded) raised (op=%s)", operation_id
        )


async def render_operation_status(
    *,
    operation_id: str,
    user_id: UUID,
    poll_url_base: str,
    expired_instance: str | None = None,
) -> JSONResponse:
    """Generic GET-status renderer reading from ``core.operations``.

    BOLA-scoped to ``user_id`` (the operations_repo.get_operation eq-filter
    on user_id makes a foreign id resolve to None → 202 pending → caller's
    poll budget expires client-side without ever revealing the row's
    existence in another tenant).

    ``poll_url_base`` is the route family's own polling URL (e.g.
    ``"/api/operations"`` or ``"/api/rag/sandboxes/operations"``); used for
    the active-state ``Location`` header. ``expired_instance`` overrides the
    410 problem ``instance`` field (defaults to ``poll_url_base/{op_id}``).
    """
    row = await asyncio.to_thread(
        operations_repo.get_operation,
        user_id=user_id,
        operation_id=operation_id,
    )

    poll_url = f"{poll_url_base}/{operation_id}"

    if row is None:
        # Cross-worker replication gap during accept: the accepted row may
        # not yet be visible to this worker's read replica. Return a transient
        # 202 pending — bounded by the client's poll budget, after which a
        # genuinely-bogus id falls out client-side.
        return JSONResponse(
            {
                "status": "accepted",
                "operation_id": operation_id,
                "status_url": poll_url,
            },
            status_code=202,
            headers={
                "Location": poll_url,
                "Retry-After": "2",
                **NO_STORE_HEADERS,
            },
        )

    status = row.get("status")

    if status in ("queued", "running", "accepted"):
        payload = dict(row.get("response") or {})
        payload["phase"] = status if status in ("queued", "running") else "queued"
        payload["created_at"] = row.get("created_at")
        payload["updated_at"] = row.get("updated_at")
        return JSONResponse(
            payload,
            status_code=202,
            headers={
                "Location": poll_url,
                "Retry-After": retry_after_for_age(row.get("created_at")),
                **NO_STORE_HEADERS,
            },
        )

    if status == "succeeded":
        payload = row.get("response") or {}
        return JSONResponse(
            payload,
            status_code=200,
            headers=terminal_cache_headers(
                operation_id, status, row.get("updated_at")
            ),
        )

    if status in ("failed", "cancelled"):
        cache_headers = terminal_cache_headers(
            operation_id, status, row.get("updated_at")
        )
        body_resp = row.get("response")
        if isinstance(body_resp, dict) and body_resp:
            return JSONResponse(body_resp, status_code=200, headers=cache_headers)
        envelope = {
            "status": status,
            "operation_id": operation_id,
            "error": row.get("error") or {},
        }
        return JSONResponse(envelope, status_code=200, headers=cache_headers)

    if status == "expired":
        envelope = {
            "status": "expired",
            "operation_id": operation_id,
            "error": row.get("error")
            or _problem_dict(
                status_code=410,
                title="Operation expired",
                detail="This operation's TTL elapsed before it could be retrieved.",
                type_slug="operation_expired",
                operation_id=operation_id,
                instance=expired_instance or poll_url,
            ),
        }
        return JSONResponse(
            envelope,
            status_code=410,
            headers=terminal_cache_headers(
                operation_id, status, row.get("updated_at")
            ),
        )

    # Unknown — defensive fallback (CHECK constraint should make unreachable).
    return JSONResponse(
        row.get("response") or {},
        status_code=202,
        headers={"Retry-After": "2"},
    )


async def accept_and_spawn(
    *,
    user_id: UUID,
    operation_id: str,
    request_hash: str,
    accept_body: dict[str, Any],
    pipeline: Callable[[], Awaitable[dict[str, Any]]],
    failure_mapper: Callable[[BaseException, str], dict[str, Any]],
    poll_url_base: str,
    live_tasks: dict[str, asyncio.Task],
    operation_context_cm: Callable[[str], AbstractContextManager[None]] | None = None,
    ttl_seconds: int = 86400,
) -> JSONResponse:
    """Shared accept path: durable record → spawn worker → 202 envelope.

    Returns a retriable 503 (RFC 9457) when the operations store cannot
    durably record the operation — never spawns work the client could
    never poll (ADR-2 fail-closed).

    On duplicate (user_id, request_hash) the canonical op id is returned and
    the accept_body is realigned so the 202 envelope's ``operation_id`` +
    ``status_url`` agree with the canonical id the client should poll.

    ``live_tasks`` is the route family's per-process strong-ref dict; the
    worker task is stored there until the done-callback pops it, both for
    GC protection and as the DELETE cancel target.
    """
    accept_body = dict(accept_body)  # defensive copy — we may mutate operation_id
    try:
        accept_result = await asyncio.to_thread(
            operations_repo.accept,
            user_id=user_id,
            operation_id=operation_id,
            request_hash=request_hash,
            accepted_body=accept_body,
            ttl_seconds=ttl_seconds,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "operations_repo.accept raised in accept_and_spawn (op=%s)",
            operation_id,
        )
        accept_result = None

    if accept_result is None:
        body = _problem_dict(
            status_code=503,
            title="Operation store unavailable",
            detail=(
                "Could not record the operation. Please retry in a moment."
            ),
            type_slug="operation-store-unavailable",
            operation_id=operation_id,
            instance=f"{poll_url_base}/{operation_id}",
            extra={"retryable": True},
        )
        return JSONResponse(
            body,
            status_code=503,
            media_type="application/problem+json",
        )

    canonical_op_id, is_new = accept_result
    if is_new:
        run_task = asyncio.create_task(
            run_worker(
                user_id=user_id,
                operation_id=canonical_op_id,
                pipeline=pipeline,
                failure_mapper=failure_mapper,
                operation_context_cm=operation_context_cm,
            )
        )
        live_tasks[canonical_op_id] = run_task
        run_task.add_done_callback(
            lambda _t, _op=canonical_op_id: live_tasks.pop(_op, None)
        )
    else:
        # Duplicate active request: an existing canonical op already owns
        # this work. The client polls the canonical op id and resolves to
        # the same result.
        accept_body["operation_id"] = canonical_op_id
        accept_body["status_url"] = f"{poll_url_base}/{canonical_op_id}"

    return JSONResponse(
        accept_body,
        status_code=202,
        headers={
            "Location": f"{poll_url_base}/{canonical_op_id}",
            "Retry-After": "2",
        },
    )
