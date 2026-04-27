"""Unit tests for the rerank semaphore + bounded queue (spec 3.2)."""
from __future__ import annotations

import asyncio

import pytest

from website.api import _concurrency
from website.api._concurrency import (
    QueueFull,
    acquire_rerank_slot,
    queue_depth,
    reset_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    monkeypatch.setenv("RAG_QUEUE_MAX", "2")
    monkeypatch.setenv("RAG_RERANK_CONCURRENCY", "1")
    reset_for_tests()
    yield
    reset_for_tests()


@pytest.mark.asyncio
async def test_queue_full_when_depth_exceeds_max():
    held = asyncio.Event()
    release = asyncio.Event()
    started = asyncio.Event()

    async def hold_slot():
        async with acquire_rerank_slot():
            started.set()
            await release.wait()

    # Two parallel holders fill RAG_QUEUE_MAX=2 (one running, one waiting).
    t1 = asyncio.create_task(hold_slot())
    await started.wait()
    started.clear()
    t2 = asyncio.create_task(hold_slot())
    # Give t2 a chance to enter the context (incrementing depth) before checking.
    await asyncio.sleep(0.05)

    with pytest.raises(QueueFull):
        async with acquire_rerank_slot():
            pass

    release.set()
    await asyncio.gather(t1, t2)


@pytest.mark.asyncio
async def test_queue_depth_decrements_on_release():
    assert queue_depth() == 0
    async with acquire_rerank_slot():
        assert queue_depth() == 1
    assert queue_depth() == 0


@pytest.mark.asyncio
async def test_concurrency_serialises_through_semaphore():
    """RAG_RERANK_CONCURRENCY=1 means at most one slot held at a time."""
    in_flight = 0
    peak = 0

    async def worker():
        nonlocal in_flight, peak
        async with acquire_rerank_slot():
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.02)
            in_flight -= 1

    # Run two workers that should serialise (semaphore of 1) but both fit
    # under queue_max=2.
    await asyncio.gather(worker(), worker())
    assert peak == 1
