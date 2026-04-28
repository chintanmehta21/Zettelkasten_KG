"""Stress tests for the iter-03 burst capacity primitives.

Exercises:
  * ``website.api._concurrency.acquire_rerank_slot`` under N concurrent acquirers
  * ``website.api.chat_routes._heartbeat_wrapper`` under N concurrent slow streams

These run in unit-test land — no network, no real model. They verify the
in-process invariants (queue cap, semaphore cap, heartbeat liveness) hold
under burst.

Run:
    python -m pytest tests/stress -v
"""
from __future__ import annotations

import asyncio

import pytest

from website.api import _concurrency, chat_routes
from website.api._concurrency import (
    QueueFull,
    acquire_rerank_slot,
    queue_depth,
    reset_for_tests,
)


@pytest.fixture(autouse=True)
def _scoped_state(monkeypatch):
    monkeypatch.setenv("RAG_QUEUE_MAX", "8")
    monkeypatch.setenv("RAG_RERANK_CONCURRENCY", "2")
    reset_for_tests()
    yield
    reset_for_tests()


@pytest.mark.asyncio
async def test_burst_50_acquirers_respects_queue_cap():
    """Spawn 50 acquirers; only 8 should ever be in queue, rest get QueueFull."""
    accepted = 0
    rejected = 0
    peak_depth = 0
    release = asyncio.Event()

    async def worker():
        nonlocal accepted, rejected, peak_depth
        try:
            async with acquire_rerank_slot():
                nonlocal_peak = queue_depth()
                if nonlocal_peak > peak_depth:
                    peak_depth = nonlocal_peak
                accepted += 1
                await release.wait()
        except QueueFull:
            rejected += 1

    tasks = [asyncio.create_task(worker()) for _ in range(50)]
    await asyncio.sleep(0.05)  # let everyone race for the queue
    release.set()
    await asyncio.gather(*tasks, return_exceptions=True)

    assert accepted + rejected == 50
    assert accepted <= 8, f"queue cap breached: {accepted} accepted"
    assert rejected >= 42, f"too few rejections: {rejected}"
    assert peak_depth <= 8


@pytest.mark.asyncio
async def test_burst_semaphore_serializes_to_concurrency_limit():
    """Even within the queue, only RAG_RERANK_CONCURRENCY=2 may execute at once."""
    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    async def worker():
        nonlocal in_flight, max_in_flight
        async with acquire_rerank_slot():
            async with lock:
                in_flight += 1
                if in_flight > max_in_flight:
                    max_in_flight = in_flight
            await asyncio.sleep(0.02)
            async with lock:
                in_flight -= 1

    # 8 simultaneous workers fit the queue; only 2 should execute concurrently.
    await asyncio.gather(*(worker() for _ in range(8)))
    assert max_in_flight <= 2, f"semaphore breached: {max_in_flight} concurrent"


@pytest.mark.asyncio
async def test_heartbeat_survives_concurrent_slow_streams(monkeypatch):
    """Run 12 concurrent _heartbeat_wrapper instances; each must emit ≥1 heartbeat
    when its inner generator stalls past the heartbeat interval."""
    monkeypatch.setattr(chat_routes, "SSE_HEARTBEAT_INTERVAL_SECONDS", 0.05)

    async def stalled_inner():
        yield "data: start\n\n"
        await asyncio.sleep(0.25)  # 5x heartbeat interval
        yield "data: end\n\n"

    async def consume() -> list[str]:
        out: list[str] = []
        async for item in chat_routes._heartbeat_wrapper(stalled_inner()):
            out.append(item)
        return out

    streams = await asyncio.gather(*(consume() for _ in range(12)))
    assert len(streams) == 12
    for stream in streams:
        heartbeats = [x for x in stream if x == ": heartbeat\n\n"]
        assert len(heartbeats) >= 2, f"missing heartbeats in stream: {stream!r}"
        assert "data: start\n\n" in stream and "data: end\n\n" in stream


@pytest.mark.asyncio
async def test_queue_depth_returns_to_zero_after_burst():
    """After a burst settles, depth must be 0 — no leaked counter."""
    async def quick():
        try:
            async with acquire_rerank_slot():
                await asyncio.sleep(0.005)
        except QueueFull:
            pass

    await asyncio.gather(*(quick() for _ in range(40)))
    assert queue_depth() == 0


@pytest.mark.asyncio
async def test_memory_guard_detect_mem_max_returns_sane_int():
    """Sanity: _detect_mem_max returns a non-zero int when the harness is
    running on a real host (or test harness with a writable proc). On
    GitHub Actions / Linux this should be > 0; on macOS / Windows hosts
    where /proc + cgroup are absent, it falls back to /proc/meminfo OR 0.
    The point of this test is to ensure the fallback chain doesn't crash."""
    from website.api import _memory_guard
    value = _memory_guard._detect_mem_max()
    assert isinstance(value, int)
    assert value >= 0
