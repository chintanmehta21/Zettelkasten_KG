"""Unit tests for maybe_fire_app_error_rate (iter 1d Tier C).

Sliding-window rate gate used for Tier C alerts (Gemini hard 5xx burst,
pgvector timeout, credential-stuffing, kg-populate failures). Verifies:
- Below-threshold ticks don't fire.
- Threshold crossing fires exactly once (alert is dedup'd at the inner gate).
- Expired entries leave the window so a quiet period re-arms.
- Bounded distinct-key set (FIFO eviction).
- Empty dedup_key is rejected.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from website.features.web_monitor import App_Errors as ae_mod
from website.features.web_monitor.App_Errors import maybe_fire_app_error_rate


@pytest.fixture(autouse=True)
def _reset_state():
    ae_mod._app_error_alerted.clear()
    ae_mod._app_error_rate_buckets.clear()
    yield
    ae_mod._app_error_alerted.clear()
    ae_mod._app_error_rate_buckets.clear()


@pytest.mark.asyncio
async def test_rate_gate_does_not_fire_below_threshold(monkeypatch):
    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(ae_mod, "notify_app_error", _capture)

    for _ in range(4):
        maybe_fire_app_error_rate(
            dedup_key="rate:test:5xx",
            threshold=5,
            window_seconds=60,
            route="r",
            exc_type="E",
            message="m",
        )
    await asyncio.sleep(0)
    assert captured == []


@pytest.mark.asyncio
async def test_rate_gate_fires_at_threshold(monkeypatch):
    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(ae_mod, "notify_app_error", _capture)

    fired_any = False
    for _ in range(5):
        fired_any = (
            maybe_fire_app_error_rate(
                dedup_key="rate:test:burst",
                threshold=5,
                window_seconds=60,
                route="r",
                exc_type="E",
                message="m",
            )
            or fired_any
        )
    await asyncio.sleep(0)
    assert fired_any is True
    assert len(captured) == 1
    # Threshold + count metadata flow through the inner alert.
    assert captured[0]["fields"]["count_in_window"] == "5"
    assert captured[0]["fields"]["threshold"] == "5"


@pytest.mark.asyncio
async def test_rate_gate_dedups_inner_alert_within_alert_window(monkeypatch):
    """Crossing the threshold every tick beyond threshold must not re-alert
    until alert_dedup_seconds elapses."""
    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(ae_mod, "notify_app_error", _capture)

    for _ in range(20):
        maybe_fire_app_error_rate(
            dedup_key="rate:test:flood",
            threshold=3,
            window_seconds=60,
            route="r",
            exc_type="E",
            message="m",
            alert_dedup_seconds=15 * 60,
        )
    await asyncio.sleep(0)
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_rate_gate_expires_old_entries(monkeypatch):
    """Stale entries outside the window must be evicted so a quiet period
    re-arms the gate."""
    monkeypatch.setattr(ae_mod, "notify_app_error", lambda **_: None)

    # Manually populate the bucket with timestamps from 2 minutes ago.
    key = "rate:test:expire"
    ae_mod._app_error_rate_buckets[key] = [time.time() - 120 for _ in range(10)]

    # One new tick with window=60s should evict ALL old entries and not fire.
    fired = maybe_fire_app_error_rate(
        dedup_key=key,
        threshold=5,
        window_seconds=60,
        route="r",
        exc_type="E",
        message="m",
    )
    assert fired is False
    # Bucket should now hold ONLY the fresh tick.
    assert len(ae_mod._app_error_rate_buckets[key]) == 1


def test_rate_gate_rejects_empty_dedup_key():
    assert (
        maybe_fire_app_error_rate(
            dedup_key="",
            threshold=5,
            window_seconds=60,
            route="r",
            exc_type="E",
            message="m",
        )
        is False
    )


@pytest.mark.asyncio
async def test_rate_gate_bounded_key_space(monkeypatch):
    """Adding more than _APP_ERROR_RATE_KEYS_MAX distinct keys must evict
    the oldest via FIFO. Prevents unbounded growth under per-IP key spaces."""
    monkeypatch.setattr(ae_mod, "notify_app_error", lambda **_: None)
    monkeypatch.setattr(ae_mod, "_APP_ERROR_RATE_KEYS_MAX", 5)

    for i in range(8):
        maybe_fire_app_error_rate(
            dedup_key=f"rate:test:per_ip:{i}",
            threshold=100,  # never alerts; just inserts the key
            window_seconds=60,
            route="r",
            exc_type="E",
            message="m",
        )
    # The first 3 should have been evicted.
    assert len(ae_mod._app_error_rate_buckets) == 5
    assert "rate:test:per_ip:0" not in ae_mod._app_error_rate_buckets
    assert "rate:test:per_ip:7" in ae_mod._app_error_rate_buckets
