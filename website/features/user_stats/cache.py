"""Per-worker in-process LRU cache for the User Stats response.

Keyed by (workspace_id, etag). TTL-based expiry. Bounded by max_entries
with LRU eviction. asyncio.Lock for concurrent-safe ordered-dict updates
(microsecond cost — well under any DB query budget).

The route layer computes the ETag from a probe RPC + caps_config_version
sentinel BEFORE consulting this cache, so a cache hit means "(workspace,
upstream-state, caps-state) all unchanged" — safe to return without
re-running the full SECURITY DEFINER aggregation.
"""
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any


class StatsCache:
    """Per-worker async-safe LRU with TTL."""

    def __init__(self, *, max_entries: int = 256, ttl_seconds: float = 60.0) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        self._max = max_entries
        self._ttl = ttl_seconds
        self._store: OrderedDict[tuple[str, str], tuple[float, Any]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, workspace_id: str, etag: str) -> Any | None:
        key = (workspace_id, etag)
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            ts, value = entry
            if time.monotonic() - ts > self._ttl:
                self._store.pop(key, None)
                return None
            self._store.move_to_end(key)
            return value

    async def set(self, workspace_id: str, etag: str, value: Any) -> None:
        key = (workspace_id, etag)
        async with self._lock:
            self._store[key] = (time.monotonic(), value)
            self._store.move_to_end(key)
            while len(self._store) > self._max:
                self._store.popitem(last=False)

    async def clear(self) -> None:
        """Drop all entries — used by ops endpoints and test cleanup."""
        async with self._lock:
            self._store.clear()
