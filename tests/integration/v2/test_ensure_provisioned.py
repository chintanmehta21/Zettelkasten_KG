"""Pin the ensure_provisioned RPC (migration 77).

Idempotent JIT provisioning. Safe to call any number of times. Returns the
profile_id (== auth.users.id per schema invariant).

These tests touch the live v2 Supabase project (see tests/integration/v2/
conftest.py) so they are marked ``@pytest.mark.live``.

Note on the "missing membership repair" scenario:
The available fixture (``mint_user`` -> ``mint_test_user_with_workspaces``)
always runs the full auth -> profile -> workspace -> membership trigger chain
because the underlying ``auth.admin.create_user`` call fires ``on_auth_user_created``
synchronously. There is no fixture that creates an ``auth.users`` row while
suppressing the trigger. To exercise the "trigger failed silently, JIT repairs
the gap" path, we mint normally, then manually DELETE the membership row (and
let the partial-unique personal-workspace row stay) before calling
``ensure_provisioned``. The RPC must re-insert the membership row.
"""
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.live


async def test_ensure_provisioned_function_exists_with_correct_security(asyncpg_pool):
    """Function exists, SECURITY DEFINER, search_path pinned in proconfig."""
    async with asyncpg_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT p.prosecdef,
                   p.proconfig,
                   pg_get_function_result(p.oid) AS rettype,
                   pg_get_function_arguments(p.oid) AS args
              FROM pg_proc p
              JOIN pg_namespace n ON n.oid = p.pronamespace
             WHERE n.nspname = 'core'
               AND p.proname = 'ensure_provisioned'
            """
        )
    assert row is not None, "core.ensure_provisioned missing from pg_proc"
    assert row["prosecdef"] is True, "must be SECURITY DEFINER"
    assert row["rettype"] == "uuid"
    # Args string includes defaults; assert on the type signature shape.
    assert "p_auth_user_id uuid" in row["args"]
    assert "p_email text" in row["args"]
    assert "p_display_name text" in row["args"]
    assert row["proconfig"] is not None and any(
        cfg.startswith("search_path=") for cfg in row["proconfig"]
    ), f"must SET search_path in proconfig (got {row['proconfig']!r})"


async def test_ensure_provisioned_is_idempotent(asyncpg_pool, mint_user):
    """Calling twice on a fully-provisioned user is a no-op; profile_id stable."""
    user = mint_user(workspace_count=1)
    async with asyncpg_pool.acquire() as conn:
        first = await conn.fetchval(
            "SELECT core.ensure_provisioned($1::uuid, NULL, NULL)",
            user.auth_user_id,
        )
        second = await conn.fetchval(
            "SELECT core.ensure_provisioned($1::uuid, NULL, NULL)",
            user.auth_user_id,
        )
    assert first == user.profile_id, f"first call returned {first!r} != {user.profile_id!r}"
    assert second == user.profile_id, f"second call returned {second!r}"

    # Verify no extra workspaces or memberships were created.
    async with asyncpg_pool.acquire() as conn:
        member_count = await conn.fetchval(
            "SELECT count(*) FROM core.workspace_members WHERE profile_id = $1",
            user.profile_id,
        )
        ws_count = await conn.fetchval(
            "SELECT count(*) FROM core.workspaces WHERE owner_profile_id = $1",
            user.profile_id,
        )
    assert member_count == 1, f"expected 1 membership, got {member_count}"
    assert ws_count == 1, f"expected 1 workspace, got {ws_count}"


async def test_ensure_provisioned_repairs_missing_membership(asyncpg_pool, mint_user):
    """If the membership row is gone, the RPC re-creates it.

    Mirrors the "trigger fired but row was wiped out-of-band" failure mode.
    The workspace row stays (partial-unique idx_workspaces_owner_personal
    means the RPC's INSERT INTO workspaces will hit the conflict path and
    look up the existing id).
    """
    user = mint_user(workspace_count=1)
    workspace_id = user.workspace_ids[0]

    # Sanity: starting state has exactly 1 membership.
    async with asyncpg_pool.acquire() as conn:
        before = await conn.fetchval(
            "SELECT count(*) FROM core.workspace_members WHERE profile_id = $1",
            user.profile_id,
        )
    assert before == 1, f"setup precondition failed: starting members = {before}"

    # Wipe the membership row to simulate the trigger-failure window.
    async with asyncpg_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM core.workspace_members WHERE profile_id = $1",
            user.profile_id,
        )
        gone = await conn.fetchval(
            "SELECT count(*) FROM core.workspace_members WHERE profile_id = $1",
            user.profile_id,
        )
    assert gone == 0, "membership wipe did not take"

    # JIT repair.
    async with asyncpg_pool.acquire() as conn:
        returned_profile_id = await conn.fetchval(
            "SELECT core.ensure_provisioned($1::uuid, NULL, NULL)",
            user.auth_user_id,
        )
    assert returned_profile_id == user.profile_id

    # Membership row is back, and it points at the *same* workspace (partial
    # unique index prevented a second personal workspace from being created).
    async with asyncpg_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT workspace_id, role
              FROM core.workspace_members
             WHERE profile_id = $1
            """,
            user.profile_id,
        )
    assert len(rows) == 1, f"expected 1 membership after repair, got {len(rows)}"
    assert rows[0]["workspace_id"] == workspace_id, (
        f"new membership points at workspace {rows[0]['workspace_id']} != "
        f"original {workspace_id} (partial unique should have made repair use the same row)"
    )
    assert rows[0]["role"] == "owner"


