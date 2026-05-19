"""P1 regression: `_operation_put` LRU eviction must NOT cancel a still-
running summarization task.

Under bursty traffic, a completion-time `_operation_put` can evict the
oldest entry, which is an accept-time placeholder for an op whose
`_OPERATION_TASKS` entry is still a live, running task. The prior
behavior cancelled it, killing the user's in-flight summary. The fix
preserves running tasks (promotes them to `_BG_TASKS` for defense-in-
depth strong ref) and only drops the `_OPERATION_TASKS` entry when the
task is already done.
"""
from __future__ import annotations

import asyncio

from website.api import zettels_routes as zr


def _purge_all(ids: list[str]) -> None:
    for oid in ids:
        zr._OPERATIONS.pop(oid, None)
        zr._OPERATION_TASKS.pop(oid, None)


def _snapshot_and_clear():
    """Snapshot the module-globals, then reset so the test runs in
    isolation regardless of pollution from prior tests in the suite."""
    snap_ops = list(zr._OPERATIONS.items())
    snap_tasks = dict(zr._OPERATION_TASKS)
    snap_in_flight = dict(zr._IN_FLIGHT)
    snap_bg = set(zr._BG_TASKS)
    zr._OPERATIONS.clear()
    zr._OPERATION_TASKS.clear()
    zr._IN_FLIGHT.clear()
    zr._BG_TASKS.clear()
    return snap_ops, snap_tasks, snap_in_flight, snap_bg


def _restore(snap):
    snap_ops, snap_tasks, snap_in_flight, snap_bg = snap
    zr._OPERATIONS.clear()
    for k, v in snap_ops:
        zr._OPERATIONS[k] = v
    zr._OPERATION_TASKS.clear()
    zr._OPERATION_TASKS.update(snap_tasks)
    zr._IN_FLIGHT.clear()
    zr._IN_FLIGHT.update(snap_in_flight)
    zr._BG_TASKS.clear()
    zr._BG_TASKS.update(snap_bg)


def _saturate(prefix: str, n: int) -> list[str]:
    """Fill _OPERATIONS with N synthetic completed-result entries."""
    ids = [f"{prefix}-fill-{i}" for i in range(n)]
    for oid in ids:
        zr._OPERATIONS[oid] = (0.0, {"status": "succeeded", "operation_id": oid})
    return ids


# ---------------------------------------------------------------------------
# Bug: a still-running in-flight task is the LRU-oldest -> eviction would
# cancel it under the old code. After fix: never cancel a running task.
# ---------------------------------------------------------------------------
def test_eviction_does_not_cancel_still_running_task():
    snap = _snapshot_and_clear()
    cap = zr._MAX_OPERATION_RECORDS
    live_id = "evict-live-1"
    new_id = "evict-new-1"
    fill_ids: list[str] = []

    async def _go():
        nonlocal fill_ids
        started = asyncio.Event()

        async def _slow():
            started.set()
            await asyncio.sleep(3600)

        task = asyncio.create_task(_slow())
        await started.wait()

        # Seed: live op at the LRU-oldest position; its OPERATION_TASKS
        # entry is the still-running task.
        zr._OPERATIONS[live_id] = (0.0, {"status": "accepted", "operation_id": live_id})
        zr._OPERATION_TASKS[live_id] = task
        # Move live_id to the front (oldest) then pile cap-1 fresh entries
        # on top so live_id is the eviction victim.
        zr._OPERATIONS.move_to_end(live_id, last=False)
        fill_ids = _saturate("eviction", cap - 1)
        # Sanity: live is oldest, total == cap.
        assert next(iter(zr._OPERATIONS)) == live_id
        assert len(zr._OPERATIONS) == cap

        # Trigger one eviction by inserting the cap+1'th record.
        zr._operation_put(new_id, {"status": "succeeded", "operation_id": new_id})

        try:
            # Core assertion (fails on old code which cancels):
            assert not task.cancelled(), "still-running task was cancelled by eviction"
            assert not task.done(), "still-running task was marked done by eviction"
            # Strong-ref preserved: either still in _OPERATION_TASKS or
            # promoted into _BG_TASKS so GC can't drop it.
            strong_ref_held = task in zr._BG_TASKS or task in set(zr._OPERATION_TASKS.values())
            assert strong_ref_held, "evicted running task lost its strong ref"
            # The new record was inserted, live was evicted from _OPERATIONS.
            assert new_id in zr._OPERATIONS
            assert live_id not in zr._OPERATIONS
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    try:
        asyncio.run(_go())
    finally:
        _purge_all([live_id, new_id, *fill_ids])
        _restore(snap)


