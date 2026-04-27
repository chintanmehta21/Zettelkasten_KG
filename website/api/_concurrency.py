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
import os
from contextlib import asynccontextmanager


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
    if state.depth >= state.queue_max:
        raise QueueFull(f"queue depth {state.depth} >= {state.queue_max}")
    state.depth += 1
    try:
        async with state.semaphore:
            yield
    finally:
        state.depth -= 1


def queue_depth() -> int:
    return _get_state().depth


def reset_for_tests() -> None:
    """Force a fresh state object -- only intended for tests."""
    global _state
    _state = _ConcurrencyState()