async def test_ensure_provisioned_creates_profile_for_orphan_auth_user(asyncpg_pool, mint_user):
    """Profile row missing → RPC creates it AND the personal workspace + membership.

    Simulates the gotrue OAuth code-ordering defect: auth.users row landed,
    but the AFTER INSERT trigger never produced a profile row. We force this
    by deleting the profile row (CASCADE wipes workspaces+memberships).
    """
    user = mint_user(workspace_count=1)

    async with asyncpg_pool.acquire() as conn:
        # CASCADE deletes through profile -> workspaces -> workspace_members.
        await conn.execute(
            "DELETE FROM core.profiles WHERE id = $1",
            user.profile_id,
        )
        profile_gone = await conn.fetchval(
            "SELECT count(*) FROM core.profiles WHERE id = $1",
            user.profile_id,
        )
    assert profile_gone == 0, "profile delete did not take"

    # JIT repair.
    async with asyncpg_pool.acquire() as conn:
        returned_profile_id = await conn.fetchval(
            "SELECT core.ensure_provisioned($1::uuid, NULL, NULL)",
            user.auth_user_id,
        )
    assert returned_profile_id == user.auth_user_id

    # All three rows back: profile + workspace + membership.
    async with asyncpg_pool.acquire() as conn:
        profile_count = await conn.fetchval(
            "SELECT count(*) FROM core.profiles WHERE id = $1",
            user.auth_user_id,
        )
        ws_count = await conn.fetchval(
            "SELECT count(*) FROM core.workspaces WHERE owner_profile_id = $1 AND is_personal",
            user.auth_user_id,
        )
        member_count = await conn.fetchval(
            "SELECT count(*) FROM core.workspace_members WHERE profile_id = $1",
            user.auth_user_id,
        )
    assert profile_count == 1, "profile not re-created"
    assert ws_count == 1, "personal workspace not re-created"
    assert member_count == 1, "owner membership not re-created"


async def test_ensure_provisioned_resolves_email_from_auth_users(asyncpg_pool, mint_user):
    """If p_email is NULL, the RPC pulls it from auth.users."""
    user = mint_user(workspace_count=1)

    # Delete profile to force the insert path.
    async with asyncpg_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM core.profiles WHERE id = $1",
            user.profile_id,
        )
        await conn.fetchval(
            "SELECT core.ensure_provisioned($1::uuid, NULL, NULL)",
            user.auth_user_id,
        )
        email_from_profile = await conn.fetchval(
            "SELECT email FROM core.profiles WHERE id = $1",
            user.auth_user_id,
        )
    assert email_from_profile == user.email, (
        f"expected email pulled from auth.users ({user.email}), got {email_from_profile!r}"
    )


async def test_ensure_provisioned_rejects_null_user_id(asyncpg_pool):
    """NULL p_auth_user_id raises an explicit error (not a silent FK violation)."""
    async with asyncpg_pool.acquire() as conn:
        with pytest.raises(Exception) as exc_info:
            await conn.fetchval(
                "SELECT core.ensure_provisioned(NULL::uuid, NULL, NULL)"
            )
    # asyncpg surfaces RAISE EXCEPTION as InvalidParameterValueError /
    # PostgresError. Check the message rather than the type so a future
    # asyncpg version can still pass.
    assert "p_auth_user_id" in str(exc_info.value).lower() or "null" in str(exc_info.value).lower()


async def test_ensure_provisioned_grants(asyncpg_pool):
    """EXECUTE granted to authenticated + service_role; revoked from PUBLIC, anon."""
    async with asyncpg_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT grantee, privilege_type
              FROM information_schema.role_routine_grants
             WHERE specific_schema = 'core'
               AND routine_name = 'ensure_provisioned'
            """
        )
    grantees = {row["grantee"] for row in rows if row["privilege_type"] == "EXECUTE"}
    assert "authenticated" in grantees, f"authenticated must have EXECUTE; grantees={grantees}"
    assert "service_role" in grantees, f"service_role must have EXECUTE; grantees={grantees}"
    assert "PUBLIC" not in grantees, "EXECUTE on PUBLIC must be revoked"
    assert "anon" not in grantees, "anon must not have EXECUTE"
