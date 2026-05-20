"""In-process async enrichment worker (PR #39 Wave-3).

One ``run_forever`` task per gunicorn worker. Polls the
``core.zettel_enrichment_jobs`` queue via ``enrich_claim_next`` and
dispatches to the per-kind handler. Empty-queue backoff (5s -> 30s) keeps
idle CPU/Postgres traffic near zero on quiet droplets.

Concurrency model:
    * Each gunicorn worker process runs one worker loop in its own asyncio
      event loop. With ``GUNICORN_WORKERS=2`` (the canonical droplet
      setting) we naturally get 2 concurrent claim_next callers — Postgres'
      ``FOR UPDATE SKIP LOCKED`` inside the RPC ensures they never grab
      the same row.
    * Handlers run sequentially within one worker loop. If we later want
      per-worker parallelism, we'd add an asyncio.Semaphore here and spawn
      multiple in-flight handler tasks per loop. For now, serial is
      simpler and matches the 1 vCPU droplet's compute budget.

Failure handling:
    * Handler raises -> worker calls enrich_requeue. The RPC promotes to
      dead_letter when attempts >= max_attempts (default 3); otherwise the
      row goes back to 'queued' for another worker to pick up.
    * Worker crash mid-handle -> the stuck-running reaper companion job
      (see migration 60 doc) eventually flips the row back to failed; on
      restart we re-poll the queue and resume.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable, Coroutine

from website.api._problem import _problem_dict
from website.features.summarization_engine.lazy_enrichment import repo
from website.features.summarization_engine.lazy_enrichment.handlers import chunk_embed

logger = logging.getLogger(
    "website.features.summarization_engine.lazy_enrichment.worker"
)

# Backoff schedule: empty-queue sleep grows 5s -> 10s -> 20s -> 30s (cap),
# resets to 5s the moment a job is claimed. Keeps idle Postgres traffic to
# a few queries per minute on a quiet droplet without sacrificing latency
# when work is bursty.
_BACKOFF_SCHEDULE_S: tuple[float, ...] = (5.0, 10.0, 20.0, 30.0)

# Per-iteration handler-error backoff (independent of empty-queue backoff).
_ERROR_SLEEP_S: float = 2.0

# Master switch: disable the worker entirely via env var (useful for test
# fixtures + CI containers that don't want a background poller running).
_DISABLED_ENV: str = "ZK_LAZY_ENRICHMENT_DISABLED"


HandlerCoro = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]

# kind -> handler dispatch. New kinds register here; the dispatch fail-fast
# converts an unknown kind into a dead_letter so a deploy that ships an
# enqueue site without the matching handler is visible immediately.
_HANDLERS: dict[str, HandlerCoro] = {
    repo.KIND_CHUNK_EMBED: chunk_embed.handle,
}


_stop_event: asyncio.Event | None = None


def is_disabled() -> bool:
    return os.environ.get(_DISABLED_ENV, "").lower() in ("1", "true", "yes", "on")


async def run_forever() -> None:
    """Worker entry point. Runs until cancelled or the stop event fires.

    Wraps every iteration in a try/except so a single transient failure
    (Postgres hiccup, handler bug, ImportError on a new kind) NEVER kills
    the loop — only an explicit asyncio.CancelledError can stop it.
    """
    if is_disabled():
        logger.info("lazy_enrichment worker disabled via %s", _DISABLED_ENV)
        return

    global _stop_event
    _stop_event = asyncio.Event()
    backoff_idx = 0
    pid = os.getpid()
    logger.info("lazy_enrichment worker started (pid=%d)", pid)
    try:
        while not _stop_event.is_set():
            try:
                job = await asyncio.to_thread(repo.claim_next)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("lazy_enrichment claim_next raised; sleeping")
                await _interruptible_sleep(_ERROR_SLEEP_S)
                continue

            if job is None:
                # Empty queue -> back off; first iteration is a short 5s.
                sleep_s = _BACKOFF_SCHEDULE_S[
                    min(backoff_idx, len(_BACKOFF_SCHEDULE_S) - 1)
                ]
                backoff_idx = min(backoff_idx + 1, len(_BACKOFF_SCHEDULE_S) - 1)
                await _interruptible_sleep(sleep_s)
                continue

            # Got work -> reset backoff.
            backoff_idx = 0
            await _process_one(job)
    except asyncio.CancelledError:
        logger.info("lazy_enrichment worker cancelled (pid=%d)", pid)
        raise
    finally:
        _stop_event = None
        logger.info("lazy_enrichment worker stopped (pid=%d)", pid)


async def request_stop() -> None:
    """Idempotent shutdown signal for tests + the FastAPI lifespan hook."""
    global _stop_event
    if _stop_event is not None:
        _stop_event.set()


async def _interruptible_sleep(duration_s: float) -> None:
    """Sleep that wakes up early on a stop request. Falls back to plain
    asyncio.sleep if the event isn't initialised yet."""
    if _stop_event is None:
        await asyncio.sleep(duration_s)
        return
    try:
        await asyncio.wait_for(_stop_event.wait(), timeout=duration_s)
    except asyncio.TimeoutError:
        pass


async def _process_one(job: dict[str, Any]) -> None:
    job_id = str(job.get("job_id") or "")
    kind = str(job.get("kind") or "")
    payload = dict(job.get("payload") or {})
    attempts = int(job.get("attempts") or 0)
    max_attempts = int(job.get("max_attempts") or 3)
    handler = _HANDLERS.get(kind)
    if handler is None:
        logger.error(
            "lazy_enrichment: unknown kind=%r (job=%s); dead-lettering", kind, job_id
        )
        await asyncio.to_thread(
            repo.finalize,
            job_id=job_id,
            target="dead_letter",
            error=_problem_dict(
                status_code=500,
                title="Unknown enrichment kind",
                detail=f"No handler registered for kind={kind!r}.",
                type_slug="enrichment-unknown-kind",
            ),
        )
        return

    try:
        await handler(payload)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        error_payload = _problem_dict(
            status_code=500,
            title="Enrichment handler failed",
            detail=str(exc) or exc.__class__.__name__,
            type_slug="enrichment-handler-failed",
        )
        # Transient: requeue if retries remain, else dead_letter.
        if attempts < max_attempts:
            logger.warning(
                "lazy_enrichment handler %s raised (job=%s attempt=%d/%d); requeuing",
                kind, job_id, attempts, max_attempts,
                exc_info=True,
            )
            await asyncio.to_thread(
                repo.requeue, job_id=job_id, error=error_payload
            )
        else:
            logger.error(
                "lazy_enrichment handler %s exhausted retries (job=%s); dead-lettering",
                kind, job_id,
                exc_info=True,
            )
            await asyncio.to_thread(
                repo.finalize,
                job_id=job_id,
                target="dead_letter",
                error=error_payload,
            )
        return

    # Success path.
    await asyncio.to_thread(repo.finalize, job_id=job_id, target="succeeded")
