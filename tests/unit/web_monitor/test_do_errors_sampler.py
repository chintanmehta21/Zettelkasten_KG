"""Unit tests for the DO_Errors memory + asyncio-task sampler (iter 1e).

Drives the sampler through synthetic /proc readings + asyncio.all_tasks
overrides to verify:
- PSI threshold + sustained-samples + hysteresis
- Cgroup memory ratio threshold + hysteresis
- asyncio task count threshold + hysteresis
- maybe_fire_do_error dedup
- Sampler degrades gracefully when /proc files are absent (dev / macOS)
"""
from __future__ import annotations

import asyncio

import pytest

from website.features.web_monitor import DO_Errors as do_mod
from website.features.web_monitor.DO_Errors import (
    MemorySampler,
    maybe_fire_do_error,
)


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    do_mod._do_error_alerted.clear()
    do_mod._sampler = None
    yield
    do_mod._do_error_alerted.clear()
    do_mod._sampler = None


# ---------------------------------------------------------------------------
# maybe_fire_do_error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_fire_do_error_fires_first_call(monkeypatch):
    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(do_mod, "notify_do_error", _capture)

    fired = maybe_fire_do_error(
        dedup_key="test:psi",
        title=":fire: PSI breach",
        body="kernel stalling",
        severity="critical",
        fields={"psi_full_avg10_pct": "12.5"},
    )
    await asyncio.sleep(0)

    assert fired is True
    assert len(captured) == 1
    assert captured[0]["title"] == ":fire: PSI breach"
    assert captured[0]["fields"]["psi_full_avg10_pct"] == "12.5"


@pytest.mark.asyncio
async def test_maybe_fire_do_error_dedups_within_window(monkeypatch):
    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(do_mod, "notify_do_error", _capture)

    for _ in range(5):
        maybe_fire_do_error(
            dedup_key="test:dup", title="t", body="b"
        )
    await asyncio.sleep(0)
    assert len(captured) == 1


def test_maybe_fire_do_error_rejects_empty_dedup_key():
    assert maybe_fire_do_error(dedup_key="", title="t", body="b") is False


# ---------------------------------------------------------------------------
# PSI threshold + sustained + hysteresis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_psi_fires_after_sustained_samples_and_rearms(monkeypatch):
    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(do_mod, "notify_do_error", _capture)

    sampler = MemorySampler(interval_seconds=60)
    # /proc unavailable for non-PSI signals so they don't fire.
    monkeypatch.setattr(do_mod, "_read_cgroup_mem_ratio", lambda: (None, None, None))
    monkeypatch.setattr(do_mod, "_read_asyncio_task_count", lambda: 0)

    # Sample 1: above critical — breach=1, NOT YET fired (needs 2 samples).
    monkeypatch.setattr(do_mod, "_read_psi_full_avg10", lambda: 12.0)
    sampler.sample_once()
    assert sampler.state.psi_breach == 1
    assert sampler.state.psi_armed_severity is None

    # Sample 2: still above critical — breach=2, FIRES.
    sampler.sample_once()
    await asyncio.sleep(0)
    assert sampler.state.psi_breach == 2
    assert sampler.state.psi_armed_severity == "critical"
    assert len(captured) == 1
    assert captured[0]["fields"]["psi_full_avg10_pct"] == "12.00"

    # Sample 3: drops into safe band — counter resets + armed flag cleared.
    monkeypatch.setattr(do_mod, "_read_psi_full_avg10", lambda: 0.5)
    sampler.sample_once()
    assert sampler.state.psi_breach == 0
    assert sampler.state.psi_armed_severity is None

    # Sample 4-5: above critical AGAIN — re-arms and fires fresh alert (via
    # the maybe_fire_do_error dedup window which is 15 min by default; for
    # the test we manually clear the dedup state).
    do_mod._do_error_alerted.clear()
    captured.clear()
    monkeypatch.setattr(do_mod, "_read_psi_full_avg10", lambda: 11.5)
    sampler.sample_once()
    sampler.sample_once()
    await asyncio.sleep(0)
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_psi_below_critical_does_not_fire(monkeypatch):
    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(do_mod, "notify_do_error", _capture)
    monkeypatch.setattr(do_mod, "_read_cgroup_mem_ratio", lambda: (None, None, None))
    monkeypatch.setattr(do_mod, "_read_asyncio_task_count", lambda: 0)
    # Sit in the WARN band (5-10%) — should NOT fire critical.
    monkeypatch.setattr(do_mod, "_read_psi_full_avg10", lambda: 7.0)

    sampler = MemorySampler(interval_seconds=60)
    for _ in range(5):
        sampler.sample_once()
    await asyncio.sleep(0)
    assert captured == []
    # In-between band: breach counter stays at 0 (doesn't increment, but
    # doesn't reset either — that's only on the SAFE band).
    assert sampler.state.psi_armed_severity is None


