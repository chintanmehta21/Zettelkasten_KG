"""Integration tests for the core.operations state-machine RPCs (migration 51).

Phase 1 of the async-ops redesign. Exercises ops_accept / ops_start /
ops_finalize against the live v2 Supabase project. Each test asserts on the
actual post-condition row state via direct asyncpg SELECTs — not on RPC
return values alone — so a regression in the SQL function body cannot pass
the test by virtue of returning the right shape while leaving the DB wrong.

Marked @pytest.mark.live (matches every other tests/integration/v2/*
module). Skipped by default; run with `pytest --live` once SUPABASE_*
credentials are present in env.

Cleanup: the tests INSERT into core.operations directly via the RPC; rows
are deleted explicitly in a try/finally per test. The mint_user fixture
handles auth.users cleanup at teardown.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg
import pytest


pytestmark = pytest.mark.live


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _fresh_op_id() -> str:
    return f"op-{uuid.uuid4().hex[:16]}"


def _fresh_hash() -> str:
    return uuid.uuid4().hex


async def _accept(
    pool: asyncpg.Pool,
    *,
    user_id: uuid.UUID,
    operation_id: str,
    request_hash: str,
    accepted: dict[str, Any] | None = None,
    ttl_seconds: int = 86400,
) -> dict[str, Any]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT operation_id, status, is_new FROM core.ops_accept("
            "$1::uuid, $2::text, $3::text, $4::jsonb, $5::int)",
            user_id,
            operation_id,
            request_hash,
            json.dumps(accepted or {"accepted": True}),
            ttl_seconds,
        )
    assert row is not None, "ops_accept returned no row — invariant violated"
    return dict(row)


async def _start(
    pool: asyncpg.Pool, *, user_id: uuid.UUID, operation_id: str
) -> str | None:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT core.ops_start($1::uuid, $2::text)", user_id, operation_id
        )


async def _finalize(
    pool: asyncpg.Pool,
    *,
    user_id: uuid.UUID,
    operation_id: str,
    target: str,
    response: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> str | None:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT core.ops_finalize($1::uuid, $2::text, $3::text, $4::jsonb, $5::jsonb)",
            user_id,
            operation_id,
            target,
            json.dumps(response) if response is not None else None,
            json.dumps(error) if error is not None else None,
        )


async def _row(
    pool: asyncpg.Pool, *, user_id: uuid.UUID, operation_id: str
) -> dict[str, Any] | None:
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT user_id, operation_id, request_hash, status, response, "
            "error, created_at, updated_at "
            "FROM core.operations WHERE user_id = $1 AND operation_id = $2",
            user_id,
            operation_id,
        )
    return dict(r) if r else None


async def _delete(
    pool: asyncpg.Pool, *, user_id: uuid.UUID, operation_id: str
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM core.operations WHERE user_id = $1 AND operation_id = $2",
            user_id,
            operation_id,
        )


async def _delete_by_user(pool: asyncpg.Pool, *, user_id: uuid.UUID) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM core.operations WHERE user_id = $1", user_id
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
async def test_accept_inserts_queued_when_no_conflict(asyncpg_pool, mint_user):
    user = mint_user(workspace_count=1)
    op_id = _fresh_op_id()
    req_hash = _fresh_hash()
    try:
        result = await _accept(
            asyncpg_pool,
            user_id=user.auth_user_id,
            operation_id=op_id,
            request_hash=req_hash,
        )
        assert result["is_new"] is True
        assert result["operation_id"] == op_id
        assert result["status"] == "queued"

        row = await _row(
            asyncpg_pool, user_id=user.auth_user_id, operation_id=op_id
        )
        assert row is not None
        assert row["status"] == "queued"
        assert row["request_hash"] == req_hash
        assert row["error"] is None
    finally:
        await _delete(asyncpg_pool, user_id=user.auth_user_id, operation_id=op_id)


async def test_accept_idempotent_returns_existing_while_active(
    asyncpg_pool, mint_user
):
    user = mint_user(workspace_count=1)
    op_id = _fresh_op_id()
    req_hash = _fresh_hash()
    try:
        first = await _accept(
            asyncpg_pool,
            user_id=user.auth_user_id,
            operation_id=op_id,
            request_hash=req_hash,
        )
        assert first["is_new"] is True

        # Second accept with the SAME hash but a DIFFERENT op_id must NOT
        # insert; it returns the original op_id with is_new=false.
        second = await _accept(
            asyncpg_pool,
            user_id=user.auth_user_id,
            operation_id=_fresh_op_id(),
            request_hash=req_hash,
        )
        assert second["is_new"] is False
        assert second["operation_id"] == op_id
        assert second["status"] == "queued"
    finally:
        await _delete_by_user(asyncpg_pool, user_id=user.auth_user_id)


async def test_accept_does_not_dedup_after_terminal_failed(
    asyncpg_pool, mint_user
):
    user = mint_user(workspace_count=1)
    req_hash = _fresh_hash()
    op1 = _fresh_op_id()
    op2 = _fresh_op_id()
    try:
        await _accept(
            asyncpg_pool,
            user_id=user.auth_user_id,
            operation_id=op1,
            request_hash=req_hash,
        )
        await _start(
            asyncpg_pool, user_id=user.auth_user_id, operation_id=op1
        )
        finalized = await _finalize(
            asyncpg_pool,
            user_id=user.auth_user_id,
            operation_id=op1,
            target="failed",
            error={"code": "bg_failure", "title": "test"},
        )
        assert finalized == "failed"

        # Partial index excludes 'failed' — fresh accept must succeed with a
        # new op_id (retry-after-failure semantics).
        second = await _accept(
            asyncpg_pool,
            user_id=user.auth_user_id,
            operation_id=op2,
            request_hash=req_hash,
        )
        assert second["is_new"] is True
        assert second["operation_id"] == op2
        assert second["status"] == "queued"
    finally:
        await _delete_by_user(asyncpg_pool, user_id=user.auth_user_id)


async def test_accept_dedups_after_terminal_succeeded(asyncpg_pool, mint_user):
    user = mint_user(workspace_count=1)
    req_hash = _fresh_hash()
    op1 = _fresh_op_id()
    try:
        await _accept(
            asyncpg_pool,
            user_id=user.auth_user_id,
            operation_id=op1,
            request_hash=req_hash,
        )
        await _start(
            asyncpg_pool, user_id=user.auth_user_id, operation_id=op1
        )
        finalized = await _finalize(
            asyncpg_pool,
            user_id=user.auth_user_id,
            operation_id=op1,
            target="succeeded",
            response={"zettel_id": "z-123"},
        )
        assert finalized == "succeeded"

        # Stripe semantics: replay returns same op_id with is_new=false.
        replay = await _accept(
            asyncpg_pool,
            user_id=user.auth_user_id,
            operation_id=_fresh_op_id(),
            request_hash=req_hash,
        )
        assert replay["is_new"] is False
        assert replay["operation_id"] == op1
        assert replay["status"] == "succeeded"
    finally:
        await _delete_by_user(asyncpg_pool, user_id=user.auth_user_id)


async def test_start_only_transitions_queued_to_running(asyncpg_pool, mint_user):
    user = mint_user(workspace_count=1)
    op_id = _fresh_op_id()
    try:
        await _accept(
            asyncpg_pool,
            user_id=user.auth_user_id,
            operation_id=op_id,
            request_hash=_fresh_hash(),
        )
        first = await _start(
            asyncpg_pool, user_id=user.auth_user_id, operation_id=op_id
        )
        assert first == "running"

        # Second call: row is already running, no transition fires.
        second = await _start(
            asyncpg_pool, user_id=user.auth_user_id, operation_id=op_id
        )
        assert second is None

        row = await _row(
            asyncpg_pool, user_id=user.auth_user_id, operation_id=op_id
        )
        assert row is not None and row["status"] == "running"
    finally:
        await _delete(asyncpg_pool, user_id=user.auth_user_id, operation_id=op_id)


async def test_start_returns_null_for_nonexistent_op(asyncpg_pool, mint_user):
    user = mint_user(workspace_count=1)
    result = await _start(
        asyncpg_pool,
        user_id=user.auth_user_id,
        operation_id=_fresh_op_id(),
    )
    assert result is None


async def test_finalize_succeeded_writes_response_nulls_error(
    asyncpg_pool, mint_user
):
    user = mint_user(workspace_count=1)
    op_id = _fresh_op_id()
    try:
        await _accept(
            asyncpg_pool,
            user_id=user.auth_user_id,
            operation_id=op_id,
            request_hash=_fresh_hash(),
        )
        await _start(
            asyncpg_pool, user_id=user.auth_user_id, operation_id=op_id
        )
        result = await _finalize(
            asyncpg_pool,
            user_id=user.auth_user_id,
            operation_id=op_id,
            target="succeeded",
            response={"zettel_id": "z-xyz", "title": "ok"},
            error=None,
        )
        assert result == "succeeded"

        row = await _row(
            asyncpg_pool, user_id=user.auth_user_id, operation_id=op_id
        )
        assert row is not None
        assert row["status"] == "succeeded"
        assert row["error"] is None
        # asyncpg returns jsonb as str — parse before asserting on shape.
        resp = (
            json.loads(row["response"])
            if isinstance(row["response"], str)
            else row["response"]
        )
        assert resp == {"zettel_id": "z-xyz", "title": "ok"}
    finally:
        await _delete(asyncpg_pool, user_id=user.auth_user_id, operation_id=op_id)


async def test_finalize_failed_writes_error_nulls_response(
    asyncpg_pool, mint_user
):
    user = mint_user(workspace_count=1)
    op_id = _fresh_op_id()
    try:
        await _accept(
            asyncpg_pool,
            user_id=user.auth_user_id,
            operation_id=op_id,
            request_hash=_fresh_hash(),
        )
        await _start(
            asyncpg_pool, user_id=user.auth_user_id, operation_id=op_id
        )
        err_body = {
            "type": "https://zettelkasten.in/problems/upstream",
            "title": "Upstream failure",
            "status": 502,
            "code": "upstream_failure",
        }
        result = await _finalize(
            asyncpg_pool,
            user_id=user.auth_user_id,
            operation_id=op_id,
            target="failed",
            response=None,
            error=err_body,
        )
        assert result == "failed"

        row = await _row(
            asyncpg_pool, user_id=user.auth_user_id, operation_id=op_id
        )
        assert row is not None
        assert row["status"] == "failed"
        assert row["response"] is None
        err = (
            json.loads(row["error"])
            if isinstance(row["error"], str)
            else row["error"]
        )
        assert err == err_body
    finally:
        await _delete(asyncpg_pool, user_id=user.auth_user_id, operation_id=op_id)


async def test_finalize_after_terminal_is_no_op(asyncpg_pool, mint_user):
    """THE bug-class killer: second finalize against terminal must NOT mutate."""
    user = mint_user(workspace_count=1)
    op_id = _fresh_op_id()
    try:
        await _accept(
            asyncpg_pool,
            user_id=user.auth_user_id,
            operation_id=op_id,
            request_hash=_fresh_hash(),
        )
        await _start(
            asyncpg_pool, user_id=user.auth_user_id, operation_id=op_id
        )
        first = await _finalize(
            asyncpg_pool,
            user_id=user.auth_user_id,
            operation_id=op_id,
            target="succeeded",
            response={"zettel_id": "z-first"},
        )
        assert first == "succeeded"
        row_before = await _row(
            asyncpg_pool, user_id=user.auth_user_id, operation_id=op_id
        )
        assert row_before is not None
        updated_at_before = row_before["updated_at"]

        # Attempt to clobber the succeeded row with a failed finalize.
        second = await _finalize(
            asyncpg_pool,
            user_id=user.auth_user_id,
            operation_id=op_id,
            target="failed",
            error={"code": "should_not_apply"},
        )
        assert second is None  # state guard fired

        row_after = await _row(
            asyncpg_pool, user_id=user.auth_user_id, operation_id=op_id
        )
        assert row_after is not None
        assert row_after["status"] == "succeeded"  # untouched
        assert row_after["error"] is None
        # updated_at must NOT have advanced — the UPDATE never fired.
        assert row_after["updated_at"] == updated_at_before
        resp = (
            json.loads(row_after["response"])
            if isinstance(row_after["response"], str)
            else row_after["response"]
        )
        assert resp == {"zettel_id": "z-first"}
    finally:
        await _delete(asyncpg_pool, user_id=user.auth_user_id, operation_id=op_id)


async def test_finalize_cancelled_idempotent_under_duplicate_cancel(
    asyncpg_pool, mint_user
):
    user = mint_user(workspace_count=1)
    op_id = _fresh_op_id()
    try:
        await _accept(
            asyncpg_pool,
            user_id=user.auth_user_id,
            operation_id=op_id,
            request_hash=_fresh_hash(),
        )
        await _start(
            asyncpg_pool, user_id=user.auth_user_id, operation_id=op_id
        )
        first = await _finalize(
            asyncpg_pool,
            user_id=user.auth_user_id,
            operation_id=op_id,
            target="cancelled",
            error={"code": "client_cancelled"},
        )
        assert first == "cancelled"

        second = await _finalize(
            asyncpg_pool,
            user_id=user.auth_user_id,
            operation_id=op_id,
            target="cancelled",
            error={"code": "client_cancelled"},
        )
        assert second is None  # already terminal

        row = await _row(
            asyncpg_pool, user_id=user.auth_user_id, operation_id=op_id
        )
        assert row is not None and row["status"] == "cancelled"
    finally:
        await _delete(asyncpg_pool, user_id=user.auth_user_id, operation_id=op_id)


async def test_finalize_rejects_invalid_target(asyncpg_pool, mint_user):
    user = mint_user(workspace_count=1)
    op_id = _fresh_op_id()
    try:
        await _accept(
            asyncpg_pool,
            user_id=user.auth_user_id,
            operation_id=op_id,
            request_hash=_fresh_hash(),
        )
        # 'queued' is a valid status BUT not a valid finalize TARGET — must raise.
        with pytest.raises(asyncpg.PostgresError) as exc_info:
            await _finalize(
                asyncpg_pool,
                user_id=user.auth_user_id,
                operation_id=op_id,
                target="queued",
            )
        assert "invalid target" in str(exc_info.value).lower() or \
               "ops_finalize" in str(exc_info.value)

        # Row must be untouched.
        row = await _row(
            asyncpg_pool, user_id=user.auth_user_id, operation_id=op_id
        )
        assert row is not None and row["status"] == "queued"
    finally:
        await _delete(asyncpg_pool, user_id=user.auth_user_id, operation_id=op_id)


async def test_cross_user_isolation_same_request_hash(asyncpg_pool, mint_user):
    """Partial unique index is scoped to (user_id, request_hash); two
    different users can hold the same request_hash simultaneously."""
    user_a = mint_user(workspace_count=1)
    user_b = mint_user(workspace_count=1)
    shared_hash = _fresh_hash()
    op_a = _fresh_op_id()
    op_b = _fresh_op_id()
    try:
        result_a = await _accept(
            asyncpg_pool,
            user_id=user_a.auth_user_id,
            operation_id=op_a,
            request_hash=shared_hash,
        )
        result_b = await _accept(
            asyncpg_pool,
            user_id=user_b.auth_user_id,
            operation_id=op_b,
            request_hash=shared_hash,
        )
        assert result_a["is_new"] is True
        assert result_b["is_new"] is True
        assert result_a["operation_id"] == op_a
        assert result_b["operation_id"] == op_b
    finally:
        await _delete_by_user(asyncpg_pool, user_id=user_a.auth_user_id)
        await _delete_by_user(asyncpg_pool, user_id=user_b.auth_user_id)
