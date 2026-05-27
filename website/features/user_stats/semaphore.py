"""Per-worker bounded queue for the stats endpoint.

Architecture audit §4: max 1 concurrent stats request per gunicorn worker,
queue depth 2, 503 backpressure above. With 2 workers = 2 concurrent total,
4 queued at most. Prevents OLTP starvation on 2 GB / 1 vCPU droplet.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator


class SemaphoreFullError(RuntimeError):
    """Raised when both active permits and queue are exhausted."""


class StatsSemaphore:
    """Bounded async semaphore with explicit queue depth + typed backpressure.

    Two-counter accounting (``_in_flight`` and ``_waiting``) lets the gate raise
    ``SemaphoreFullError`` BEFORE parking a new caller when the queue is full —
    the route layer maps that to HTTP 503. State invariants are restored on
    both ``SemaphoreFullError`` (rejection before increment) and on cancellation
    or any other exception while parked on the underlying ``asyncio.Semaphore``.
    """

    def __init__(self, *, max_concurrent: int = 1, max_queued: int = 2) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        if max_queued < 0:
            raise ValueError("max_queued must be >= 0")
        self._max_concurrent = max_concurrent
        self._max_queued = max_queued
        self._sem = asyncio.Semaphore(max_concurrent)
        self._in_flight = 0
        self._waiting = 0
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[None]:
        # Entry gate: raise FullError BEFORE incrementing _waiting so the
        # cleanup path has nothing to undo on this raise.
        async with self._lock:
            total = self._in_flight + self._waiting
            if total >= self._max_concurrent + self._max_queued:
                raise SemaphoreFullError(
                    f"stats endpoint at capacity ({total}/{self._max_concurrent + self._max_queued})"
                )
            self._waiting += 1

        acquired = False
        try:
            await self._sem.acquire()
            acquired = True
            async with self._lock:
                self._waiting -= 1
                self._in_flight += 1
            try:
                yield
            finally:
                async with self._lock:
                    self._in_flight -= 1
                self._sem.release()
        finally:
            # Cancellation or any exception BEFORE acquire() returned must
            # restore _waiting — otherwise the counter poisons the gate.
            if not acquired:
                async with self._lock:
                    self._waiting -= 1
