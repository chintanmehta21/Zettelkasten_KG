"""Migration 86: append-only content.zettel_privacy_events audit table.

@pytest.mark.live — uses the direct asyncpg pool + mint_user + bulk_insert_zettels.
Records each make_private / make_public action (privacy demonstrability).
"""
from __future__ import annotations

import asyncpg
import pytest

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_table_exists_with_expected_columns(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        cols = {
            r["column_name"]: r["data_type"]
            for r in await conn.fetch(
                """
                SELECT column_name, data_type
                  FROM information_schema.columns
                 WHERE table_schema = 'content'
                   AND table_name = 'zettel_privacy_events'
                """
            )
        }
    for c in ("id", "actor_user_id", "workspace_zettel_id", "action", "created_at"):
        assert c in cols, f"missing column {c}: {cols}"


@pytest.mark.asyncio
async def test_action_check_enforced(asyncpg_pool, mint_user, bulk_insert_zettels):
    user = mint_user(workspace_count=1)
    wz_id = (await bulk_insert_zettels(owner_user=user, n=1, prefix="privacy"))[0]
    async with asyncpg_pool.acquire() as conn:
        # Valid inserts OK.
        await conn.execute(
            """
            INSERT INTO content.zettel_privacy_events
              (actor_user_id, workspace_zettel_id, action)
            VALUES ($1, $2, 'make_private')
            """,
            user.profile_id, wz_id,
        )
        await conn.execute(
            """
            INSERT INTO content.zettel_privacy_events
              (actor_user_id, workspace_zettel_id, action)
            VALUES ($1, $2, 'make_public')
            """,
            user.profile_id, wz_id,
        )
        # Bad action rejected by CHECK.
        with pytest.raises(asyncpg.PostgresError):
            await conn.execute(
                """
                INSERT INTO content.zettel_privacy_events
                  (actor_user_id, workspace_zettel_id, action)
                VALUES ($1, $2, 'nuke')
                """,
                user.profile_id, wz_id,
            )


@pytest.mark.asyncio
async def test_service_role_has_no_update_or_delete_grant(asyncpg_pool):
    """Append-only: service_role may SELECT/INSERT but not UPDATE/DELETE."""
    async with asyncpg_pool.acquire() as conn:
        privs = {
            r["privilege_type"]
            for r in await conn.fetch(
                """
                SELECT privilege_type
                  FROM information_schema.role_table_grants
                 WHERE table_schema = 'content'
                   AND table_name = 'zettel_privacy_events'
                   AND grantee = 'service_role'
                """
            )
        }
    assert "SELECT" in privs and "INSERT" in privs
    assert "UPDATE" not in privs, f"append-only violated: {privs}"
    assert "DELETE" not in privs, f"append-only violated: {privs}"
