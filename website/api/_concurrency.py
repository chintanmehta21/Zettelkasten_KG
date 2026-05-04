"""Route-level concurrency primitives: rerank semaphore + bounded queue.

Spec 3.2 -- limit how many in-flight RAG answer streams a single worker will
process before shedding additional load with HTTP 503. With gunicorn
``--workers 2`` each worker has its own pair (semaphore + depth counter); the
combined cap is ``RAG_RERANK_CONCURRENCY * workers`` concurrent reranks and
``RAG_QUEUE_MAX * workers`` queued + in-flight requests cluster-wide.

Env vars:
  - ``RAG_RERANK_CONCURRENCY`` (default 2): simultaneous rerank slots per worker
  - ``RAG_QUEUE_MAX`` (default 8): in-flight + waiting requests per worker
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

# iter-10 P8: opportunistic RSS sampling around slot acquire/release. resource
# is Unix-only (the production droplet). On Windows / non-POSIX hosts the
# import fails silently and the log emits 0 — the structural log line still
# carries depth/queue_max which are the more important fields.
try:
    import resource as _resource  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — Windows dev hosts
    _resource = None  # type: ignore[assignment]


_logger = logging.getLogger("rag.concurrency")

_RSS_LOG_ENABLED = os.environ.get(
    "RAG_SLOT_RSS_LOG_ENABLED", "true"
).lower() not in ("false", "0", "no", "off")


def _rss_kb() -> int:
    """Resident set size in kB; 0 when sampling is unavailable on this host."""
    if _resource is None:
        return 0
    try:
        return int(_resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss)
    except Exception:  # pragma: no cover — defensive
        return 0


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(value, 1)


class QueueFull(Exception):
    """Raised when the bounded rerank queue would overflow."""


class _ConcurrencyState:
    """Holds the semaphore + queue depth. Re-built when env values change so
    tests can monkeypatch ``RAG_QUEUE_MAX`` / ``RAG_RERANK_CONCURRENCY`` and see
    the effect immediately."""

    def __init__(self) -> None:
        self.concurrency = _env_int("RAG_RERANK_CONCURRENCY", 2)
        self.queue_max = _env_int("RAG_QUEUE_MAX", 8)
        self.semaphore = asyncio.Semaphore(self.concurrency)
        self.depth = 0

    def env_changed(self) -> bool:
        return (
            self.concurrency != _env_int("RAG_RERANK_CONCURRENCY", 2)
            or self.queue_max != _env_int("RAG_QUEUE_MAX", 8)
        )


_state: _ConcurrencyState = _ConcurrencyState()


def _get_state() -> _ConcurrencyState:
    global _state
    if _state.env_changed():
        _state = _ConcurrencyState()
    return _state


@asynccontextmanager
async def acquire_rerank_slot():
    """Acquire a rerank slot or raise :class:`QueueFull` if at capacity."""
    state = _get_state()
    rss_pre = _rss_kb() if _RSS_LOG_ENABLED else 0
    if state.depth >= state.queue_max:
        raise QueueFull(f"queue depth {state.depth} >= {state.queue_max}")
    state.depth += 1
    try:
        async with state.semaphore:
            yield
    finally:
        state.depth -= 1
        if _RSS_LOG_ENABLED:
            rss_post = _rss_kb()
            # iter-10 P8: catches OOM-precursor patterns under burst. iter-09
            # droplet logs showed 2 worker SIGKILLs at 780MB / 1GB swap thrash —
            # pre/post delta surfaces who's consuming pages without pulling
            # cgroup logs.
            _logger.info(
                "slot depth=%d/%d rss_pre_kb=%d rss_post_kb=%d delta_kb=%d",
                state.depth, state.queue_max, rss_pre, rss_post, rss_post - rss_pre,
            )


def queue_depth() -> int:
    return _get_state().depth


def reset_for_tests() -> None:
    """Force a fresh state object -- only intended for tests."""
    global _state
    _state = _ConcurrencyState()
