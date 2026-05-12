"""WAVE-C 1c-A.3 — UserGraphCache single-flight + invalidation tests.

Locked decisions covered:
- D-KG-6: in-process LRU cap=200 · TTL=30s · per-user lock · 20s timeout
- D-KG-7: full-invalidate on summarize / zettel mutation
- bucket key isolation across users (BOLA / OWASP API1:2023)

These are async unit tests against the cache module — they do NOT hit
Supabase, so they run with the rest of the suite without `--live`. The file
sits under tests/integration/v2/ to colocate with the other graph-API tests
even though it doesn't use the asyncpg_pool fixture.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from website.api.graph_cache import (
    UserGraphCache,
    bucket_for_strength,
    get_default_cache,
)


# ── Bucket key derivation ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "weak"),
        (0.0, "weak"),
        (0.39, "weak"),
        (0.4, "medium"),
        (0.69, "medium"),
        (0.7, "strong"),
        (1.0, "strong"),
        ("not-a-number", "weak"),
    ],
)
def test_bucket_for_strength_matches_d_kg_3(value, expected) -> None:
    assert bucket_for_strength(value) == expected


# ── Cache hit + invalidate round-trip ───────────────────────────────────


async def test_cache_hit_then_invalidate_round_trip() -> None:
    cache = UserGraphCache(capacity=10, ttl_seconds=60.0)
    user_id = "user-1"
    bucket = "strong"
    call_count = 0

    async def loader() -> dict:
        nonlocal call_count
        call_count += 1
        return {"nodes": [{"id": "a"}], "links": []}

    # Cold load.
    p1 = await cache.get_or_load(user_id, bucket, loader)
    # Warm hit.
    p2 = await cache.get_or_load(user_id, bucket, loader)
    assert p1 == p2
    assert call_count == 1, "warm hit must not invoke loader"

    # Invalidate → next load goes cold again.
    removed = cache.invalidate(user_id)
    assert removed >= 1
    await cache.get_or_load(user_id, bucket, loader)
    assert call_count == 2, "post-invalidate must reload"


# ── Single-flight: 50 concurrent → 1 upstream call ──────────────────────


async def test_single_flight_coalesces_concurrent_loads() -> None:
    cache = UserGraphCache(capacity=10, ttl_seconds=60.0)
    user_id = "user-coalesce"
    bucket = "weak"
    call_count = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_loader() -> dict:
        nonlocal call_count
        call_count += 1
        started.set()
        # Hold the loader so all 50 callers stack on the inflight Future.
        await release.wait()
        return {"nodes": [], "links": [], "marker": call_count}

    async def caller() -> dict:
        return await cache.get_or_load(user_id, bucket, slow_loader)

    tasks = [asyncio.create_task(caller()) for _ in range(50)]

    # Wait until the elected loader is in-flight, then release it.
    await started.wait()
    release.set()

    payloads = await asyncio.gather(*tasks)
    assert call_count == 1, f"single-flight failed: {call_count} upstream calls"
    # All 50 responses are the SAME object (Future result is shared).
    assert all(p == payloads[0] for p in payloads)


# ── Cache key isolation across users (BOLA / UUID-leak) ────────────────


async def test_cache_key_isolation_across_users() -> None:
    cache = UserGraphCache(capacity=10, ttl_seconds=60.0)

    async def loader_for(uid: str):
        async def _l() -> dict:
            return {"nodes": [{"id": f"node-of-{uid}"}], "links": []}

        return _l

    user_alice = str(uuid.uuid4())
    user_bob = str(uuid.uuid4())

    p_alice = await cache.get_or_load(user_alice, "strong", await loader_for(user_alice))
    p_bob = await cache.get_or_load(user_bob, "strong", await loader_for(user_bob))

    assert p_alice["nodes"][0]["id"] == f"node-of-{user_alice}"
    assert p_bob["nodes"][0]["id"] == f"node-of-{user_bob}"

    # Invalidating Alice MUST NOT touch Bob.
    cache.invalidate(user_alice)
    assert (user_alice, "strong") not in cache.keys()
    assert (user_bob, "strong") in cache.keys()

    # OWASP API1:2023 BOLA pattern — even if a buggy caller passed Alice's
    # uid into Bob's slot, the per-tuple key prevents cross-tenant payload
    # leak. Confirm by direct lookup.
    bob_cached = await cache.get_or_load(user_bob, "strong", await loader_for(user_bob))
    assert user_alice not in str(bob_cached)


# ── LRU cap honored at burst ──────────────────────────────────────────


async def test_lru_cap_honored_under_burst() -> None:
    cap = 50
    cache = UserGraphCache(capacity=cap, ttl_seconds=60.0)

    async def make_loader(idx: int):
        async def _l() -> dict:
            return {"nodes": [{"id": f"n-{idx}"}], "links": []}

        return _l

    # 600 distinct users hitting the cache → store should never exceed cap.
    for i in range(600):
        loader = await make_loader(i)
        await cache.get_or_load(f"user-{i}", "weak", loader)
        assert len(cache) <= cap, f"LRU cap exceeded at iter {i}: len={len(cache)}"

    assert len(cache) == cap


# ── TTL expiry triggers reload ──────────────────────────────────────────


async def test_ttl_expiry_triggers_reload() -> None:
    cache = UserGraphCache(capacity=10, ttl_seconds=0.05)
    user_id = "ttl-user"
    call_count = 0

    async def loader() -> dict:
        nonlocal call_count
        call_count += 1
        return {"nodes": [], "links": []}

    await cache.get_or_load(user_id, "weak", loader)
    assert call_count == 1
    # Wait past TTL.
    await asyncio.sleep(0.1)
    await cache.get_or_load(user_id, "weak", loader)
    assert call_count == 2, "expired entry must trigger reload"


# ── Loader exception is propagated, inflight cleared ───────────────────


async def test_loader_exception_clears_inflight() -> None:
    cache = UserGraphCache(capacity=10, ttl_seconds=60.0)

    class _BoomError(RuntimeError):
        pass

    async def broken() -> dict:
        raise _BoomError("upstream boom")

    with pytest.raises(_BoomError):
        await cache.get_or_load("user-x", "weak", broken)

    # Inflight slot must be cleared so the next call retries cleanly.
    assert cache.inflight_count() == 0
    # And not cached.
    assert ("user-x", "weak") not in cache.keys()


# ── Default singleton accessor stable ─────────────────────────────────


def test_get_default_cache_is_singleton() -> None:
    a = get_default_cache()
    b = get_default_cache()
    assert a is b


# ── Single-flight error path: no N+1 upstream calls under burst ────────


async def test_single_flight_error_path_does_not_n_plus_1() -> None:
    """50 concurrent callers + upstream raising must yield exactly 1 loader call.

    Regression for PR #7 C2: prior order was `_inflight.pop()` then
    `future.set_exception()`. A follower entering the gap saw neither a
    cached entry nor an inflight Future and triggered its own upstream load.
    The fix swaps the order under one lock acquisition so followers always
    observe the inflight Future, attach to it, and receive the same exception.
    """
    cache = UserGraphCache(capacity=10, ttl_seconds=60.0)
    user_id = "user-error-coalesce"
    bucket = "weak"
    call_count = 0
    started = asyncio.Event()
    release = asyncio.Event()

    class _BoomError(RuntimeError):
        pass

    async def slow_broken_loader() -> dict:
        nonlocal call_count
        call_count += 1
        started.set()
        # Hold so all 50 callers stack on the same inflight Future before we
        # raise — the burst window is what exposes the race.
        await release.wait()
        raise _BoomError("upstream boom")

    async def caller():
        try:
            return await cache.get_or_load(user_id, bucket, slow_broken_loader)
        except _BoomError as exc:
            return exc

    tasks = [asyncio.create_task(caller()) for _ in range(50)]

    # Wait for the elected loader to be in-flight, then release it.
    await started.wait()
    release.set()

    results = await asyncio.gather(*tasks)
    assert call_count == 1, (
        f"single-flight error path failed: {call_count} upstream calls "
        f"(expected 1). Followers raced into a fresh load instead of "
        f"attaching to the inflight Future."
    )
    # All 50 followers got the same exception type.
    assert all(isinstance(r, _BoomError) for r in results)
    # Inflight slot cleared so subsequent retries work.
    assert cache.inflight_count() == 0
