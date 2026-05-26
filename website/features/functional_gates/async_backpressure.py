"""Per-user async-ops in-flight backpressure (cross-cutting gate).

Replaces the legacy in-memory LRU cap. Reads the DB once per accept; if the
user already has >= MAX in-flight (status IN queued|running) ops, the route
returns a 429 + RFC 9457 problem body + Retry-After header. Fail-open: any
DB error treats the gate as "open" (zero in-flight) so a transient DB issue
never 5xxs the Add Zettel path.

Reusable across endpoints (future: file upload, chat, etc.) per the
``website/features/functional_gates`` reuse rule.
"""
from __future__ import annotations

import asyncio
import os
from typing import Final
from uuid import UUID

from fastapi.responses import JSONResponse

from website.api._problem import _problem_dict
from website.core import operations_repo


_MAX_IN_FLIGHT_PER_USER: Final[int] = int(
    os.environ.get("ZK_MAX_INFLIGHT_PER_USER", "3")
)
_RETRY_AFTER_SECONDS: Final[int] = int(
    os.environ.get("ZK_BACKPRESSURE_RETRY_AFTER", "30")
)


async def check_async_backpressure(
    *,
    user_id: UUID,
    limit: int | None = None,
    retry_after: int | None = None,
) -> JSONResponse | None:
    """Return a 429 JSONResponse if at/over the per-user in-flight limit.

    Default ``limit`` = env ``ZK_MAX_INFLIGHT_PER_USER`` (default 3).
    Default ``retry_after`` = env ``ZK_BACKPRESSURE_RETRY_AFTER`` (default 30s).

    Sync DB call is dispatched via ``asyncio.to_thread`` to avoid blocking the
    event loop. Fail-open on any exception (returns ``None`` = no backpressure)
    so a transient DB hiccup never 5xxs the accept path; the reaper + per-user
    limit re-converge within minutes.
    """
    eff_limit = limit if limit is not None else _MAX_IN_FLIGHT_PER_USER
    eff_retry = retry_after if retry_after is not None else _RETRY_AFTER_SECONDS
    try:
        count = await asyncio.to_thread(
            operations_repo.count_in_flight_for_user, user_id=user_id
        )
    except (OSError, RuntimeError, asyncio.TimeoutError):
        # Narrow: socket/loop/timeout escapes the inner exception swallow.
        # Programmer-bug exceptions (TypeError, AttributeError) propagate
        # instead of silently fail-opening — pre-PR-#115 mask point.
        # CancelledError is BaseException-derived (3.11+) and so wasn't
        # caught by the prior `except Exception` either; this preserves it.
        return None  # fail-open
    if count < eff_limit:
        return None
    body = _problem_dict(
        status_code=429,
        title="Too many in-flight operations",
        detail=(
            f"User has {count} in-flight operations; limit is {eff_limit}. "
            "Wait for one to finish before submitting another."
        ),
        type_slug="too-many-in-flight",
    )
    return JSONResponse(
        body,
        status_code=429,
        media_type="application/problem+json",
        headers={"Retry-After": str(eff_retry)},
    )
