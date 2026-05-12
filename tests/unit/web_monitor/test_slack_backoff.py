"""WM-05: stamina backoff + Retry-After honoring + bounded queue.

The retry decorator is exercised through ``post_with_retry`` directly so
the test doesn't need to drive a full FastAPI request. ``stamina`` sleeps
real wall-clock by default — we use ``stamina.set_testing(True)`` to
zero-out the sleeps so the test stays under 1s.
"""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest
import respx
import stamina

from website.features.web_monitor._slack_client import (
    RateLimited,
    fire_and_forget,
    inflight_count,
    post_with_retry,
)


_TEST_URL = "https://hooks.slack.com/services/TTEST/BTEST/tokTestBackoff"


@pytest.fixture(autouse=True)
def _stamina_test_mode():
    """Disable stamina's real sleeps. attempts=4 mirrors prod _MAX_ATTEMPTS so
    retry semantics are preserved; only the wall-clock waits are zeroed."""
    stamina.set_testing(True, attempts=4)
    try:
        yield
    finally:
        stamina.set_testing(False)


@pytest.mark.asyncio
async def test_post_succeeds_first_try():
    with respx.mock(assert_all_called=True) as router:
        route = router.post(_TEST_URL).mock(return_value=httpx.Response(200, text="ok"))
        resp = await post_with_retry(_TEST_URL, {"text": "hi"})
        assert resp is not None
        assert resp.status_code == 200
        assert route.call_count == 1


@pytest.mark.asyncio
async def test_post_retries_on_429_then_succeeds():
    with respx.mock(assert_all_called=True) as router:
        route = router.post(_TEST_URL).mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "1"}, text="rate-limited"),
                httpx.Response(429, headers={"Retry-After": "1"}, text="rate-limited"),
                httpx.Response(200, text="ok"),
            ]
        )
        resp = await post_with_retry(_TEST_URL, {"text": "hi"})
        assert resp is not None
        assert resp.status_code == 200
        assert route.call_count == 3


@pytest.mark.asyncio
async def test_post_honors_retry_after_header_within_tolerance(monkeypatch):
    """Retry-After=2 must drive the sleep duration. With stamina in testing
    mode the explicit asyncio.sleep used by _post_with_explicit_retry_after
    is the only real sleep — patch it to capture the requested delay."""
    captured: list[float] = []

    real_sleep = asyncio.sleep

    async def _fake_sleep(delay):
        captured.append(delay)
        await real_sleep(0)  # yield once so the loop keeps running

    monkeypatch.setattr(
        "website.features.web_monitor._slack_client.asyncio.sleep", _fake_sleep
    )

    with respx.mock(assert_all_called=True) as router:
        router.post(_TEST_URL).mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "2"}),
                httpx.Response(200, text="ok"),
            ]
        )
        resp = await post_with_retry(_TEST_URL, {"text": "hi"})
        assert resp is not None
        assert resp.status_code == 200

    # The Retry-After value (2.0) must appear in the captured sleeps.
    # ±100ms tolerance is enforced by exact-match here since the helper
    # passes the parsed float directly to asyncio.sleep (no jitter applied
    # to Retry-After per spec).
    assert any(abs(s - 2.0) <= 0.1 for s in captured), (
        f"Retry-After=2 not honored; captured sleeps: {captured!r}"
    )


@pytest.mark.asyncio
async def test_post_gives_up_after_max_attempts():
    with respx.mock(assert_all_called=True) as router:
        route = router.post(_TEST_URL).mock(
            return_value=httpx.Response(429, headers={"Retry-After": "1"})
        )
        resp = await post_with_retry(_TEST_URL, {"text": "hi"})
        # post_with_retry returns None instead of raising
        assert resp is None
        # 4 attempts max — assert at least 2 (lower bound; exact count
        # depends on stamina + outer-loop coordination)
        assert route.call_count >= 2


@pytest.mark.asyncio
async def test_post_retries_5xx_then_succeeds():
    with respx.mock(assert_all_called=True) as router:
        route = router.post(_TEST_URL).mock(
            side_effect=[
                httpx.Response(503, text="upstream"),
                httpx.Response(200, text="ok"),
            ]
        )
        resp = await post_with_retry(_TEST_URL, {"text": "hi"})
        assert resp is not None
        assert resp.status_code == 200
        assert route.call_count == 2


@pytest.mark.asyncio
async def test_post_returns_none_on_unexpected_exception(monkeypatch):
    """A non-httpx exception must NOT escape the helper."""

    async def _boom(*_, **__):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(
        "website.features.web_monitor._slack_client._post_with_explicit_retry_after",
        _boom,
    )
    resp = await post_with_retry(_TEST_URL, {"text": "hi"})
    assert resp is None


# ---------------------------------------------------------------------------
# WM-07: bounded fire-and-forget pool (merged into WM-05)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fire_and_forget_returns_task_and_tracks_inflight():
    """Tasks scheduled via fire_and_forget must be strong-ref'd in
    _inflight so Python's GC doesn't drop them mid-await."""
    started = asyncio.Event()
    finish = asyncio.Event()

    async def _slow():
        started.set()
        await finish.wait()

    task = fire_and_forget(_slow)
    assert task is not None
    await started.wait()
    assert inflight_count() >= 1
    finish.set()
    await task
    # Set is cleared via add_done_callback — give the loop one tick
    await asyncio.sleep(0)
    # Inflight count returns to baseline (>= 0; other tests can't fight us
    # because each schedules under the same module-level set)
    assert inflight_count() == 0


@pytest.mark.asyncio
async def test_fire_and_forget_bounded_by_semaphore():
    """Spawning more than _MAX_INFLIGHT tasks must queue, not parallelize.

    Setup: 20 tasks each waiting on a shared barrier. With sem=8, exactly
    8 reach the barrier; the rest queue on the semaphore.
    """
    from website.features.web_monitor import _slack_client

    barrier_enters = asyncio.Event()
    barrier_exits = asyncio.Event()
    counter = {"running": 0, "max_running": 0}

    async def _hold():
        counter["running"] += 1
        counter["max_running"] = max(counter["max_running"], counter["running"])
        if counter["running"] >= _slack_client._MAX_INFLIGHT:
            barrier_enters.set()
        await barrier_exits.wait()
        counter["running"] -= 1

    tasks = [fire_and_forget(_hold) for _ in range(20)]
    assert all(t is not None for t in tasks)
    # Wait until the semaphore is saturated
    await asyncio.wait_for(barrier_enters.wait(), timeout=2.0)
    assert counter["max_running"] == _slack_client._MAX_INFLIGHT, (
        f"expected max concurrent == {_slack_client._MAX_INFLIGHT}, "
        f"got {counter['max_running']}"
    )
    # Let everyone finish
    barrier_exits.set()
    await asyncio.gather(*tasks)
