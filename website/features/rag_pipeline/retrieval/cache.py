"""Async in-memory caches for retrieval work."""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import OrderedDict
from typing import Any


class LRUCache:
    """Thread-safe async LRU with TTL."""

    def __init__(self, max_size: int = 512, ttl_seconds: float = 60.0):
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._max = max_size
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            if key not in self._data:
                return None
            ts, value = self._data[key]
            if time.monotonic() - ts > self._ttl:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return value

    async def put(self, key: str, value: Any) -> None:
        async with self._lock:
            self._data[key] = (time.monotonic(), value)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)


def _query_key(query: str) -> str:
    return hashlib.sha256(query.strip().lower().encode()).hexdigest()[:32]


QUERY_EMBEDDING_CACHE = LRUCache(max_size=512, ttl_seconds=300.0)
RETRIEVAL_CACHE = LRUCache(max_size=256, ttl_seconds=60.0)
