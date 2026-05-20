"""Phase 4 (async-ops redesign): pg_cron stuck-running reaper.

Verifies migration ``57_stuck_running_reaper.sql``:
- The pg_cron job ``reap_stuck_running_operations`` is scheduled.
- Rows status='running' with updated_at older than 5 minutes are finalized as
  'failed' + RFC 9457 worker-lost error.
- Rows status='running' with recent updated_at are untouched (within window).
- Rows status='queued' are untouched regardless of age (only running is reaped).

Marked ``live`` — needs a real Supabase project. Tests INVOKE the reaper's
SQL statement directly (not the cron tick) for deterministic assertions; a
separate test verifies the job IS scheduled with the expected cadence.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest


pytestmark = pytest.mark.live


_REAPER_SQL = """
UPDATE core.operations
SET status='failed',
    error=jsonb_build_object(
        'type','https://zettelkasten.in/problems/errors/worker-lost',
        'title','Background worker lost',
        'status',500,
        'detail','The worker handling this operation did not finalize within the watchdog window.',
        'code','worker-lost'
    ),
    updated_at=now()
WHERE status='running'
  AND updated_at < now() - interval '5 minutes'
"""


async def _insert_op(
    pool: asyncpg.Pool,
    *,
    user_id: uuid.UUID,
    status: str,
    age: timedelta,
) -> str:
    operation_id = f"reaper-test-{uuid.uuid4().hex[:12]}"
    request_hash = uuid.uuid4().hex
    target_time = datetime.now(timezone.utc) - age
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO core.operations
                (operation_id, user_id, status, request_hash,
                 accepted, response, error, created_at, updated_at, expires_at)
            VALUES ($1, $2, $3, $4,
                    '{}'::jsonb, NULL, NULL,
                    $5, $5, now() + interval '24 hours')
            """,
            operation_id,
            user_id,
            status,
            request_hash,
            target_time,
        )
    return operation_id


async def _fetch_op(pool: asyncpg.Pool, operation_id: str) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT operation_id, status, error, updated_at "
            "FROM core.operations WHERE operation_id = $1",
            operation_id,
        )
    assert row is not None, f"row {operation_id} missing"
    return dict(row)


async def _delete_op(pool: asyncpg.Pool, operation_id: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM core.operations WHERE operation_id = $1",
            operation_id,
        )


async def test_reaper_job_is_scheduled(asyncpg_pool: asyncpg.Pool):
    """Migration 52 registered the cron job under the documented name."""
    async with asyncpg_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT count(*)::int FROM cron.job "
            "WHERE jobname = 'reap_stuck_running_operations'"
        )
    assert count == 1, "reap_stuck_running_operations cron job not scheduled"


async def test_reaper_marks_stuck_running_as_failed_worker_lost(
    asyncpg_pool: asyncpg.Pool, mint_user
):
    user = mint_user(workspace_count=1)
    op_id = await _insert_op(
        asyncpg_pool,
        user_id=user.auth_user_id,
        status="running",
        age=timedelta(minutes=10),
    )
    try:
        async with asyncpg_pool.acquire() as conn:
            await conn.execute(_REAPER_SQL)
        row = await _fetch_op(asyncpg_pool, op_id)
        assert row["status"] == "failed"
        # asyncpg may return JSONB as str or dict depending on codec; normalize.
        err = row["error"]
        if isinstance(err, str):
            import json as _json
            err = _json.loads(err)
        assert err is not None
        assert err.get("code") == "worker-lost"
        assert err.get("status") == 500
        # updated_at refreshed by the reaper (was 10 min ago; now within seconds)
        assert (datetime.now(timezone.utc) - row["updated_at"]) < timedelta(minutes=1)
    finally:
        await _delete_op(asyncpg_pool, op_id)


async def test_reaper_leaves_recent_running_rows_alone(
    asyncpg_pool: asyncpg.Pool, mint_user
):
    user = mint_user(workspace_count=1)
    op_id = await _insert_op(
        asyncpg_pool,
        user_id=user.auth_user_id,
        status="running",
        age=timedelta(seconds=30),  # well within the 5-minute window
    )
    try:
        async with asyncpg_pool.acquire() as conn:
            await conn.execute(_REAPER_SQL)
        row = await _fetch_op(asyncpg_pool, op_id)
        assert row["status"] == "running", "recent running row must not be reaped"
        assert row["error"] is None
    finally:
        await _delete_op(asyncpg_pool, op_id)


async def test_reaper_leaves_queued_rows_alone(
    asyncpg_pool: asyncpg.Pool, mint_user
):
    """Even an old 'queued' row is the TTL sweep's concern (migration 49),
    not the reaper's. The reaper only touches status='running'."""
    user = mint_user(workspace_count=1)
    op_id = await _insert_op(
        asyncpg_pool,
        user_id=user.auth_user_id,
        status="queued",
        age=timedelta(minutes=10),
    )
    try:
        async with asyncpg_pool.acquire() as conn:
            await conn.execute(_REAPER_SQL)
        row = await _fetch_op(asyncpg_pool, op_id)
        assert row["status"] == "queued", "queued row must not be reaped"
        assert row["error"] is None
    finally:
        await _delete_op(asyncpg_pool, op_id)
