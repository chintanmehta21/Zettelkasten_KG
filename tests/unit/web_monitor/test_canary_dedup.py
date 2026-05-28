"""P3 — heartbeat first-WARN-then-suppress dedup.

Pre-fix: ``heartbeat_loop`` calls ``logger.exception("heartbeat beat failed;
continuing")`` on EVERY failed beat. A sustained outbound outage produces one
ERROR + full traceback per cadence cycle (~288/day), masking real signals in
``journalctl`` / log triage.

Post-fix: same exception class repeating is suppressed to DEBUG after the
first WARNING; recovery emits an INFO line counting suppressed failures;
a different exception class re-arms the WARNING (new failure mode).

No exponential backoff cadence — that was rejected as over-engineering during
the devil's-advocate sweep.
"""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import patch

import httpx
import pytest

from website.core import heartbeat as canary


@pytest.fixture(autouse=True)
def _reset_failure_state():
    """Ensure module-level dedup state doesn't bleed across tests."""
    yield
    canary._FAILURE_STATE["class"] = None
    canary._FAILURE_STATE["count"] = 0


async def _run_n_beats(monkeypatch, side_effects, n_beats: int) -> None:
    """Drive heartbeat_loop through ``n_beats`` rounds with the given side-effects."""
    monkeypatch.setenv("HEARTBEAT_PING_URL", "https://hc-ping.com/test-uuid")
    monkeypatch.setenv("HEARTBEAT_INTERVAL_S", "0.01")
    stop = asyncio.Event()

    call_count = {"n": 0}

    async def _beat(*a, **kw):
        i = call_count["n"]
        call_count["n"] += 1
        effect = side_effects[min(i, len(side_effects) - 1)]
        if isinstance(effect, BaseException):
            raise effect

    with patch.object(canary, "_one_beat", side_effect=_beat):
        task = asyncio.create_task(canary.heartbeat_loop(stop))
        # Wait long enough for n_beats * interval beats to complete.
        await asyncio.sleep(0.02 * n_beats + 0.05)
        stop.set()
        await asyncio.wait_for(task, timeout=1.0)


@pytest.mark.asyncio
async def test_repeated_failure_same_class_is_suppressed_after_first(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="website.heartbeat")
    err = httpx.ConnectError("network down")
    await _run_n_beats(monkeypatch, [err, err, err, err], n_beats=4)

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING and "heartbeat beat failed" in r.message]
    debug_suppressed = [r for r in caplog.records if r.levelno == logging.DEBUG and "suppressed" in r.message]

    assert len(warnings) == 1, f"expected exactly 1 WARNING, got {len(warnings)}: {[r.message for r in warnings]}"
    assert len(debug_suppressed) >= 2, f"expected >=2 suppressed DEBUG lines after first WARNING, got {len(debug_suppressed)}"


@pytest.mark.asyncio
async def test_recovery_after_failure_emits_info_count(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="website.heartbeat")
    err = httpx.ConnectError("network down")
    # 2 failures (same class), then success
    await _run_n_beats(monkeypatch, [err, err, None, None], n_beats=4)

    recovery = [r for r in caplog.records if r.levelno == logging.INFO and "recovered" in r.message]
    assert len(recovery) >= 1, f"expected INFO recovery line, got {[r.message for r in caplog.records if r.levelno==logging.INFO]}"
    # Recovery message should cite the failure count (>=2)
    assert any("ConnectError" in r.message for r in recovery), "recovery line should name the failure class"


@pytest.mark.asyncio
async def test_different_failure_class_re_arms_warning(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="website.heartbeat")
    err_a = httpx.ConnectError("network down")
    err_b = httpx.TimeoutException("read timeout")
    await _run_n_beats(monkeypatch, [err_a, err_a, err_b, err_b], n_beats=4)

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING and "heartbeat beat failed" in r.message]
    # Two distinct failure classes → 2 WARNING lines (one per class transition)
    assert len(warnings) == 2, f"expected 2 WARNINGs (one per failure class), got {len(warnings)}"