# ---------------------------------------------------------------------------
# Already-done eviction must not raise and must not "cancel" anything.
# ---------------------------------------------------------------------------
def test_eviction_of_done_task_does_not_raise():
    snap = _snapshot_and_clear()
    cap = zr._MAX_OPERATION_RECORDS
    done_id = "evict-done-1"
    new_id = "evict-done-new-1"
    fill_ids: list[str] = []

    async def _go():
        nonlocal fill_ids

        async def _ok():
            return "ok"

        task = asyncio.create_task(_ok())
        await task
        assert task.done() and not task.cancelled()

        zr._OPERATIONS[done_id] = (0.0, {"status": "succeeded", "operation_id": done_id})
        zr._OPERATION_TASKS[done_id] = task
        zr._OPERATIONS.move_to_end(done_id, last=False)
        fill_ids = _saturate("evict-done", cap - 1)
        assert next(iter(zr._OPERATIONS)) == done_id

        # Should not raise.
        zr._operation_put(new_id, {"status": "succeeded", "operation_id": new_id})

        # Done task is unchanged (it was already done; nothing to cancel).
        assert task.done()
        assert not task.cancelled()
        assert done_id not in zr._OPERATIONS

    try:
        asyncio.run(_go())
    finally:
        _purge_all([done_id, new_id, *fill_ids])
        _restore(snap)


# ---------------------------------------------------------------------------
# Eviction of an op with NO _OPERATION_TASKS entry (already popped by its
# done-callback): must not raise.
# ---------------------------------------------------------------------------
def test_eviction_without_task_entry_is_safe():
    snap = _snapshot_and_clear()
    cap = zr._MAX_OPERATION_RECORDS
    orphan_id = "evict-orphan-1"
    new_id = "evict-orphan-new-1"
    zr._OPERATIONS[orphan_id] = (0.0, {"status": "succeeded", "operation_id": orphan_id})
    zr._OPERATIONS.move_to_end(orphan_id, last=False)
    fill_ids = _saturate("evict-orphan", cap - 1)
    try:
        zr._operation_put(new_id, {"status": "succeeded", "operation_id": new_id})
        assert orphan_id not in zr._OPERATIONS
        assert new_id in zr._OPERATIONS
    finally:
        _purge_all([orphan_id, new_id, *fill_ids])
        _restore(snap)


# ---------------------------------------------------------------------------
# Regression: ordinary _operation_put behavior (insert + LRU order) unchanged.
# ---------------------------------------------------------------------------
def test_operation_put_preserves_lru_for_completed_ops():
    snap = _snapshot_and_clear()
    ids = [f"lru-{i}" for i in range(5)]
    try:
        for oid in ids:
            zr._operation_put(oid, {"status": "succeeded", "operation_id": oid})
        # Last inserted is most-recent.
        assert list(zr._OPERATIONS)[-len(ids):] == ids
    finally:
        _purge_all(ids)
        _restore(snap)


# ---------------------------------------------------------------------------
# End-to-end: a slow task whose _OPERATIONS placeholder has been LRU-evicted
# still completes; its done-callback fires _store_operation_result, which
# calls _operation_put with the final result, pops _OPERATION_TASKS, and
# frees _IN_FLIGHT.
# ---------------------------------------------------------------------------
def test_slow_task_completes_after_its_placeholder_was_evicted():
    snap = _snapshot_and_clear()
    cap = zr._MAX_OPERATION_RECORDS
    cache_key = ("u", "e2e-evict")
    op_id = "e2e-evict-1"
    fill_ids: list[str] = []

    async def _go():
        nonlocal fill_ids
        started = asyncio.Event()
        proceed = asyncio.Event()

        async def _slow():
            started.set()
            await proceed.wait()
            return {"status": "succeeded", "operation_id": op_id}

        task = asyncio.create_task(_slow())
        await started.wait()

        # Mimic the accept-path: placeholder in _OPERATIONS, task in
        # _OPERATION_TASKS, _IN_FLIGHT seeded, done-callback installed.
        zr._OPERATIONS[op_id] = (0.0, {"status": "accepted", "operation_id": op_id})
        zr._OPERATION_TASKS[op_id] = task
        zr._IN_FLIGHT[cache_key] = ("h", op_id, task)
        task.add_done_callback(
            lambda t: zr._store_operation_result(
                t, operation_id=op_id, cache_key=cache_key,
                request_hash="h", persist_requested=False, user_id=None,
            )
        )
        # Push placeholder to oldest and saturate.
        zr._OPERATIONS.move_to_end(op_id, last=False)
        fill_ids = _saturate("e2e", cap - 1)
        assert next(iter(zr._OPERATIONS)) == op_id

        # Force eviction of the placeholder.
        zr._operation_put("e2e-trigger", {"status": "succeeded"})
        assert op_id not in zr._OPERATIONS
        # Task must NOT be cancelled.
        assert not task.cancelled()
        assert not task.done()

        # Let the slow task finish; the done-callback flow must work.
        proceed.set()
        await task

    try:
        asyncio.run(_go())
        # Done-callback wrote terminal result via _operation_put.
        stored = zr._operation_get(op_id)
        assert stored is not None, "terminal result missing after eviction+complete"
        assert stored["status"] == "succeeded"
        # Cleanup trio ran.
        assert cache_key not in zr._IN_FLIGHT
        assert op_id not in zr._OPERATION_TASKS
    finally:
        zr._OPERATIONS.pop(op_id, None)
        zr._OPERATIONS.pop("e2e-trigger", None)
        zr._OPERATION_TASKS.pop(op_id, None)
        zr._IN_FLIGHT.pop(cache_key, None)
        _purge_all(fill_ids)
        _restore(snap)
