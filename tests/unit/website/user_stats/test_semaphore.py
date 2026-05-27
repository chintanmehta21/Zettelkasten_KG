"""StatsSemaphore tests — per-worker bounded queue for the User Stats route.

Architecture audit §4: max 1 concurrent stats request per gunicorn worker,
queue depth 2, 503 backpressure above. With 2 workers = 2 concurrent total,
4 queued at most.
"""
from __future__ import annotations

import asyncio

import pytest

from website.features.user_stats.semaphore import (
    SemaphoreFullError,
    StatsSemaphore,
)


@pytest.mark.asyncio
async def test_semaphore_allows_max_concurrent():
    """Permit count = 1; one concurrent acquire succeeds."""
    sem = StatsSemaphore(max_concurrent=1, max_queued=2)
    async with sem.acquire():
        pass  # should not raise


@pytest.mark.asyncio
async def test_semaphore_rejects_when_queue_full():
    """When max_concurrent + max_queued slots are taken, raise SemaphoreFullError."""
    sem = StatsSemaphore(max_concurrent=1, max_queued=1)
    held = asyncio.Event()
    released = asyncio.Event()

    async def hold():
        async with sem.acquire():
            held.set()
            await released.wait()

    async def queue():
        async with sem.acquire():
            pass

    # Hold the only permit
    holder_task = asyncio.create_task(hold())
    await held.wait()
    # Queue one (within max_queued)
    queued_task = asyncio.create_task(queue())
    await asyncio.sleep(0.05)
    # Third should reject
    with pytest.raises(SemaphoreFullError):
        async with sem.acquire():
            pass
    released.set()
    await holder_task
    await queued_task


@pytest.mark.asyncio
async def test_semaphore_releases_on_exception():
    """If body raises, the permit must still be released."""
    sem = StatsSemaphore(max_concurrent=1, max_queued=0)
    with pytest.raises(ValueError):
        async with sem.acquire():
            raise ValueError("boom")
    # Should be reacquirable
    async with sem.acquire():
        pass


@pytest.mark.asyncio
async def test_counters_remain_clean_after_rejection():
    """After a SemaphoreFullError, _waiting must not underflow.

    Regression test for the bug where the except handler decremented a
    counter that was never incremented.
    """
    sem = StatsSemaphore(max_concurrent=1, max_queued=1)
    held = asyncio.Event()
    released = asyncio.Event()

    async def hold():
        async with sem.acquire():
            held.set()
            await released.wait()

    async def queue():
        async with sem.acquire():
            pass

    holder_task = asyncio.create_task(hold())
    await held.wait()
    queued_task = asyncio.create_task(queue())
    await asyncio.sleep(0.05)
    with pytest.raises(SemaphoreFullError):
        async with sem.acquire():
            pass

    released.set()
    await holder_task
    await queued_task

    # All counters back to zero — no underflow from the rejection path.
    assert sem._waiting == 0
    assert sem._in_flight == 0

    # And the gate is still functional (next acquire succeeds).
    async with sem.acquire():
        pass
    assert sem._waiting == 0
    assert sem._in_flight == 0


@pytest.mark.asyncio
async def test_cancellation_mid_wait_restores_waiting():
    """If a queued caller is cancelled while parked on the inner semaphore,
    _waiting must be decremented in the finally block.

    Regression test for the cancellation-leak that would otherwise poison
    the gate over time.
    """
    sem = StatsSemaphore(max_concurrent=1, max_queued=2)
    held = asyncio.Event()
    released = asyncio.Event()

    async def hold():
        async with sem.acquire():
            held.set()
            await released.wait()

    async def queue():
        async with sem.acquire():
            pass

    holder_task = asyncio.create_task(hold())
    await held.wait()

    # Queue a caller, then cancel it while it's parked.
    queued_task = asyncio.create_task(queue())
    await asyncio.sleep(0.05)
    queued_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued_task

    # Cancelled wait must NOT leak _waiting.
    assert sem._waiting == 0

    # Release the holder and verify the gate is still functional.
    released.set()
    await holder_task
    async with sem.acquire():
        pass
    assert sem._waiting == 0
    assert sem._in_flight == 0
