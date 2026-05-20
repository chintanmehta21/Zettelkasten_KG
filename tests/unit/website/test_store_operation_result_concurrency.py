"""P1 concurrency regressions in `_store_operation_result` (done-callback).

T1: terminal-write task must be strongly referenced (routed via `_spawn_bg`)
    so GC cannot drop the cross-worker `mark_*` write mid-flight.
T2: a CANCELLED work task (evicted by `_operation_put` LRU) must NOT leave
    the `_IN_FLIGHT` idempotency slot stuck forever — cleanup trio must run
    on the cancelled path exactly as it does for success/failure.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from website.api import zettels_routes as zr


def _seed_slot(cache_key, op_id, task):
    zr._IN_FLIGHT[cache_key] = ("sub", op_id, task)
    zr._OPERATION_TASKS[op_id] = task


def _clear(cache_key, op_id):
    zr._IN_FLIGHT.pop(cache_key, None)
    zr._OPERATION_TASKS.pop(op_id, None)
    zr._OPERATIONS.pop(op_id, None)


# ---------------------------------------------------------------------------
# T2 — cancelled task must free the idempotency slot + store a terminal result
# ---------------------------------------------------------------------------
def test_cancelled_work_task_frees_in_flight_and_stores_failed():
    cache_key = ("u", "c-cancel")
    op_id = "op-cancel-1"

    async def _go():
        started = asyncio.Event()

        async def _never():
            started.set()
            await asyncio.sleep(3600)

        task = asyncio.create_task(_never())
        await started.wait()  # deterministic: task is running before cancel
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert task.cancelled()

        _seed_slot(cache_key, op_id, task)
        # No user_id -> no terminal persist path; isolates the cleanup trio.
        zr._store_operation_result(
            task,
            operation_id=op_id,
            cache_key=cache_key,
            request_hash="h",
            persist_requested=False,
            user_id=None,
        )

    try:
        asyncio.run(_go())
        # cleanup trio MUST have run despite CancelledError
        assert cache_key not in zr._IN_FLIGHT, "idempotency slot stuck after cancel"
        assert op_id not in zr._OPERATION_TASKS
        stored = zr._operation_get(op_id)
        assert stored is not None, "no terminal result stored for cancelled op"
        assert stored["status"] == "failed"
    finally:
        _clear(cache_key, op_id)


def test_cancelled_path_does_not_cache_put():
    """A cancelled op is NOT a success — it must never populate the
    idempotency response cache (only the success `else` branch may)."""
    cache_key = ("u", "c-cancel-nocache")
    op_id = "op-cancel-2"

    async def _go():
        started = asyncio.Event()

        async def _never():
            started.set()
            await asyncio.sleep(3600)

        task = asyncio.create_task(_never())
        await started.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        _seed_slot(cache_key, op_id, task)
        with patch("website.api.zettels_routes._cache_put") as cp:
            zr._store_operation_result(
                task, operation_id=op_id, cache_key=cache_key,
                request_hash="h", persist_requested=False, user_id=None,
            )
            assert cp.call_count == 0

    try:
        asyncio.run(_go())
    finally:
        _clear(cache_key, op_id)


# ---------------------------------------------------------------------------
# T1 — terminal-write task routed through the _spawn_bg strong-ref chokepoint
# ---------------------------------------------------------------------------
def test_terminal_write_routed_through_spawn_bg_with_running_loop():
    cache_key = ("u", "c-t1")
    op_id = "op-t1-1"
    uid = zr._zoro_user_id()

    async def _go():
        async def _ok():
            return {"status": "succeeded", "operation_id": op_id}

        task = asyncio.create_task(_ok())
        await task
        _seed_slot(cache_key, op_id, task)

        with patch("website.api.zettels_routes._spawn_bg") as sb, \
             patch("website.api.zettels_routes.operations_repo.mark_succeeded",
                   return_value=True), \
             patch("website.api.zettels_routes.operations_repo.mark_failed",
                   return_value=True):
            zr._store_operation_result(
                task, operation_id=op_id, cache_key=cache_key,
                request_hash="h", persist_requested=False, user_id=uid,
            )
            # terminal write must go through the strong-ref chokepoint
            assert sb.call_count == 1, "terminal write not routed via _spawn_bg"
            # _spawn_bg is mocked here so the passed coro is never consumed;
            # close it to avoid a test-only "never awaited" RuntimeWarning.
            (arg,) = sb.call_args.args
            if asyncio.iscoroutine(arg):
                arg.close()

    try:
        asyncio.run(_go())
    finally:
        _clear(cache_key, op_id)


def test_terminal_write_sync_fallback_when_no_running_loop():
    """Callback fired post-loop (no running loop): _spawn_bg's create_task
    raises RuntimeError -> synchronous best-effort mark_* must still fire."""
    cache_key = ("u", "c-t1-fallback")
    op_id = "op-t1-2"
    uid = zr._zoro_user_id()

    async def _make_done():
        async def _ok():
            return {"status": "succeeded", "operation_id": op_id}

        t = asyncio.create_task(_ok())
        await t
        return t

    task = asyncio.run(_make_done())  # task done, no running loop now
    _seed_slot(cache_key, op_id, task)
    try:
        with patch("website.api.zettels_routes.operations_repo.mark_succeeded",
                   return_value=True) as ms, \
             patch("website.api.zettels_routes.operations_repo.mark_failed",
                   return_value=True) as mf:
            zr._store_operation_result(
                task, operation_id=op_id, cache_key=cache_key,
                request_hash="h", persist_requested=False, user_id=uid,
            )
            assert ms.call_count == 1
            assert mf.call_count == 0
        assert cache_key not in zr._IN_FLIGHT
    finally:
        _clear(cache_key, op_id)


# ---------------------------------------------------------------------------
# Regression — success / Exception paths unchanged
# ---------------------------------------------------------------------------
def test_succeeded_path_cache_puts_and_frees_slot():
    cache_key = ("u", "c-ok")
    op_id = "op-ok-1"

    async def _go():
        async def _ok():
            return {"status": "succeeded", "operation_id": op_id}

        task = asyncio.create_task(_ok())
        await task
        _seed_slot(cache_key, op_id, task)
        with patch("website.api.zettels_routes._cache_put") as cp:
            zr._store_operation_result(
                task, operation_id=op_id, cache_key=cache_key,
                request_hash="h", persist_requested=False, user_id=None,
            )
            assert cp.call_count == 1

    try:
        asyncio.run(_go())
        assert cache_key not in zr._IN_FLIGHT
        assert zr._operation_get(op_id)["status"] == "succeeded"
    finally:
        _clear(cache_key, op_id)


def test_exception_path_no_cache_put_stores_failed_frees_slot():
    cache_key = ("u", "c-err")
    op_id = "op-err-1"

    async def _go():
        async def _boom():
            raise ValueError("kaboom")

        task = asyncio.create_task(_boom())
        try:
            await task
        except ValueError:
            pass
        _seed_slot(cache_key, op_id, task)
        with patch("website.api.zettels_routes._cache_put") as cp:
            zr._store_operation_result(
                task, operation_id=op_id, cache_key=cache_key,
                request_hash="h", persist_requested=False, user_id=None,
            )
            assert cp.call_count == 0

    try:
        asyncio.run(_go())
        assert cache_key not in zr._IN_FLIGHT
        assert op_id not in zr._OPERATION_TASKS
        assert zr._operation_get(op_id)["status"] == "failed"
    finally:
        _clear(cache_key, op_id)


# ---------------------------------------------------------------------------
# P2 — structured failure detail preserved across the 20s fast-ack boundary
# (otherwise the frontend's `err.detail.code === 'quota_exhausted'` UI regresses
# to a generic message for any failure that completes after the universal-202)
# ---------------------------------------------------------------------------
def _async_failed_result(op_id: str, exc: BaseException):
    """Drive _store_operation_result's `except Exception` branch with `exc`
    and return the stored terminal envelope."""
    from fastapi import HTTPException as _HTTPException  # noqa: F401
    cache_key = ("u", f"c-{op_id}")

    async def _go():
        async def _raises():
            raise exc

        task = asyncio.create_task(_raises())
        try:
            await task
        except BaseException:
            pass
        _seed_slot(cache_key, op_id, task)
        zr._store_operation_result(
            task, operation_id=op_id, cache_key=cache_key,
            request_hash="h", persist_requested=False, user_id=None,
        )

    try:
        asyncio.run(_go())
        return zr._operation_get(op_id)
    finally:
        _clear(cache_key, op_id)


def test_async_failure_httpexception_dict_detail_preserves_structured_error():
    """402 quota_exhausted from the pricing gate must reach the frontend with
    `error.detail == {"code":"quota_exhausted", ...}` after a slow-async fail,
    so the post-F1 reject path's `err.detail.code` works identically to sync."""
    from fastapi import HTTPException

    detail = {
        "code": "quota_exhausted",
        "message": "Daily Zettel limit reached",
        "meter": "zettel",
    }
    stored = _async_failed_result(
        "op-quota-async",
        HTTPException(status_code=402, detail=detail),
    )
    assert stored is not None
    err = stored.get("error")
    assert isinstance(err, dict), f"structured error missing: {stored!r}"
    # Mirror the sync path's _problem(...) output for the HTTPException branch
    # (zettels_routes.py:504-519): same code/title/status/detail surface so
    # frontend `err.detail.code === 'quota_exhausted'` resolves identically.
    assert err.get("status") == 402
    assert err.get("detail") == detail
    # The sync path derives title from detail["message"]/["error"]; mirror it.
    assert err.get("title") == "Daily Zettel limit reached"
    # type_slug parity: "quota-exhausted" when detail.code == "quota_exhausted".
    assert err.get("type", "").endswith("/quota-exhausted")


