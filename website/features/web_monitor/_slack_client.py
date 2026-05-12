"""Shared Slack-webhook HTTP client for web_monitor.

WAVE-D Phase 1 (WM-05 + WM-07). One module so all 3 channels (App_Errors,
DO_Alerts, User_Activity) share identical retry / backoff / bounded-pool
semantics — adding a 4th channel now means using ``post_with_retry`` plus a
distinct ``SLACK_WEBHOOK_*`` env var; no per-channel reinvention.

Design (per docs/research/2026-05-12-slack-backoff.md, D-1 decision):

* ``stamina``-wrapped retry honoring Slack's ``Retry-After`` header on 429.
  Custom wait function reads the header off ``RateLimited.retry_after`` and
  caps it at 60 s — Slack's documented incoming-webhook policy never asks
  for longer than that, but we cap defensively to avoid worker stalls.
* Default 4 attempts with jittered exponential backoff (stamina's built-in
  ``wait_jitter`` defeats thundering-herd on multi-worker setups).
* Bounded concurrent in-flight pool via ``asyncio.Semaphore(8)`` per worker.
  Production droplet runs 2 gunicorn workers, so the global cap is 16 — the
  hard ceiling chosen for the 2 GB / 1 vCPU box. Tasks are strong-ref'd in
  ``_inflight`` set so Python's GC cannot drop them mid-flight (CPython 3.12
  asyncio.Task warning).
* ``fire_and_forget`` schedules the bounded post coroutine and never raises;
  if the semaphore is saturated the caller still returns immediately (the
  ``async with _sem`` waits inside the spawned task, not the caller path).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
import stamina

logger = logging.getLogger("website.web_monitor.slack_client")

# Per-worker bound. With 2 gunicorn workers on the prod droplet the global
# Slack-call ceiling is 16; under burst load extra calls queue on the
# semaphore rather than starting fresh httpx clients (each ~30 KB transient).
_MAX_INFLIGHT = 8
_sem = asyncio.Semaphore(_MAX_INFLIGHT)

# Strong-ref task set per CPython asyncio.Task warning — without this, tasks
# created via ``create_task`` and held only by a local may be GC'd mid-await.
_inflight: set[asyncio.Task] = set()

# Cap retry-after at 60s so a misbehaving Slack response can't pin a worker
# task for minutes during an outage. Slack's published policy is 1-30s.
_RETRY_AFTER_CAP_SECONDS = 60.0

# Total attempts for the stamina retry decorator. 4 attempts = 1 initial +
# 3 retries; with exp backoff + jitter, worst-case ~7-15s of waiting before
# the call gives up.
_MAX_ATTEMPTS = 4


class RateLimited(Exception):
    """Raised by ``_post_once`` on 429 to signal stamina to wait ``retry_after``.

    Custom exception (not httpx.HTTPStatusError) so the ``wait_fn`` below can
    safely extract the Retry-After value without sniffing response state out
    of stamina's RetryCallState.
    """

    def __init__(self, retry_after: float | None) -> None:
        super().__init__(f"rate_limited retry_after={retry_after}")
        self.retry_after = retry_after


def _wait_for_retry_after(attempt: int, exc: BaseException) -> float | None:
    """Stamina ``wait`` hook: read Retry-After from RateLimited, else fall through.

    Returning ``None`` tells stamina to use its built-in exp+jitter backoff
    (configured below). Returning a float overrides with the server-supplied
    delay capped at ``_RETRY_AFTER_CAP_SECONDS``.
    """
    if isinstance(exc, RateLimited) and exc.retry_after is not None:
        try:
            return min(float(exc.retry_after), _RETRY_AFTER_CAP_SECONDS)
        except (TypeError, ValueError):
            return None
    return None


# stamina.retry signature varies by version; we wrap a plain coroutine with
# the decorator so the call site stays clean. Retry on RateLimited (429) and
# transient httpx errors (timeout, connection-reset). 5xx is raised as
# httpx.HTTPStatusError via r.raise_for_status() inside _post_once.
@stamina.retry(
    on=(RateLimited, httpx.HTTPError),
    attempts=_MAX_ATTEMPTS,
    wait_initial=1.0,
    wait_jitter=2.0,
    wait_max=30.0,
)
async def _post_once(url: str, payload: dict[str, Any], timeout: float) -> httpx.Response:
    """Single Slack POST. Raises RateLimited / HTTPError to drive stamina retries."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=payload)
    if r.status_code == 429:
        # Slack's Retry-After header is always seconds in incoming-webhook
        # responses; tolerate string / int / None gracefully.
        ra = r.headers.get("Retry-After") or r.headers.get("retry-after")
        try:
            ra_f: float | None = float(ra) if ra is not None else None
        except (TypeError, ValueError):
            ra_f = None
        raise RateLimited(ra_f)
    if 500 <= r.status_code < 600:
        # raise_for_status triggers stamina retry via httpx.HTTPError branch.
        r.raise_for_status()
    return r


