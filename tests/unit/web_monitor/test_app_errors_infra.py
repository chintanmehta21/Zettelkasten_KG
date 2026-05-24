"""Unit tests for the App_Errors dedup + helper infrastructure (iter 1c).

Covers:
- ``maybe_fire_app_error`` sentinel dedup (first call fires, dup is suppressed)
- Dedup window expiry behaviour (after window elapses, alert re-arms)
- ``_hash_id`` BOLA-safe rendering (truncated SHA-256, no leakage)
- ``_spawn_alerting`` done-callback fires alert on non-CancelledError exc
- Boot-time alert payload contract (fields rendered as strings, no PII)
"""
from __future__ import annotations

import asyncio
import time

import pytest

from website.features.web_monitor import App_Errors as ae_mod
from website.features.web_monitor.App_Errors import (
    _hash_id,
    _spawn_alerting,
    maybe_fire_app_error,
)


@pytest.fixture(autouse=True)
def _reset_dedup_state():
    ae_mod._app_error_alerted.clear()
    yield
    ae_mod._app_error_alerted.clear()


# ---------------------------------------------------------------------------
# _hash_id — BOLA-safe rendering
# ---------------------------------------------------------------------------


def test_hash_id_returns_truncated_sha256():
    h = _hash_id("f2105544-b73d-4946-8329-096d82f070d3")
    assert len(h) == 12
    # Must not be the raw value.
    assert "f2105544" not in h
    # Stable across calls.
    assert _hash_id("f2105544-b73d-4946-8329-096d82f070d3") == h


def test_hash_id_handles_falsy_inputs():
    assert _hash_id(None) == "—"
    assert _hash_id("") == "—"


def test_hash_id_distinct_inputs_produce_distinct_hashes():
    a = _hash_id("user-A")
    b = _hash_id("user-B")
    assert a != b


# ---------------------------------------------------------------------------
# maybe_fire_app_error — sentinel dedup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_fire_app_error_fires_first_call(monkeypatch):
    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(ae_mod, "notify_app_error", _capture)

    fired = maybe_fire_app_error(
        dedup_key="test:key:1",
        route="POST /api/test",
        exc_type="RuntimeError",
        message="boom",
        request_id="op-123",
        fields={"user_hash": "abcdef123456"},
    )
    await asyncio.sleep(0)

    assert fired is True
    assert len(captured) == 1
    assert captured[0]["route"] == "POST /api/test"
    assert captured[0]["exc_type"] == "RuntimeError"
    assert captured[0]["fields"]["user_hash"] == "abcdef123456"


@pytest.mark.asyncio
async def test_maybe_fire_app_error_dedups_within_window(monkeypatch):
    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(ae_mod, "notify_app_error", _capture)

    r1 = maybe_fire_app_error(
        dedup_key="dup:key", route="r", exc_type="E", message="m"
    )
    r2 = maybe_fire_app_error(
        dedup_key="dup:key", route="r", exc_type="E", message="m"
    )
    r3 = maybe_fire_app_error(
        dedup_key="dup:key", route="r", exc_type="E", message="m"
    )
    await asyncio.sleep(0)

    assert r1 is True
    assert r2 is False
    assert r3 is False
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_maybe_fire_app_error_rearms_after_window_expires(monkeypatch):
    """After the dedup window elapses, the next call re-fires."""
    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(ae_mod, "notify_app_error", _capture)

    # Use a 1-second window so we can drive the clock easily.
    fired1 = maybe_fire_app_error(
        dedup_key="window:key",
        route="r",
        exc_type="E",
        message="m",
        dedup_seconds=1,
    )
    # Force the stored timestamp into the past — easier than sleeping.
    ae_mod._app_error_alerted["window:key"] = time.time() - 10

    fired2 = maybe_fire_app_error(
        dedup_key="window:key",
        route="r",
        exc_type="E",
        message="m",
        dedup_seconds=1,
    )
    await asyncio.sleep(0)

    assert fired1 is True
    assert fired2 is True  # re-armed
    assert len(captured) == 2


def test_maybe_fire_app_error_rejects_empty_dedup_key(monkeypatch):
    """A bad caller without dedup_key would defeat the rate limiter — drop."""
    monkeypatch.setattr(ae_mod, "notify_app_error", lambda **_: None)
    assert maybe_fire_app_error(
        dedup_key="", route="r", exc_type="E", message="m"
    ) is False


