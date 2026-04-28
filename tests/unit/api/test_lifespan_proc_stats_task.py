"""Iter-03 mem-bounded §2.8: a periodic asyncio task logs proc stats every
PROC_STATS_LOG_INTERVAL_SECONDS (default 60). Lifecycle: started in lifespan
startup, cancelled cleanly within 1s on shutdown.
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from website import main as main_mod


@pytest.mark.asyncio
async def test_proc_stats_logger_loop_emits_log_line(monkeypatch, caplog):
    monkeypatch.setattr(main_mod, "_proc_stats_interval_seconds", lambda: 0.05)
    monkeypatch.setattr(
        main_mod._proc_stats_module, "read_proc_stats",
        lambda: {"vm_rss_kb": 42, "vm_swap_kb": 0,
                 "vm_size_kb": 100, "num_threads": 4,
                 "load_1m": 0.0, "load_5m": 0.0, "load_15m": 0.0,
                 "cgroup_mem_current": 0, "cgroup_mem_max": 0,
                 "cgroup_swap_current": 0, "cgroup_swap_max": 0},
    )
    caplog.set_level(logging.INFO, logger="website.main")
    task = asyncio.create_task(main_mod._proc_stats_logger_loop())
    await asyncio.sleep(0.15)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    msgs = [r.message for r in caplog.records if "[proc_stats]" in r.message]
    assert msgs, "logger loop must have emitted at least one [proc_stats] line"
    assert "vm_rss_kb=42" in msgs[0]


@pytest.mark.asyncio
async def test_lifespan_starts_and_cancels_task():
    started: list[bool] = []
    stopped: list[bool] = []

    async def _fake_loop():
        started.append(True)
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            stopped.append(True)
            raise

    import contextlib
    @contextlib.asynccontextmanager
    async def _wrap_lifespan(app):
        async with main_mod._lifespan(app, loop_factory=_fake_loop):
            yield

    from fastapi import FastAPI
    fake_app = FastAPI()
    async with _wrap_lifespan(fake_app):
        await asyncio.sleep(0.05)
    assert started == [True]
    assert stopped == [True]
