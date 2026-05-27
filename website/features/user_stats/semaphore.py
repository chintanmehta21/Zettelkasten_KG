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
        async with self._lock:
            total = self._in_flight + self._waiting
            if total >= self._max_concurrent + self._max_queued:
                raise SemaphoreFullError(
                    f"stats endpoint at capacity ({total}/{self._max_concurrent + self._max_queued})"
                )
            self._waiting += 1
        try:
            await self._sem.acquire()
            async with self._lock:
                self._waiting -= 1
                self._in_flight += 1
            try:
                yield
            finally:
                async with self._lock:
                    self._in_flight -= 1
                self._sem.release()
        except SemaphoreFullError:
            async with self._lock:
                self._waiting -= 1
            raise