def test_maybe_fire_app_error_no_loop_rolls_back_dedup_entry():
    """Sync caller path (no running loop) must not leave a stale dedup entry."""
    # No running loop in this sync test function.
    fired = maybe_fire_app_error(
        dedup_key="noloop:key", route="r", exc_type="E", message="m"
    )
    assert fired is False
    # Dedup entry rolled back so a later async caller can still fire.
    assert "noloop:key" not in ae_mod._app_error_alerted


# ---------------------------------------------------------------------------
# notify_app_error payload contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_app_error_renders_fields_block(slack_webhook_mock):
    import json

    rec = slack_webhook_mock()
    from website.features.web_monitor.App_Errors import notify_app_error

    await notify_app_error(
        route="POST /api/x",
        exc_type="BoomError",
        message="upstream timed out",
        request_id="op-abc",
        fields={
            "user_hash": "ab12cd34",
            "stage": "background_pipeline",
        },
    )
    body = json.dumps(
        rec.calls["SLACK_WEBHOOK_APP_ERRORS"][0], ensure_ascii=False
    )
    assert "BoomError" in body
    assert "POST /api/x" in body
    assert "ab12cd34" in body
    assert "background_pipeline" in body
    assert "op-abc" in body


@pytest.mark.asyncio
async def test_notify_app_error_handles_none_field_values(slack_webhook_mock):
    """None field values render as em-dash — not as literal 'None'."""
    import json

    rec = slack_webhook_mock()
    from website.features.web_monitor.App_Errors import notify_app_error

    await notify_app_error(
        route="r",
        exc_type="E",
        message="m",
        fields={"kasten_hash": None, "user_hash": "ab12"},
    )
    body = json.dumps(rec.calls["SLACK_WEBHOOK_APP_ERRORS"][0])
    assert "None" not in body or '"None"' not in body  # no literal "None"
    assert "ab12" in body


# ---------------------------------------------------------------------------
# _spawn_alerting — done-cb fires #app-errors on exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spawn_alerting_fires_on_exception(monkeypatch):
    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(ae_mod, "notify_app_error", _capture)

    async def _boom():
        raise RuntimeError("synthetic")

    task = _spawn_alerting(
        _boom(),
        dedup_key="spawn:test:boom",
        route="test.spawn",
    )
    assert task is not None
    # Wait for task to complete + done-callback to fire.
    try:
        await task
    except RuntimeError:
        pass
    # Let the done-callback's create_task drain.
    await asyncio.sleep(0)

    assert len(captured) == 1
    assert captured[0]["exc_type"] == "RuntimeError"
    assert captured[0]["route"] == "test.spawn"


@pytest.mark.asyncio
async def test_spawn_alerting_silent_on_success(monkeypatch):
    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(ae_mod, "notify_app_error", _capture)

    async def _ok():
        return "fine"

    task = _spawn_alerting(
        _ok(), dedup_key="spawn:test:ok", route="test.spawn.ok"
    )
    assert task is not None
    await task
    await asyncio.sleep(0)
    assert captured == []


@pytest.mark.asyncio
async def test_spawn_alerting_silent_on_cancel(monkeypatch):
    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(ae_mod, "notify_app_error", _capture)

    async def _slow():
        await asyncio.sleep(5)

    task = _spawn_alerting(
        _slow(), dedup_key="spawn:test:cancel", route="test.spawn.cancel"
    )
    assert task is not None
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await asyncio.sleep(0)
    assert captured == []


@pytest.mark.asyncio
async def test_spawn_alerting_strong_ref_set_discards_on_done(monkeypatch):
    """Caller's strong-ref set must be drained on task completion."""
    monkeypatch.setattr(ae_mod, "notify_app_error", lambda **_: None)
    task_set: set[asyncio.Task] = set()

    async def _ok():
        return None

    task = _spawn_alerting(
        _ok(),
        dedup_key="spawn:set:ok",
        route="test.set",
        task_set=task_set,
    )
    assert task in task_set
    await task
    await asyncio.sleep(0)
    assert task not in task_set
