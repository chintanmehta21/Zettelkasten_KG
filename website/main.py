"""Website-only runtime entrypoint.

Boots the FastAPI app. The module-level ``app`` is what gunicorn loads when
``--preload`` runs, so heavy ONNX sessions in :mod:`website.features.rag_pipeline.rerank.cascade`
are imported once in the master and inherited by workers via copy-on-write.

iter-03 mem-bounded §2.8: a lifespan-managed periodic task logs proc stats
every ``PROC_STATS_LOG_INTERVAL_SECONDS`` (default 60) so ops can decide
later whether to re-enable RAG_FP32_VERIFY.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Awaitable, Callable

import uvicorn
from fastapi import FastAPI

from website.api import _proc_stats as _proc_stats_module
from website.app import create_app
from website.core.heartbeat import heartbeat_loop
from website.core.settings import get_settings
from website.features.rag_pipeline.observability.event_loop_monitor import EventLoopMonitor

logger = logging.getLogger("website.main")


def _proc_stats_interval_seconds() -> float:
    try:
        return float(os.environ.get("PROC_STATS_LOG_INTERVAL_SECONDS", "60"))
    except ValueError:
        return 60.0


async def _proc_stats_logger_loop() -> None:
    """Emit one line per interval. Loop exits cleanly on cancellation."""
    interval = _proc_stats_interval_seconds()
    while True:
        try:
            stats = _proc_stats_module.read_proc_stats()
            logger.info(_proc_stats_module.format_log_line(stats))
        except Exception:  # noqa: BLE001 — never let the logger kill the worker
            logger.exception("proc_stats logger iteration failed")
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return


@contextlib.asynccontextmanager
async def _lifespan(
    _app: FastAPI,
    *,
    loop_factory: Callable[[], Awaitable[None]] = _proc_stats_logger_loop,
):
    # iter-12 Class P: explicit executor sizing. Default min(32, cpu_count+4)=5
    # threads/process saturates under burst-12. PATH_F sizing per RESEARCH.md.
    _exec_workers = int(os.environ.get("RAG_EXECUTOR_MAX_WORKERS", "8"))
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(
        max_workers=_exec_workers,
        thread_name_prefix="supa",
    ))

    # iter-12 Class P: lag canary — p95 < 50 ms gates Phase-2 anchor-boost.
    lag_monitor = EventLoopMonitor(interval_ms=100)
    await lag_monitor.start()
    _app.state.event_loop_monitor = lag_monitor

    task = asyncio.create_task(loop_factory())

    # WM-11 canary heartbeat (post-WAVE-D H-4). No-op if HEARTBEAT_PING_URL
    # is unset, so dev environments stay quiet by default.
    hb_stop = asyncio.Event()
    _app.state.heartbeat_stop = hb_stop

    def _key_pool_getter() -> object | None:
        try:
            from website.features.api_key_switching import get_key_pool

            return get_key_pool()
        except Exception:  # noqa: BLE001 — never block lifespan startup
            return None

    hb_task = asyncio.create_task(
        heartbeat_loop(hb_stop, key_pool_getter=_key_pool_getter)
    )

    # PR #39 / Wave-3 B1 (2026-05-20): in-process lazy-enrichment worker.
    # One coroutine per gunicorn worker process drains the
    # core.zettel_enrichment_jobs queue via SELECT FOR UPDATE SKIP LOCKED.
    # Disabled in test/CI when ZK_LAZY_ENRICHMENT_DISABLED=1 (the worker's
    # internal env check short-circuits at first iteration).
    from website.features.summarization_engine.lazy_enrichment import (
        worker as enrichment_worker,
    )

    # B4 — alert on enrichment-worker death. The worker is supposed to run
    # for the lifetime of the gunicorn worker; any other exit (KeyError,
    # asyncpg connection drop, JSON decode error inside a job) silently
    # halts lazy enrichment for THIS worker until restart. Use
    # _spawn_alerting so the done-callback fires #app-errors if the task
    # ends with a non-CancelledError exception.
    from website.features.web_monitor.App_Errors import _spawn_alerting

    enrichment_task = _spawn_alerting(
        enrichment_worker.run_forever(),
        dedup_key="enrichment_worker_died",
        route="main._lifespan.enrichment_worker",
        severity="critical",
    )
    assert enrichment_task is not None  # the lifespan always has a running loop

    # Tier D — start the per-worker memory/asyncio-task sampler so PSI,
    # cgroup memory, and asyncio task-count breaches fire to #do-errors.
    # Runs one coroutine per gunicorn worker; degrades gracefully on hosts
    # without cgroup-v2 / PSI (returns None from the /proc reads).
    from website.features.web_monitor import start_memory_sampler, stop_memory_sampler

    memory_sampler = start_memory_sampler()

    try:
        yield
    finally:
        hb_stop.set()
        task.cancel()
        await enrichment_worker.request_stop()
        enrichment_task.cancel()
        stop_memory_sampler()
        sampler_task = memory_sampler._task if memory_sampler is not None else None
        tasks_to_drain: list[asyncio.Task] = [task, hb_task, enrichment_task]
        if sampler_task is not None:
            tasks_to_drain.append(sampler_task)
        for t in tasks_to_drain:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        await lag_monitor.stop()


# Module-level ASGI app. gunicorn imports ``website.main:app`` with --preload.
app = create_app(lifespan=_lifespan)


def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    port = settings.server_port
    logger.info("Starting Zettelkasten website on 0.0.0.0:%d (uvicorn dev mode)", port)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