def test_async_failure_unsupported_video_preserves_structured_error():
    """UnsupportedVideoError thrown in the background task must map to the
    SAME problem-detail shape as the sync route handler at L520-528."""
    from website.features.summarization_engine.core.errors import (
        UnsupportedVideoError,
    )

    exc = UnsupportedVideoError(
        reason="private", url="https://youtube.com/watch?v=abc",
    )
    stored = _async_failed_result("op-unsup-async", exc)
    err = stored.get("error") if stored else None
    assert isinstance(err, dict), f"structured error missing: {stored!r}"
    assert err.get("status") == 422
    assert err.get("title") == "Unsupported video"
    assert err.get("detail") == "Video type cannot be ingested: private"
    assert err.get("type", "").endswith("/unsupported-video")


def test_async_failure_extraction_confidence_preserves_structured_error():
    """ExtractionConfidenceError must map to the sync path's L529-538 shape,
    including the `reason` + `tier_results` extras emitted by _problem.extra."""
    from website.features.summarization_engine.core.errors import (
        ExtractionConfidenceError,
    )

    tier_results = [{"tier": "t1", "ok": False}]
    exc = ExtractionConfidenceError(
        "low", reason="low_signal", tier_results=tier_results,
    )
    stored = _async_failed_result("op-conf-async", exc)
    err = stored.get("error") if stored else None
    assert isinstance(err, dict), f"structured error missing: {stored!r}"
    assert err.get("status") == 422
    assert err.get("title") == "Insufficient content"
    assert err.get("type", "").endswith("/insufficient-content")
    assert err.get("reason") == "low_signal"
    assert err.get("tier_results") == tier_results


