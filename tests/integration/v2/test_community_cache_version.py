"""Migration 89: content.community_cache_version counter + bump RPC.

@pytest.mark.live.
"""
from __future__ import annotations

import pytest

from website.core.supabase_v2.repositories.community_repository import (
    CommunityGraphRepository,
)

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_single_row_seeded(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        cnt = await conn.fetchval("SELECT count(*) FROM content.community_cache_version")
        ver = await conn.fetchval("SELECT version FROM content.community_cache_version LIMIT 1")
    assert cnt == 1, f"expected exactly one row, got {cnt}"
    assert ver is not None and ver >= 0


@pytest.mark.asyncio
async def test_bump_increments_monotonically(asyncpg_pool):
    repo = CommunityGraphRepository()
    before = repo.read_cache_version()
    after = repo.bump_cache_version()
    assert after == before + 1, f"bump not monotonic: {before} -> {after}"
    assert repo.read_cache_version() == after
