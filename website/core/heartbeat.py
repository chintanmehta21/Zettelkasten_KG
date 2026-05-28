"""WM-11 — dead-man-switch canary heartbeat.

Pings healthchecks.io every ``HEARTBEAT_INTERVAL_S`` seconds (default 300).
Absence of pings → healthchecks.io alerts via Slack (#do-alerts) after the
configured grace window. Path bypasses Caddy + Cloudflare deliberately so
the signal proves the droplet container's event loop, not the public
ingress (which is covered separately).

Spec: docs/research/2026-05-12-canary-heartbeat.md (operator-approved 2026-05-12).
Anti-patterns avoided: self-loop pings · event-loop-starvation lying ·
write-path heartbeats · /fail flapping · double-alerting on transient blip.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Callable, Optional

import httpx

logger = logging.getLogger("website.heartbeat")

# 2026-05-28 dedup: pre-fix, every failed beat fired ``logger.exception`` with
# a full traceback every cadence cycle (~288/day at 300s interval). One
# sustained outbound outage drowned out real signals in droplet log triage.
# Now: first failure of a given exception class fires WARNING; subsequent same-
# class failures suppress to DEBUG; a new failure class re-arms WARNING;
# recovery emits an INFO line counting the suppressed streak. No backoff
# cadence (rejected as over-engineering — 0 confirmed firings in the 3-day
# 2026-05-25 → 2026-05-28 droplet log window).
_FAILURE_STATE: dict[str, object] = {"class": None, "count": 0}


def _ping_url() -> Optional[str]:
    """Resolved at call-time so tests can monkeypatch env."""
    return os.environ.get("HEARTBEAT_PING_URL") or None


def _interval_s() -> float:
    raw = os.environ.get("HEARTBEAT_INTERVAL_S", "300")
    try:
        v = float(raw)
        return v if v > 0 else 300.0
    except ValueError:
        return 300.0


async def _one_beat(
    *,
    key_pool_getter: Optional[Callable[[], object]] = None,
    client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
) -> None:
    """Single heartbeat round-trip.

    Medium-deep signal: (1) event-loop alive (this coroutine is running),
    (2) key-pool sanity via ``count_active_keys`` property read — no Gemini
    API call (no upstream amplification), (3) outbound HTTPS to hc-ping.com.
    Skipped silently when ``HEARTBEAT_PING_URL`` unset.
    """
    url = _ping_url()
    if not url:
        return  # disabled

    keys_active = -1  # sentinel: pool not wired
    if key_pool_getter is not None:
        try:
            pool = key_pool_getter()
            if pool is not None and hasattr(pool, "count_active_keys"):
                keys_active = int(pool.count_active_keys())
        except Exception:  # noqa: BLE001 — never let pool-introspection block ping
            logger.debug("heartbeat: key_pool introspection failed", exc_info=True)

    body = f"keys_active={keys_active}"
    async with client_factory(timeout=10.0) as client:
        await client.post(url, content=body)


async def heartbeat_loop(
    stop: asyncio.Event,
    *,
    key_pool_getter: Optional[Callable[[], object]] = None,
) -> None:
    """Run heartbeat beats until ``stop`` is set.

    Cancellation-safe via ``asyncio.wait_for(stop.wait(), timeout=interval)``
    — the canonical FastAPI lifespan-cancel pattern. Bare ``asyncio.sleep``
    would swallow blue/green cutover cancels for up to ``interval`` seconds.
    """
    if not _ping_url():
        logger.info("heartbeat disabled: HEARTBEAT_PING_URL unset")
        return

    interval = _interval_s()
    logger.info("heartbeat enabled: cadence=%.0fs", interval)
    while not stop.is_set():
        try:
            await _one_beat(key_pool_getter=key_pool_getter)
        except Exception as exc:  # noqa: BLE001 — never raise out of the loop
            # Transient blip → no Slack alert from here. The absence-of-ping
            # after the healthchecks.io grace window will produce one. See
            # anti-pattern #5 (double-alerting on the same incident).
            exc_class = type(exc).__name__
            if exc_class == _FAILURE_STATE["class"]:
                # Same failure class as the previous cycle — suppress to DEBUG.
                _FAILURE_STATE["count"] = int(_FAILURE_STATE["count"]) + 1  # type: ignore[arg-type]
                logger.debug(
                    "heartbeat beat failed (suppressed; %d consecutive %s)",
                    _FAILURE_STATE["count"],
                    exc_class,
                )
            else:
                # First failure ever, or new failure class — re-arm WARNING.
                logger.exception("heartbeat beat failed; continuing")
                _FAILURE_STATE["class"] = exc_class
                _FAILURE_STATE["count"] = 1
        else:
            # Successful beat — if we were in a failure streak, log recovery.
            count = int(_FAILURE_STATE["count"])  # type: ignore[arg-type]
            if count > 0:
                logger.info(
                    "heartbeat recovered after %d suppressed %s failures",
                    count,
                    _FAILURE_STATE["class"],
                )
                _FAILURE_STATE["class"] = None
                _FAILURE_STATE["count"] = 0
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
