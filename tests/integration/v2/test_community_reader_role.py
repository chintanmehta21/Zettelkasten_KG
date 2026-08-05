"""Migration 87: community_reader least-privilege role + RLS fail-closed.

The decisive privacy upgrade: community_reader is NOLOGIN + NOT BYPASSRLS +
SELECT-only on the community surface. We prove fail-closed by SET ROLE
community_reader on the asyncpg connection (service_role/superuser session)
and asserting a PRIVATE row is invisible even with a bare SELECT, while a
default (public) row is visible.

@pytest.mark.live.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_role_exists_nologin_not_bypassrls(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT rolcanlogin, rolbypassrls FROM pg_roles WHERE rolname = 'community_reader'"
        )
    assert row is not None, "community_reader role missing"
    assert row["rolcanlogin"] is False, "must be NOLOGIN"
    assert row["rolbypassrls"] is False, "must NOT bypass RLS (the whole point)"


@pytest.mark.asyncio
async def test_role_has_select_grants_on_community_surface(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        granted = {
            (r["table_schema"], r["table_name"])
            for r in await conn.fetch(
                """
                SELECT table_schema, table_name
                  FROM information_schema.role_table_grants
                 WHERE grantee = 'community_reader' AND privilege_type = 'SELECT'
                """
            )
        }
    assert ("content", "workspace_zettels") in granted
    assert ("content", "canonical_zettels") in granted
    assert ("core", "workspaces") in granted
    assert ("core", "profiles") in granted


@pytest.mark.asyncio
async def test_rls_fails_closed_under_set_role(asyncpg_pool, mint_user, bulk_insert_zettels):
    """A bare SELECT as community_reader returns ONLY public (is_private=false) rows."""
    user = mint_user(workspace_count=1)
    wz_ids = await bulk_insert_zettels(owner_user=user, n=2, prefix="failclosed")
    public_id, private_id = wz_ids[0], wz_ids[1]
    async with asyncpg_pool.acquire() as conn:
        # bulk_insert_zettels creates default (public) rows; mark one private.
        await conn.execute(
            "UPDATE content.workspace_zettels SET is_private = true, made_private_at = now() WHERE id = $1",
            private_id,
        )
        # Impersonate the non-BYPASSRLS role within this (superuser) session.
        await conn.execute("SET ROLE community_reader")
        try:
            visible = {
                r["id"]
                for r in await conn.fetch(
                    "SELECT id FROM content.workspace_zettels WHERE id = ANY($1::uuid[])",
                    [public_id, private_id],
                )
            }
        finally:
            await conn.execute("RESET ROLE")
    assert public_id in visible, "public row must be visible to community_reader"
    assert private_id not in visible, "PRIVATE row leaked to community_reader — RLS not fail-closed"
