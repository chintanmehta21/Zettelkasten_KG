"""Pin the Custom Access Token Hook (migration 76) shape contract.

The hook is registered out-of-band via the Supabase Dashboard, but the function
itself lives in the DB. These tests pin the function-level contract:

  1. The function exists with the correct signature and security flags.
  2. For an auth user with workspace memberships, the output JSON has the
     workspace_ids array under claims.app_metadata.
  3. For an auth user with no memberships, the array is empty (not null,
     not missing).
  4. For a user_id that doesn't exist in auth.users, the function returns
     a valid jsonb (empty array) without raising.
  5. Privileges: EXECUTE granted ONLY to supabase_auth_admin; revoked from
     PUBLIC, anon, authenticated.

These tests touch the live v2 Supabase project (see tests/integration/v2/
conftest.py) so they are marked ``@pytest.mark.live``.
"""
from __future__ import annotations

import json
import uuid

import pytest

pytestmark = pytest.mark.live


async def test_hook_function_exists_with_correct_security(asyncpg_pool):
    """Function exists, has SECURITY DEFINER, has SET search_path in proconfig."""
    async with asyncpg_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT p.prosecdef,
                   p.proconfig,
                   p.provolatile::text AS volatile,
                   pg_get_function_result(p.oid) AS rettype,
                   pg_get_function_arguments(p.oid) AS args
              FROM pg_proc p
              JOIN pg_namespace n ON n.oid = p.pronamespace
             WHERE n.nspname = 'core'
               AND p.proname = 'custom_access_token_hook'
            """
        )
    assert row is not None, "core.custom_access_token_hook missing from pg_proc"
    assert row["prosecdef"] is True, "must be SECURITY DEFINER"
    # STABLE volatility per the hook contract (read-only on auth.users +
    # core.workspace_members; gotrue may call this multiple times per request).
    assert row["volatile"] == "s", f"expected STABLE volatility, got {row['volatile']!r}"
    assert row["rettype"] == "jsonb", f"expected jsonb return, got {row['rettype']!r}"
    assert row["args"] == "event jsonb", f"unexpected args: {row['args']!r}"
    assert row["proconfig"] is not None and any(
        cfg.startswith("search_path=") for cfg in row["proconfig"]
    ), f"must SET search_path in pg_proc.proconfig (got {row['proconfig']!r})"


async def test_hook_injects_workspace_ids_for_member(asyncpg_pool, mint_user):
    """Member with 2 workspaces → claims.app_metadata.workspace_ids has 2 UUIDs."""
    user = mint_user(workspace_count=2)
    event = {
        "user_id": str(user.auth_user_id),
        "claims": {"sub": str(user.auth_user_id), "app_metadata": {}},
        "authentication_method": "oauth",
    }
    async with asyncpg_pool.acquire() as conn:
        result = await conn.fetchval(
            "SELECT core.custom_access_token_hook($1::jsonb)",
            json.dumps(event),
        )
    out = json.loads(result) if isinstance(result, str) else result
    ws_ids = out["claims"]["app_metadata"]["workspace_ids"]
    assert isinstance(ws_ids, list), f"workspace_ids must be list, got {type(ws_ids)}"
    assert len(ws_ids) == 2, f"expected 2 workspace_ids, got {len(ws_ids)}: {ws_ids!r}"
    assert all(isinstance(x, str) for x in ws_ids), "workspace_ids must be string UUIDs"
    # Sanity: every returned id is a valid UUID and matches one of the user's
    # actual workspaces.
    parsed = {uuid.UUID(x) for x in ws_ids}
    assert parsed == set(user.workspace_ids), (
        f"hook returned {parsed} but user has {set(user.workspace_ids)}"
    )


async def test_hook_returns_empty_array_for_unknown_user(asyncpg_pool):
    """Unknown user_id → workspace_ids is [] (NOT null, NOT missing)."""
    fake_user_id = uuid.uuid4()
    event = {
        "user_id": str(fake_user_id),
        "claims": {"sub": "stub", "app_metadata": {}},
        "authentication_method": "oauth",
    }
    async with asyncpg_pool.acquire() as conn:
        result = await conn.fetchval(
            "SELECT core.custom_access_token_hook($1::jsonb)",
            json.dumps(event),
        )
    out = json.loads(result) if isinstance(result, str) else result
    assert out["claims"]["app_metadata"]["workspace_ids"] == []


async def test_hook_preserves_existing_claims(asyncpg_pool, mint_user):
    """Other claims (role, sub, custom keys) must round-trip unchanged."""
    user = mint_user(workspace_count=1)
    event = {
        "user_id": str(user.auth_user_id),
        "claims": {
            "sub": str(user.auth_user_id),
            "role": "authenticated",
            "email": user.email,
            "aud": "authenticated",
            "app_metadata": {"provider": "google", "providers": ["google"]},
            "user_metadata": {"name": "Alice"},
        },
        "authentication_method": "oauth",
    }
    async with asyncpg_pool.acquire() as conn:
        result = await conn.fetchval(
            "SELECT core.custom_access_token_hook($1::jsonb)",
            json.dumps(event),
        )
    out = json.loads(result) if isinstance(result, str) else result
    # Pre-existing claims preserved
    assert out["claims"]["sub"] == str(user.auth_user_id)
    assert out["claims"]["role"] == "authenticated"
    assert out["claims"]["email"] == user.email
    assert out["claims"]["aud"] == "authenticated"
    assert out["claims"]["user_metadata"] == {"name": "Alice"}
    # app_metadata pre-existing keys preserved
    assert out["claims"]["app_metadata"]["provider"] == "google"
    assert out["claims"]["app_metadata"]["providers"] == ["google"]
    # workspace_ids injected
    assert len(out["claims"]["app_metadata"]["workspace_ids"]) == 1


async def test_hook_handles_missing_app_metadata(asyncpg_pool, mint_user):
    """If claims has no app_metadata key, the hook creates it before nested set."""
    user = mint_user(workspace_count=1)
    event = {
        "user_id": str(user.auth_user_id),
        "claims": {"sub": str(user.auth_user_id)},  # no app_metadata!
        "authentication_method": "oauth",
    }
    async with asyncpg_pool.acquire() as conn:
        result = await conn.fetchval(
            "SELECT core.custom_access_token_hook($1::jsonb)",
            json.dumps(event),
        )
    out = json.loads(result) if isinstance(result, str) else result
    assert "app_metadata" in out["claims"]
    assert isinstance(out["claims"]["app_metadata"]["workspace_ids"], list)


async def test_hook_grants_restrict_to_supabase_auth_admin(asyncpg_pool):
    """EXECUTE granted to supabase_auth_admin; revoked from PUBLIC, anon, authenticated.

    Defends the hook against being callable by an end-user JWT or anonymous
    request — only the gotrue role (which assumes supabase_auth_admin when
    invoking hooks) may execute it.
    """
    async with asyncpg_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT grantee, privilege_type
              FROM information_schema.role_routine_grants
             WHERE specific_schema = 'core'
               AND routine_name = 'custom_access_token_hook'
            """
        )
    grantees_with_execute = {
        row["grantee"] for row in rows if row["privilege_type"] == "EXECUTE"
    }
    assert "supabase_auth_admin" in grantees_with_execute, (
        f"supabase_auth_admin must have EXECUTE; grantees: {grantees_with_execute}"
    )
    # PUBLIC is the default grant — REVOKE must have stripped it.
    assert "PUBLIC" not in grantees_with_execute, (
        "EXECUTE on PUBLIC must be revoked (advisor lint 0028/0029)"
    )
    assert "anon" not in grantees_with_execute, "anon must not have EXECUTE"
    assert "authenticated" not in grantees_with_execute, (
        "authenticated must not have EXECUTE"
    )
