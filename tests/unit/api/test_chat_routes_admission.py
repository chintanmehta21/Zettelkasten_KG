"""iter-09 RES-4: non-stream /adhoc admission wire.

Verifies the new ``async with acquire_rerank_slot()`` wrapper inside
``_run_answer``: QueueFull surfaces as HTTP 503 with ``Retry-After: 5``,
mirroring the SSE path. Without this iter-09 fix, 12-concurrent burst probes
saw depth=0 and admitted indiscriminately (iter-08 burst 25% 502 rate).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from website.api import chat_routes
from website.api._concurrency import QueueFull
from website.features.rag_pipeline.types import ScopeFilter


class _StubBody:
    def __init__(self) -> None:
        self.scope_filter = ScopeFilter()
        self.content = "hi"
        self.quality = "fast"
        self.stream = False


def _stub_session() -> dict:
    return {"id": "00000000-0000-0000-0000-000000000001",
            "sandbox_id": None,
            "title": "Existing"}


def _stub_runtime():
    runtime = MagicMock()

    async def _update(*a, **k):
        return None

    runtime.sessions.update_session = _update
    return runtime


@pytest.mark.asyncio
async def test_run_answer_returns_503_when_queue_full(monkeypatch) -> None:
    """When acquire_rerank_slot raises QueueFull, _run_answer must convert
    it to HTTP 503 with Retry-After: 5 (parity with the SSE error event)."""

    @asynccontextmanager
    async def _full_slot():
        raise QueueFull("queue full")
        yield  # pragma: no cover

    monkeypatch.setattr(chat_routes, "acquire_rerank_slot", _full_slot)

    runtime = _stub_runtime()
    body = _StubBody()
    with pytest.raises(HTTPException) as exc_info:
        await chat_routes._run_answer(
            runtime, "00000000-0000-0000-0000-000000000002", _stub_session(), body
        )
    assert exc_info.value.status_code == 503
    assert exc_info.value.headers.get("Retry-After") == "5"
    detail = exc_info.value.detail
    assert isinstance(detail, dict) and detail.get("code") == "queue_full"


@pytest.mark.asyncio
async def test_run_answer_invokes_orchestrator_inside_slot(monkeypatch) -> None:
    """Sanity: when the slot is open, the orchestrator runs and returns the
    standard (session_id, turn) payload — i.e. the wrap doesn't break the
    happy path."""
    slot_active: list[bool] = []

    @asynccontextmanager
    async def _open_slot():
        slot_active.append(True)
        try:
            yield
        finally:
            slot_active.append(False)

    monkeypatch.setattr(chat_routes, "acquire_rerank_slot", _open_slot)

    runtime = _stub_runtime()

    class _Turn:
        def model_dump(self) -> dict:
            return {"id": "t1"}

    async def _answer(*a, **k):
        # During answer execution the slot must be active.
        assert slot_active and slot_active[-1] is True
        return _Turn()

    async def _side_effects(*a, **k):
        return None

    runtime.orchestrator.answer = _answer
    monkeypatch.setattr(chat_routes, "_post_answer_side_effects", _side_effects)

    body = _StubBody()
    payload = await chat_routes._run_answer(
        runtime, "00000000-0000-0000-0000-000000000002", _stub_session(), body
    )
    assert payload["session_id"] == "00000000-0000-0000-0000-000000000001"
    assert payload["turn"] == {"id": "t1"}
    # Slot opened then closed.
    assert slot_active == [True, False]


@pytest.mark.asyncio
async def test_run_answer_releases_slot_before_side_effects_finish(monkeypatch) -> None:
    """iter-10 P2: post-answer side effects must run AFTER the rerank slot is
    released. Schedules a slow stub side-effects coroutine; verifies the slot
    is already released by the time it observes the slot state."""
    import asyncio

    slot_state: dict = {"in_slot": False}

    @asynccontextmanager
    async def _tracking_slot():
        slot_state["in_slot"] = True
        try:
            yield
        finally:
            slot_state["in_slot"] = False

    monkeypatch.setattr(chat_routes, "acquire_rerank_slot", _tracking_slot)

    runtime = _stub_runtime()

    class _Turn:
        def model_dump(self) -> dict:
            return {"id": "t1"}

    async def _answer(*a, **k):
        return _Turn()

    runtime.orchestrator.answer = _answer

    side_observed: dict = {}
    side_done = asyncio.Event()

    async def _slow_side_effects(*a, **k):
        # Sleep so the request handler returns + slot releases first.
        await asyncio.sleep(0.05)
        side_observed["slot_held_during"] = slot_state["in_slot"]
        side_done.set()

    monkeypatch.setattr(chat_routes, "_post_answer_side_effects", _slow_side_effects)

    body = _StubBody()
    payload = await chat_routes._run_answer(
        runtime, "00000000-0000-0000-0000-000000000002", _stub_session(), body
    )
    # Response returned BEFORE side effects finished.
    assert payload["session_id"] == "00000000-0000-0000-0000-000000000001"
    # Wait for the fire-and-forget task to finish observing the slot state.
    await asyncio.wait_for(side_done.wait(), timeout=2.0)
    assert side_observed["slot_held_during"] is False, (
        "Side effects observed slot still held — slot must release BEFORE "
        "fire-and-forget task body runs."
    )


@pytest.mark.asyncio
async def test_run_answer_isolates_side_effect_exceptions(monkeypatch, caplog) -> None:
    """A failing post-answer side effect MUST NOT 5xx the response. The task
    is best-effort enrichment; failures are logged but the API still returns
    the answer payload."""
    import asyncio
    import logging

    @asynccontextmanager
    async def _open_slot():
        yield

    monkeypatch.setattr(chat_routes, "acquire_rerank_slot", _open_slot)

    runtime = _stub_runtime()

    class _Turn:
        def model_dump(self) -> dict:
            return {"id": "t1"}

    async def _answer(*a, **k):
        return _Turn()

    runtime.orchestrator.answer = _answer

    failed = asyncio.Event()

    async def _exploding_side_effects(*a, **k):
        try:
            raise RuntimeError("supabase down")
        finally:
            failed.set()

    monkeypatch.setattr(chat_routes, "_post_answer_side_effects", _exploding_side_effects)

    body = _StubBody()
    with caplog.at_level(logging.ERROR, logger="website.api.chat_routes"):
        payload = await chat_routes._run_answer(
            runtime, "00000000-0000-0000-0000-000000000002", _stub_session(), body
        )
    assert payload["turn"] == {"id": "t1"}
    await asyncio.wait_for(failed.wait(), timeout=2.0)
    # Give the exception handler a tick to log.
    await asyncio.sleep(0.01)
    assert any(
        "post_answer_side_effects" in r.message.lower() or
        "side effect" in r.message.lower()
        for r in caplog.records
    ), "Failed side effect must be logged"
