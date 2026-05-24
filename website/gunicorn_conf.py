"""Gunicorn hooks for production workers."""

from __future__ import annotations


def post_fork(server, worker) -> None:  # pragma: no cover - exercised by gunicorn
    from website.features.rag_pipeline.scoring.runtime import start_registry_adapter_post_fork

    start_registry_adapter_post_fork()


def child_exit(server, worker) -> None:  # pragma: no cover - exercised by gunicorn
    """Phase 4 / Task 4.6: clean up the dying worker's Prometheus
    multiprocess shard so kg_* counters don't keep ballooning across
    worker churn (see prometheus_client multiprocess exposition docs).

    No-op when prometheus_client is missing (e.g. local dev without
    ops/requirements installed); also no-op when PROMETHEUS_MULTIPROC_DIR
    is unset (multiprocess mode disabled — single-process exposition).
    """
    try:
        from prometheus_client import multiprocess
        multiprocess.mark_process_dead(worker.pid)
    except Exception:  # noqa: BLE001 — metrics are best-effort, never fatal.
        pass

