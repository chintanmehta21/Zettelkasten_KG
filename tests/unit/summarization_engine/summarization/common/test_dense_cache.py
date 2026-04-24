"""Unit tests for the per-URL DenseVerify LRU cache.

Covers:
- eviction at capacity (LRU order),
- TTL expiry drops the entry on lookup,
- ``get_or_compute`` hits cache on second call (compute not re-invoked),
- ``cache_key_for_url`` is stable + hex sha1.
"""
from __future__ import annotations

import pytest

from website.features.summarization_engine.summarization.common.dense_cache import (
    LRUCache,
    cache_key_for_url,
)


@pytest.mark.asyncio
async def test_eviction_at_capacity():
    cache: LRUCache[int] = LRUCache(maxsize=2, ttl=1000)
    await cache.set("a", 1)
    await cache.set("b", 2)
    await cache.set("c", 3)  # evicts "a" (LRU)
    assert await cache.get("a") is None
    assert await cache.get("b") == 2
    assert await cache.get("c") == 3
    assert len(cache) == 2


@pytest.mark.asyncio
async def test_lru_order_preserves_most_recently_used():
    cache: LRUCache[int] = LRUCache(maxsize=2, ttl=1000)
    await cache.set("a", 1)
    await cache.set("b", 2)
    # Re-access "a" so it becomes MRU, pushing "b" to LRU.
    _ = await cache.get("a")
    await cache.set("c", 3)  # evicts "b"
    assert await cache.get("b") is None
    assert await cache.get("a") == 1
    assert await cache.get("c") == 3


@pytest.mark.asyncio
async def test_ttl_expiry_drops_entry():
    now = {"t": 0.0}

    def fake_clock() -> float:
        return now["t"]

    cache: LRUCache[str] = LRUCache(maxsize=10, ttl=10, clock=fake_clock)
    await cache.set("k", "v")
    assert await cache.get("k") == "v"
    # Advance past TTL.
    now["t"] = 20.0
    assert await cache.get("k") is None
    assert len(cache) == 0


@pytest.mark.asyncio
async def test_get_or_compute_hits_cache_on_second_call():
    cache: LRUCache[str] = LRUCache(maxsize=4, ttl=1000)
    calls = {"n": 0}

    async def _compute() -> str:
        calls["n"] += 1
        return "value"

    v1 = await cache.get_or_compute("key", _compute)
    v2 = await cache.get_or_compute("key", _compute)
    assert v1 == v2 == "value"
    assert calls["n"] == 1  # compute ran exactly once


@pytest.mark.asyncio
async def test_get_or_compute_recomputes_after_expiry():
    now = {"t": 0.0}

    def fake_clock() -> float:
        return now["t"]

    cache: LRUCache[int] = LRUCache(maxsize=4, ttl=5, clock=fake_clock)
    calls = {"n": 0}

    async def _compute() -> int:
        calls["n"] += 1
        return 42

    await cache.get_or_compute("key", _compute)
    now["t"] = 100.0  # past TTL
    await cache.get_or_compute("key", _compute)
    assert calls["n"] == 2


def test_cache_key_is_stable_and_hex_sha1():
    k1 = cache_key_for_url("https://example.com/post")
    k2 = cache_key_for_url("https://example.com/post")
    assert k1 == k2
    assert len(k1) == 40
    assert all(c in "0123456789abcdef" for c in k1)


def test_cache_key_differs_for_distinct_urls():
    k1 = cache_key_for_url("https://example.com/a")
    k2 = cache_key_for_url("https://example.com/b")
    assert k1 != k2


def test_invalid_constructor_args_raise():
    with pytest.raises(ValueError):
        LRUCache(maxsize=0, ttl=10)
    with pytest.raises(ValueError):
        LRUCache(maxsize=10, ttl=0)
