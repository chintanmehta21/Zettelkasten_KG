"""Schema assertions for migration 85 (privacy columns on workspace_zettels).

Marked @pytest.mark.live — introspects the live v2 Postgres catalog via the
direct asyncpg pool. No user data is written.

Opt-OUT model: is_private DEFAULT false (default PUBLIC); made_private_at nullable.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_is_private_column_exists_default_false_not_null(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT data_type, is_nullable, column_default
              FROM information_schema.columns
             WHERE table_schema = 'content'
               AND table_name = 'workspace_zettels'
               AND column_name = 'is_private'
            """
        )
    assert row is not None, "is_private column missing"
    assert row["data_type"] == "boolean"
    assert row["is_nullable"] == "NO"
    # Default FALSE = PUBLIC-by-default (the whole point of the opt-out flip).
    assert "false" in (row["column_default"] or "").lower()


@pytest.mark.asyncio
async def test_made_private_at_column_exists_nullable_timestamptz(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT data_type, is_nullable
              FROM information_schema.columns
             WHERE table_schema = 'content'
               AND table_name = 'workspace_zettels'
               AND column_name = 'made_private_at'
            """
        )
    assert row is not None, "made_private_at column missing"
    assert row["data_type"] == "timestamp with time zone"
    assert row["is_nullable"] == "YES"


@pytest.mark.asyncio
async def test_legacy_publish_columns_absent(asyncpg_pool):
    """The opt-in columns must NOT exist under the opt-out model."""
    async with asyncpg_pool.acquire() as conn:
        present = {
            r["column_name"]
            for r in await conn.fetch(
                """
                SELECT column_name
                  FROM information_schema.columns
                 WHERE table_schema = 'content'
                   AND table_name = 'workspace_zettels'
                   AND column_name IN ('is_published', 'published_at', 'attribution')
                """
            )
        }
    assert present == set(), f"legacy opt-in columns must be absent, found {present}"


@pytest.mark.asyncio
async def test_community_partial_index_exists(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        ddl = await conn.fetchval(
            """
            SELECT indexdef
              FROM pg_indexes
             WHERE schemaname = 'content'
               AND tablename = 'workspace_zettels'
               AND indexname = 'idx_workspace_zettels_community'
            """
        )
    assert ddl is not None, "idx_workspace_zettels_community missing"
    assert "is_private" in ddl.lower()
    assert "where" in ddl.lower()  # partial
