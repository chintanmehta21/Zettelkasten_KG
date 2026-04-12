import asyncio

import pytest

from website.features.rag_pipeline.retrieval.cache import LRUCache


@pytest.mark.asyncio
async def test_get_returns_none_for_missing_key() -> None:
    cache = LRUCache()
    assert await cache.get("missing") is None


@pytest.mark.asyncio
async def test_put_then_get_returns_value() -> None:
    cache = LRUCache()
    await cache.put("a", 1)
    assert await cache.get("a") == 1


@pytest.mark.asyncio
async def test_get_returns_none_after_ttl_expires() -> None:
    cache = LRUCache(ttl_seconds=0.01)
    await cache.put("a", 1)
    await asyncio.sleep(0.02)
    assert await cache.get("a") is None


@pytest.mark.asyncio
async def test_lru_evicts_oldest_when_full() -> None:
    cache = LRUCache(max_size=2, ttl_seconds=60.0)
    await cache.put("a", 1)
    await cache.put("b", 2)
    await cache.put("c", 3)
    assert await cache.get("a") is None
    assert await cache.get("b") == 2
    assert await cache.get("c") == 3