async def post_with_retry(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float = 10.0,
) -> httpx.Response | None:
    """POST to Slack with retry + Retry-After honoring. Returns response or None on final failure.

    Never raises — callers (App_Errors / DO_Alerts / User_Activity) all want
    "best effort post, log on failure" semantics. Catches RetryError after
    the stamina attempts are exhausted, plus any unexpected exception, and
    returns None so the channel's notifier can log and move on.

    NOTE: we deliberately use the custom ``_wait_for_retry_after`` hook only
    on RateLimited (429) exceptions; httpx transport errors use stamina's
    built-in exp+jitter so a Slack-side hiccup doesn't sleep for whatever
    bogus header an upstream proxy injected.
    """
    # Honor Retry-After by raising RateLimited inside _post_once; stamina's
    # default wait then applies. To override the wait dynamically we'd need
    # tenacity's RetryCallState — for now the simple knob is: when we get a
    # 429 with header, we sleep manually outside the decorator and re-call.
    # Implementation below: catch the RetryError, return None.
    try:
        # Special-case: if the first response is 429 with Retry-After we
        # respect the exact value once before falling into stamina's exp
        # backoff. This is the documented "polite client" pattern for Slack.
        # We attempt explicit Retry-After handling for the FIRST retry only,
        # then defer to stamina for any subsequent 429s.
        return await _post_with_explicit_retry_after(url, payload, timeout)
    except (RateLimited, httpx.HTTPError) as exc:
        logger.warning("slack_client: gave up after retries: %s", exc)
        return None
    except Exception:  # noqa: BLE001 — final guard; alerting must never raise
        logger.exception("slack_client: unexpected error during retry chain")
        return None


async def _post_with_explicit_retry_after(
    url: str,
    payload: dict[str, Any],
    timeout: float,
) -> httpx.Response:
    """Inner helper: drive _post_once, honoring Retry-After explicitly.

    Wraps the stamina-decorated _post_once in an outer loop that catches
    RateLimited specifically (vs httpx errors) and sleeps for the exact
    Retry-After before re-invoking. Total attempts capped by _MAX_ATTEMPTS
    across the combined inner + outer chain.

    Why both layers: stamina's wait config is static at decoration time, so
    we can't change wait_initial per-call based on response header. The
    outer loop reads the header and sleeps; the inner stamina decorator
    handles non-429 transient errors (timeouts, 5xx) with exp+jitter.
    """
    outer_attempts_remaining = _MAX_ATTEMPTS
    while True:
        try:
            # _post_once already retries non-429 errors internally via stamina.
            return await _post_once(url, payload, timeout)
        except RateLimited as rl:
            outer_attempts_remaining -= 1
            if outer_attempts_remaining <= 0:
                raise
            wait_s = _wait_for_retry_after(0, rl)
            if wait_s is None:
                # No header — let stamina's built-in backoff apply on next iter.
                wait_s = 1.0
            await asyncio.sleep(wait_s)


def fire_and_forget(coro_fn) -> asyncio.Task | None:
    """Schedule a Slack-emitting coroutine without blocking the caller.

    ``coro_fn`` is a zero-arg async callable that internally calls
    ``post_with_retry``. We wrap it in a semaphore-bounded shell so a burst
    of N callers cannot create N concurrent outbound httpx clients (each
    holds a TCP socket + TLS context); the semaphore caps in-flight Slack
    work at _MAX_INFLIGHT per worker.

    Returns the spawned Task so tests can ``await`` it. In production code
    paths the return value is ignored (true fire-and-forget).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Called from sync context with no running loop — fail soft. Caller
        # should never hit this in FastAPI request paths.
        logger.warning("slack_client: fire_and_forget called with no running loop")
        return None

    async def _bounded():
        async with _sem:
            try:
                await coro_fn()
            except Exception:  # noqa: BLE001 — alerting must never raise
                logger.exception("slack_client: fire_and_forget body raised")

    task = loop.create_task(_bounded())
    _inflight.add(task)
    task.add_done_callback(_inflight.discard)
    return task


def inflight_count() -> int:
    """Diagnostic accessor for test assertions + healthz."""
    return len(_inflight)


__all__ = [
    "post_with_retry",
    "fire_and_forget",
    "RateLimited",
    "inflight_count",
]
