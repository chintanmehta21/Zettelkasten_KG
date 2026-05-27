"""StatsCache tests — TDD per CLAUDE.md test-driven-development rule."""
from __future__ import annotations

import asyncio

import pytest

from website.features.user_stats.cache import StatsCache


@pytest.mark.asyncio
async def test_cache_returns_stored_value():
    cache = StatsCache(max_entries=10, ttl_seconds=60)
    await cache.set("ws1", "etag-a", {"x": 1})
    assert await cache.get("ws1", "etag-a") == {"x": 1}


@pytest.mark.asyncio
async def test_cache_misses_on_different_etag():
    cache = StatsCache(max_entries=10, ttl_seconds=60)
    await cache.set("ws1", "etag-a", {"x": 1})
    assert await cache.get("ws1", "etag-b") is None


@pytest.mark.asyncio
async def test_cache_expires_after_ttl():
    cache = StatsCache(max_entries=10, ttl_seconds=0.05)
    await cache.set("ws1", "etag-a", {"x": 1})
    await asyncio.sleep(0.1)
    assert await cache.get("ws1", "etag-a") is None


@pytest.mark.asyncio
async def test_cache_evicts_lru_when_full():
    cache = StatsCache(max_entries=2, ttl_seconds=60)
    await cache.set("ws1", "a", {"x": 1})
    await cache.set("ws2", "a", {"x": 2})
    await cache.get("ws1", "a")  # mark ws1 as MRU
    await cache.set("ws3", "a", {"x": 3})  # should evict ws2 (oldest)
    assert await cache.get("ws2", "a") is None
    assert await cache.get("ws1", "a") == {"x": 1}
    assert await cache.get("ws3", "a") == {"x": 3}
