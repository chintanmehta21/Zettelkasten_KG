"""App_Errors — alert fan-out for FastAPI uncaught exceptions / 5xx.

One file, one Slack channel: `#app-errors`. Self-contained (its own Slack
posting helper) so it can be reasoned about without looking at siblings.

Wiring (already done in website/app.py):

    from website.features.web_monitor.App_Errors import notify_app_error
    from starlette.responses import JSONResponse

    @app.exception_handler(Exception)
    async def _on_unhandled(request, exc):
        await notify_app_error(
            route=request.url.path,
            exc_type=type(exc).__name__,
            message=str(exc)[:400],
            request_id=request.headers.get("x-request-id"),
        )
        return JSONResponse({"error": "internal_server_error"}, status_code=500)

This module has no inbound HTTP endpoint — app errors originate in our own
code, not from external webhooks. The only public surface is
`notify_app_error()` plus an optional `router` with a healthz check.

Env vars:
    SLACK_WEBHOOK_APP_ERRORS    # Slack incoming webhook URL for #app-errors
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter

from website.features.web_monitor._slack_client import post_with_retry

logger = logging.getLogger("website.web_monitor.app_errors")

router = APIRouter(prefix="/webhooks/monitor", tags=["web_monitor.app_errors"])

SLACK_ENV_VAR = "SLACK_WEBHOOK_APP_ERRORS"

# Dedup state for maybe_fire_app_error. Same sentinel + bounded-LRU pattern
# as web_monitor.User_Activity._signup_alerted. Keyed by caller-supplied
# dedup_key (typically "<route>:<exc_type>" or "<route>:<id_hash>") so the
# same upstream incident does not flood the channel. Each replica owns its
# own map; worst case during blue/green cutover = ~2 alerts per incident.
_APP_ERROR_DEDUP_MAX = 5000
_APP_ERROR_DEDUP_SECONDS = 15 * 60       # default 1 alert / dedup_key / 15 min
_app_error_alerted: "OrderedDict[str, float]" = OrderedDict()

# Rate-gate buckets for maybe_fire_app_error_rate. Each bucket is a list of
# event timestamps within the rate window; older entries are evicted on each
# tick. Bounded set of distinct keys (FIFO eviction) so a runaway key-space
# (e.g. per-IP) cannot grow unbounded under a scanner storm.
_APP_ERROR_RATE_KEYS_MAX = 5000
_app_error_rate_buckets: "OrderedDict[str, list[float]]" = OrderedDict()


# ---------------------------------------------------------------------------
# Slack posting
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SlackMessage:
    title: str
    body: str
    severity: str = "critical"         # info | warning | critical
    fields: dict[str, str] | None = None
    source: str = "app"

    def to_payload(self) -> dict[str, Any]:
        color = {
            "info": "#2E86AB",
            "warning": "#D4A024",
            "critical": "#C83E4D",
        }.get(self.severity, "#C83E4D")
        fields = [
            {"type": "mrkdwn", "text": f"*{k}*\n{v}"}
            for k, v in (self.fields or {}).items()
        ]
        blocks: list[dict[str, Any]] = [
            {"type": "header", "text": {"type": "plain_text", "text": self.title}},
            {"type": "section", "text": {"type": "mrkdwn", "text": self.body}},
        ]
        if fields:
            blocks.append({"type": "section", "fields": fields[:10]})
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"source: `{self.source}` · severity: `{self.severity}`",
                    }
                ],
            }
        )
        return {"attachments": [{"color": color, "blocks": blocks}]}


async def post_to_app_errors(msg: SlackMessage) -> bool:
    """POST a Slack message to #app-errors. Returns True on 2xx.

    Never raises — a failed alert must not escalate into a failed response.
    WM-05: delegates to _slack_client.post_with_retry which honors Slack's
    Retry-After on 429 and applies exp+jitter backoff for transient errors.
    """
    url = os.getenv(SLACK_ENV_VAR)
    if not url:
        logger.warning(
            "app_errors: %s unset; alert logged only: %s", SLACK_ENV_VAR, msg.title
        )
        # Structured contract: level=info, channel name embedded.
        logger.info("ALERT[app_errors] %s — %s", msg.title, msg.body)
        return False
    response = await post_with_retry(url, msg.to_payload())
    if response is None:
        logger.error("app_errors: Slack post gave up after retries: %s", msg.title)
        return False
    if not (200 <= response.status_code < 300):
        # B-4: never log response.text — Slack echoes payload fragments that
        # may include PII / log-injection content. Status + reason + length
        # are sufficient for triage; body is fetched only at WARN level in
        # exceptional debug sessions, never in standard error logging.
        logger.error(
            "app_errors: Slack post failed status=%s reason=%s body_len=%s",
            response.status_code,
            response.reason_phrase,
            len(response.text),
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Public notifier
# ---------------------------------------------------------------------------


async def notify_app_error(
    *,
    route: str,
    exc_type: str,
    message: str,
    request_id: str | None = None,
    fields: dict[str, str] | None = None,
    severity: str = "critical",
) -> None:
    """Post an uncaught exception / 5xx description to #app-errors.

    Called from the FastAPI global exception handler and from explicit
    instrumentation points in background tasks / streaming routes that the
    global handler can't see (post-202 worker, mid-stream SSE generators).
    Never raises — alerting must never be in the critical response path.

    Args:
        route: request path or logical alert site (e.g. ``/api/zettels/add``,
            ``async_pipeline_run``, ``razorpay_webhook``).
        exc_type: class name of the exception (e.g. ``ValueError``).
        message: stringified exception — truncate before calling if huge.
        request_id: optional x-request-id header value for trace correlation.
        fields: optional extra metadata rendered in the Slack fields block —
            use BOLA-safe truncated/hashed identifiers (``_hash_id``) for
            user/kasten/workspace ids; NEVER include raw cross-tenant UUIDs.
        severity: ``info`` | ``warning`` | ``critical`` (default).
    """
    merged_fields: dict[str, str] = {"request_id": request_id or "—"}
    if fields:
        for k, v in fields.items():
            if v is None:
                merged_fields[k] = "—"
            else:
                merged_fields[k] = str(v)[:200]
    msg = SlackMessage(
        title=f":boom: {exc_type} on {route}",
        body=f"```{message[:900]}```",
        severity=severity,
        fields=merged_fields,
        source="app",
    )
    try:
        await post_to_app_errors(msg)
    except Exception:  # noqa: BLE001
        logger.exception("app_errors: notify_app_error dispatch failed")


# ---------------------------------------------------------------------------
# Dedup helpers — for callers that need idempotent alerting (post-202 workers,
# webhook handlers replayed by upstream, background tasks).
# ---------------------------------------------------------------------------


def _hash_id(value: str | None, *, prefix_len: int = 12) -> str:
    """BOLA-safe identifier rendering for alert payloads.

    Returns a short SHA-256 prefix of ``value``; never the raw UUID.
    Matches the OWASP API1:2023 BOLA contract: an alert must not allow a
    Slack viewer (or an attacker reading exfiltrated logs) to recover the
    cross-tenant resource id. ``"—"`` for falsy inputs so the Slack field
    block stays uniform.
    """
    if not value:
        return "—"
    digest = hashlib.sha256(str(value).encode("utf-8", "ignore")).hexdigest()
    return digest[:prefix_len]


def maybe_fire_app_error(
    *,
    dedup_key: str,
    route: str,
    exc_type: str,
    message: str,
    request_id: str | None = None,
    fields: dict[str, str] | None = None,
    severity: str = "critical",
    dedup_seconds: int = _APP_ERROR_DEDUP_SECONDS,
) -> bool:
    """Schedule a #app-errors alert iff ``dedup_key`` hasn't fired recently.

    The dedup is per-replica (in-memory). Same sentinel-based atomic check-
    and-set as :func:`web_monitor.User_Activity.maybe_fire_signup_alert`:
    plain ``time.time()`` markers collide on Windows' coarse clock, so we
    use ``object()`` identity for the winning insert.

    Returns True if an alert task was scheduled, False if dedup'd. Never
    raises — alerting must never break the caller. Falls back to
    ``logger.warning`` when invoked outside a running event loop.
    """
    if not dedup_key:
        # Safety net: a missing dedup key would defeat the rate limiter.
        # Treat as "do not alert" rather than letting one bad caller flood.
        logger.warning("app_errors: maybe_fire_app_error called without dedup_key")
        return False

    sentinel = object()
    prev = _app_error_alerted.setdefault(dedup_key, sentinel)
    if prev is not sentinel:
        # Already alerted under this key. If the dedup window has passed,
        # re-arm INLINE (overwrite the stored timestamp) and continue to
        # the fire path. Recursion was tail-only but added a maintenance
        # smell flagged in the iter-1f code review — inline is clearer.
        if isinstance(prev, float) and (time.time() - prev) > dedup_seconds:
            _app_error_alerted[dedup_key] = time.time()
            _app_error_alerted.move_to_end(dedup_key)
        else:
            return False
    else:
        _app_error_alerted[dedup_key] = time.time()
    if len(_app_error_alerted) > _APP_ERROR_DEDUP_MAX:
        _app_error_alerted.popitem(last=False)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning(
            "app_errors: maybe_fire_app_error called outside event loop (dedup_key=%s)",
            dedup_key,
        )
        # Roll back so a later async caller can still fire.
        _app_error_alerted.pop(dedup_key, None)
        return False
    loop.create_task(
        notify_app_error(
            route=route,
            exc_type=exc_type,
            message=message,
            request_id=request_id,
            fields=fields,
            severity=severity,
        )
    )
    return True


def maybe_fire_app_error_rate(
    *,
    dedup_key: str,
    threshold: int,
    window_seconds: int,
    route: str,
    exc_type: str,
    message: str,
    request_id: str | None = None,
    fields: dict[str, str] | None = None,
    severity: str = "warning",
    alert_dedup_seconds: int = 5 * 60,
) -> bool:
    """Sliding-window rate gate — fires #app-errors only when sustained.

    Used for Tier C alerts where a single event is noise but a burst is
    signal (Gemini 5xx burst, pgvector timeout, credential-stuffing, etc.).
    Tick the counter; if ``count_in_window >= threshold`` AND we haven't
    alerted on this dedup_key in the last ``alert_dedup_seconds``, fire.

    Implementation: per-key list of timestamps within ``window_seconds``;
    expired entries are pruned on each tick. Cheap (~10 µs per call) and
    bounded by ``_APP_ERROR_RATE_KEYS_MAX`` distinct keys.

    Returns True if an alert was scheduled, False otherwise.
    """
    if not dedup_key:
        return False
    now = time.time()
    bucket = _app_error_rate_buckets.get(dedup_key)
    if bucket is None:
        if len(_app_error_rate_buckets) >= _APP_ERROR_RATE_KEYS_MAX:
            _app_error_rate_buckets.popitem(last=False)
        bucket = []
        _app_error_rate_buckets[dedup_key] = bucket
    cutoff = now - window_seconds
    # Drop expired entries from the head. List-based deque is fine at our
    # threshold scale (≤ a few hundred entries per key); for >10k events
    # we'd switch to collections.deque.
    while bucket and bucket[0] < cutoff:
        bucket.pop(0)
    bucket.append(now)
    _app_error_rate_buckets.move_to_end(dedup_key)
    if len(bucket) < threshold:
        return False
    # Threshold breached — funnel through maybe_fire_app_error so the alert
    # itself is still deduped on a longer window (no flapping).
    extra_fields = dict(fields or {})
    extra_fields.setdefault("count_in_window", str(len(bucket)))
    extra_fields.setdefault("threshold", str(threshold))
    extra_fields.setdefault("window_seconds", str(window_seconds))
    return maybe_fire_app_error(
        dedup_key=f"rate:{dedup_key}",
        route=route,
        exc_type=exc_type,
        message=message,
        request_id=request_id,
        fields=extra_fields,
        severity=severity,
        dedup_seconds=alert_dedup_seconds,
    )


def _spawn_alerting(
    coro,
    *,
    dedup_key: str,
    route: str,
    task_set: "set[asyncio.Task] | None" = None,
    severity: str = "critical",
) -> "asyncio.Task | None":
    """Schedule a fire-and-forget task that alerts to #app-errors if it raises.

    ``coro`` is the coroutine to run (matches the ``asyncio.create_task``
    convention). ``task_set`` is an optional strong-ref set the caller
    maintains to keep the task alive past CPython 3.12's eager-GC behaviour
    for unreferenced Tasks. The done-callback inspects ``task.exception()``
    and dispatches ``maybe_fire_app_error`` on a non-None, non-CancelledError
    result. Returns the Task (so caller may ``await`` in tests) or ``None``
    if no event loop is running.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning(
            "app_errors: _spawn_alerting called outside event loop (route=%s)", route
        )
        # Close the unconsumed coroutine to avoid the "coroutine was never
        # awaited" RuntimeWarning leak.
        try:
            coro.close()
        except Exception:  # noqa: BLE001 — defensive
            pass
        return None

    task = loop.create_task(coro)
    if task_set is not None:
        task_set.add(task)

    def _done(t: asyncio.Task) -> None:
        if task_set is not None:
            task_set.discard(t)
        try:
            exc = t.exception()
        except (asyncio.CancelledError, asyncio.InvalidStateError):
            return
        if exc is None or isinstance(exc, asyncio.CancelledError):
            return
        maybe_fire_app_error(
            dedup_key=dedup_key,
            route=route,
            exc_type=type(exc).__name__,
            message=str(exc)[:400],
            severity=severity,
        )

    task.add_done_callback(_done)
    return task


# ---------------------------------------------------------------------------
# Healthz (no inbound webhook — just a config probe)
# ---------------------------------------------------------------------------


@router.get("/app-errors/healthz")
async def app_errors_healthz() -> dict[str, Any]:
    return {
        "ok": True,
        "channel": "app_errors",
        "webhook_configured": bool(os.getenv(SLACK_ENV_VAR)),
    }


__all__ = [
    "router",
    "SlackMessage",
    "post_to_app_errors",
    "notify_app_error",
    "maybe_fire_app_error",
    "maybe_fire_app_error_rate",
    "_hash_id",
    "_spawn_alerting",
]