# ---------------------------------------------------------------------------
# Cgroup memory threshold + hysteresis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cgroup_mem_fires_above_90pct_sustained(monkeypatch):
    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(do_mod, "notify_do_error", _capture)
    monkeypatch.setattr(do_mod, "_read_psi_full_avg10", lambda: None)
    monkeypatch.setattr(do_mod, "_read_asyncio_task_count", lambda: 0)
    monkeypatch.setattr(
        do_mod,
        "_read_cgroup_mem_ratio",
        lambda: (0.92, 1_500_000_000, 1_600_000_000),
    )

    sampler = MemorySampler(interval_seconds=60)
    sampler.sample_once()  # breach=1
    sampler.sample_once()  # breach=2, fires
    await asyncio.sleep(0)
    assert sampler.state.mem_armed_severity == "critical"
    assert len(captured) == 1
    assert captured[0]["fields"]["ratio_pct"] == "92.0"

    # Drop into safe band → re-arm.
    monkeypatch.setattr(
        do_mod,
        "_read_cgroup_mem_ratio",
        lambda: (0.50, 800_000_000, 1_600_000_000),
    )
    sampler.sample_once()
    assert sampler.state.mem_armed_severity is None
    assert sampler.state.mem_breach == 0


# ---------------------------------------------------------------------------
# Asyncio task-count threshold + hysteresis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_asyncio_tasks_fires_after_sustained_high_count(monkeypatch):
    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(do_mod, "notify_do_error", _capture)
    monkeypatch.setattr(do_mod, "_read_psi_full_avg10", lambda: None)
    monkeypatch.setattr(do_mod, "_read_cgroup_mem_ratio", lambda: (None, None, None))
    monkeypatch.setattr(do_mod, "_read_asyncio_task_count", lambda: 500)

    sampler = MemorySampler(interval_seconds=60)
    # Threshold sustained = 4 samples (60s). First 3: no fire. 4th: fires.
    sampler.sample_once()
    sampler.sample_once()
    sampler.sample_once()
    await asyncio.sleep(0)
    assert captured == []

    sampler.sample_once()
    await asyncio.sleep(0)
    assert len(captured) == 1
    assert captured[0]["fields"]["task_count"] == "500"
    assert sampler.state.tasks_armed_severity == "warning"

    # Re-arm via safe band.
    monkeypatch.setattr(do_mod, "_read_asyncio_task_count", lambda: 30)
    sampler.sample_once()
    assert sampler.state.tasks_breach == 0
    assert sampler.state.tasks_armed_severity is None


# ---------------------------------------------------------------------------
# Graceful degradation on hosts without /proc
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sampler_degrades_gracefully_when_proc_unavailable(monkeypatch):
    """macOS / Windows dev: /proc reads return None; sampler must not raise
    or fire spurious alerts."""
    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(do_mod, "notify_do_error", _capture)
    monkeypatch.setattr(do_mod, "_read_psi_full_avg10", lambda: None)
    monkeypatch.setattr(do_mod, "_read_cgroup_mem_ratio", lambda: (None, None, None))
    monkeypatch.setattr(do_mod, "_read_asyncio_task_count", lambda: 5)

    sampler = MemorySampler(interval_seconds=60)
    for _ in range(10):
        sampler.sample_once()
    await asyncio.sleep(0)
    assert captured == []


@pytest.mark.asyncio
async def test_sample_once_returns_snapshot(monkeypatch):
    monkeypatch.setattr(do_mod, "notify_do_error", lambda **_: None)
    monkeypatch.setattr(do_mod, "_read_psi_full_avg10", lambda: 0.0)
    monkeypatch.setattr(
        do_mod, "_read_cgroup_mem_ratio", lambda: (0.3, 500_000_000, 1_600_000_000)
    )
    monkeypatch.setattr(do_mod, "_read_asyncio_task_count", lambda: 7)
    sampler = MemorySampler()
    snap = sampler.sample_once()
    assert snap["psi_full_avg10"] == 0.0
    assert snap["mem_ratio"] == 0.3
    assert snap["asyncio_tasks"] == 7
    assert "state" in snap
