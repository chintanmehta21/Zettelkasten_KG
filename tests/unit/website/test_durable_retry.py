"""Step 5: durable retry for accepted Add-Zettel work (migration 85).

PR #174's lifespan drain covers signal-initiated shutdown only. A cgroup OOM
kill is SIGKILL with zero grace — no Python handler runs at all — and the
droplet's app cgroup has already OOM-killed processes. The only mechanism that
survives that is out-of-process state: a heartbeat that proves liveness, a
reaper that requeues rather than fails, and a step journal so a retry doesn't
re-run (and re-bill) work that already completed.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from website.api import zettels_routes as zr
from website.core import operations_repo

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = REPO_ROOT / "supabase/website/_v2/85_operations_durable_retry.sql"


# --- heartbeat -------------------------------------------------------------


async def test_heartbeat_stops_when_no_longer_owner():
    """A reclaimed operation may now be owned by another worker.

    Continuing to ping would resurrect liveness for work we no longer own and
    let two workers run the same pipeline — double-billing Gemini.
    """
    calls = []

    def _hb(**kw):
        calls.append(kw)
        return False  # row is no longer 'running'

    with patch.object(zr, "OPS_HEARTBEAT_INTERVAL_S", 0.01), patch.object(
        operations_repo, "heartbeat", _hb
    ):
        await asyncio.wait_for(
            zr._heartbeat_loop(user_id=zr.UUID(int=1), operation_id="op-hb"),
            timeout=5,
        )
    assert len(calls) == 1, "must stop after the first non-owner response"


async def test_heartbeat_keeps_pinging_while_owner():
    calls = []

    def _hb(**kw):
        calls.append(kw)
        return True

    with patch.object(zr, "OPS_HEARTBEAT_INTERVAL_S", 0.01), patch.object(
        operations_repo, "heartbeat", _hb
    ):
        task = asyncio.create_task(
            zr._heartbeat_loop(user_id=zr.UUID(int=1), operation_id="op-hb2")
        )
        await asyncio.sleep(0.08)
        task.cancel()
    assert len(calls) >= 2, "should have pinged repeatedly"


async def test_heartbeat_survives_repo_errors():
    """A monitoring loop must never kill the job it monitors."""

    def _boom(**_kw):
        raise RuntimeError("postgrest down")

    with patch.object(zr, "OPS_HEARTBEAT_INTERVAL_S", 0.01), patch.object(
        operations_repo, "heartbeat", _boom
    ):
        task = asyncio.create_task(
            zr._heartbeat_loop(user_id=zr.UUID(int=1), operation_id="op-hb3")
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_run_cancels_heartbeat_on_every_exit_path():
    """A leaked heartbeat keeps a dead op looking alive forever."""
    live: list[asyncio.Task] = []
    real_create = asyncio.create_task

    def _track(coro, **kw):
        t = real_create(coro, **kw)
        if (kw.get("name") or "").startswith("ops_heartbeat:"):
            live.append(t)
        return t

    async def _ok_pipeline():
        return {"status": "succeeded"}

    async def _boom_pipeline():
        raise ValueError("pipeline exploded")

    for pipeline in (_ok_pipeline, _boom_pipeline):
        live.clear()
        with patch.object(asyncio, "create_task", _track), patch.object(
            operations_repo, "start", lambda **_kw: None
        ), patch.object(operations_repo, "finalize", lambda **_kw: None), patch(
            "website.features.web_monitor.maybe_fire_app_error", lambda **_kw: None
        ), patch.object(zr, "OPS_HEARTBEAT_INTERVAL_S", 30):
            await zr._run(
                user_id=zr.UUID(int=2),
                operation_id="op-exit",
                pipeline=pipeline,
                persist_requested=True,
                url=None,
            )
        assert live, "heartbeat task was never spawned"
        await asyncio.sleep(0)
        assert live[0].cancelled() or live[0].done(), (
            f"heartbeat leaked for pipeline={pipeline.__name__}"
        )


def test_heartbeat_interval_well_under_reaper_window():
    """Dropped pings must not get a healthy job reclaimed and re-billed."""
    stale_window_s = 10 * 60  # migration 85 default
    assert zr.OPS_HEARTBEAT_INTERVAL_S * 4 < stale_window_s, (
        "heartbeat interval leaves too little margin before the reaper reclaims"
    )


# --- migration contract ----------------------------------------------------


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_reaper_requeues_before_dead_lettering():
    """The old reaper marked stale rows 'failed', destroying recoverable work."""
    sql = _sql()
    assert "ops_reclaim_stale" in sql
    assert "SET status = 'queued'" in sql, "reaper must requeue, not only fail"
    assert "s.attempts < s.max_attempts" in sql, "requeue must be bounded"
    assert "s.attempts >= s.max_attempts" in sql, "must dead-letter when exhausted"


def test_reaper_window_exceeds_longest_llm_call():
    """Reclaiming a LIVE job re-runs the pipeline and re-bills Gemini.

    Gemini has no idempotency key on generateContent, so the stale window must
    sit well above the worst-case call (~120s) plus jitter.
    """
    sql = _sql()
    m = re.search(r"DEFAULT interval '(\d+) minutes'", sql)
    assert m, "ops_reclaim_stale must declare an explicit default window"
    assert int(m.group(1)) * 60 >= 300, "stale window under the 300s safety floor"


def test_claim_uses_skip_locked_and_bounds_attempts():
    sql = _sql()
    assert "FOR UPDATE SKIP LOCKED" in sql, "2 workers would grab the same row"
    assert "o.attempts < o.max_attempts" in sql, "a poison job would loop forever"


def test_step_journal_respects_input_hash():
    """Reusing a result computed from different inputs is worse than recomputing."""
    sql = _sql()
    assert "input_hash" in sql
    assert "p_input_hash IS NULL OR input_hash IS NOT DISTINCT FROM p_input_hash" in sql


def test_new_table_has_explicit_service_role_grant():
    """RLS policies are NOT a substitute for a table grant (2026-05-21 outage)."""
    sql = _sql()
    assert re.search(
        r"GRANT .*ON core\.operation_steps TO service_role", sql
    ), "core.operation_steps missing explicit service_role grant"


def test_every_new_function_is_granted():
    sql = _sql()
    defined = set(re.findall(r"CREATE OR REPLACE FUNCTION core\.(\w+)\(", sql))
    granted = set(re.findall(r"GRANT EXECUTE ON FUNCTION core\.(\w+)\(", sql))
    assert defined, "no functions parsed — regex drifted from the migration"
    assert defined <= granted, f"missing service_role EXECUTE grant: {defined - granted}"


def test_down_migration_restores_a_working_reaper():
    """A rollback that leaves NO watchdog would strand rows until their TTL."""
    down = (
        REPO_ROOT / "supabase/website/_v2/85_operations_durable_retry.down.sql"
    ).read_text(encoding="utf-8")
    assert "cron.schedule" in down, "down-migration leaves no watchdog at all"
    assert "reap_stuck_running_operations" in down
    assert "DROP TABLE IF EXISTS core.operation_steps" in down