def test_async_failure_generic_exception_has_no_structured_error():
    """A plain RuntimeError carries no structured detail — `error` is None and
    the existing `confidence_reason=str(exc)` path is untouched."""
    stored = _async_failed_result("op-generic-async", RuntimeError("boom"))
    assert stored is not None
    assert stored.get("status") == "failed"
    assert stored["quality"]["confidence_reason"] == "boom"
    # Either field absent or explicitly None — never a wrong-shape dict.
    assert stored.get("error") in (None,)


def test_async_cancelled_path_has_no_structured_error():
    """T2 cancellation path must keep its current 'operation cancelled' body
    with error=None (cancellation is not a typed failure)."""
    cache_key = ("u", "c-cancel-err")
    op_id = "op-cancel-err"

    async def _go():
        started = asyncio.Event()

        async def _never():
            started.set()
            await asyncio.sleep(3600)

        task = asyncio.create_task(_never())
        await started.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        _seed_slot(cache_key, op_id, task)
        zr._store_operation_result(
            task, operation_id=op_id, cache_key=cache_key,
            request_hash="h", persist_requested=False, user_id=None,
        )

    try:
        asyncio.run(_go())
        stored = zr._operation_get(op_id)
        assert stored is not None
        assert stored["status"] == "failed"
        assert stored["quality"]["confidence_reason"] == "operation cancelled"
        assert stored.get("error") in (None,)
    finally:
        _clear(cache_key, op_id)


def test_succeeded_envelope_does_not_introduce_structured_error():
    """No regression on the success path — `error` MUST be None / absent."""
    cache_key = ("u", "c-ok-err")
    op_id = "op-ok-err"

    async def _go():
        async def _ok():
            from website.api.module_runners.summarization import (
                AddZettelPipelineOutput, QualityDTO, persistence_dto,
            )
            return AddZettelPipelineOutput(
                status="succeeded",
                operation_id=op_id,
                persistence=persistence_dto(False, None),
                quality=QualityDTO(confidence="succeeded"),
            ).model_dump(mode="json")

        task = asyncio.create_task(_ok())
        await task
        _seed_slot(cache_key, op_id, task)
        zr._store_operation_result(
            task, operation_id=op_id, cache_key=cache_key,
            request_hash="h", persist_requested=False, user_id=None,
        )

    try:
        asyncio.run(_go())
        stored = zr._operation_get(op_id)
        assert stored is not None
        assert stored["status"] == "succeeded"
        assert stored.get("error") in (None,)
    finally:
        _clear(cache_key, op_id)
