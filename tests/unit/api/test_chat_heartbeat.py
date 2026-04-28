"""Unit tests for the SSE heartbeat wrapper (1B.4).

When the inner stream stalls, the wrapper must yield ``: heartbeat\\n\\n``
roughly every SSE_HEARTBEAT_INTERVAL_SECONDS so Cloudflare/Caddy keep the
connection alive. Real events still pass through unchanged.
"""
from __future__ import annotations

import asyncio

import pytest

from website.api import chat_routes


@pytest.fixture(autouse=True)
def _fast_heartbeat(monkeypatch):
    monkeypatch.setattr(chat_routes, "SSE_HEARTBEAT_INTERVAL_SECONDS", 0.05)
    yield


async def _collect(gen, max_items=20, deadline_s=2.0):
    out = []
    try:
        async with asyncio.timeout(deadline_s):
            async for item in gen:
                out.append(item)
                if len(out) >= max_items:
                    break
    except (asyncio.TimeoutError, TimeoutError):
        pass
    return out


@pytest.mark.asyncio
async def test_real_events_pass_through_without_heartbeat():
    async def fast():
        yield "data: a\n\n"
        yield "data: b\n\n"

    out = await _collect(chat_routes._heartbeat_wrapper(fast()))
    assert out == ["data: a\n\n", "data: b\n\n"]


@pytest.mark.asyncio
async def test_heartbeat_emitted_when_idle():
    async def stalled():
        yield "data: first\n\n"
        await asyncio.sleep(0.3)  # 6x heartbeat interval
        yield "data: second\n\n"

    out = await _collect(chat_routes._heartbeat_wrapper(stalled()), max_items=10)
    heartbeats = [x for x in out if x == ": heartbeat\n\n"]
    assert len(heartbeats) >= 2, f"expected ≥2 heartbeats, got {out!r}"
    assert "data: first\n\n" in out
    assert "data: second\n\n" in out


@pytest.mark.asyncio
async def test_inner_exception_does_not_leak_consumer_task():
    async def boom():
        yield "data: ok\n\n"
        raise RuntimeError("boom")

    out = await _collect(chat_routes._heartbeat_wrapper(boom()))
    assert "data: ok\n\n" in out
