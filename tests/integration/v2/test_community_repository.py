"""CommunityGraphRepository: the single forced-predicate app read path.

@pytest.mark.live.
"""
from __future__ import annotations

import pytest

from website.core.supabase_v2.repositories.community_repository import (
    CommunityGraphRepository,
)

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_get_community_graph_returns_public_only(asyncpg_pool, mint_user, bulk_insert_zettels):
    user = mint_user(workspace_count=1)
    wz_ids = await bulk_insert_zettels(owner_user=user, n=2, prefix="repo")
    public_id, private_id = wz_ids[0], wz_ids[1]
    async with asyncpg_pool.acquire() as conn:
        public_cz = await conn.fetchval(
            "SELECT canonical_zettel_id FROM content.workspace_zettels WHERE id = $1", public_id
        )
        private_cz = await conn.fetchval(
            "SELECT canonical_zettel_id FROM content.workspace_zettels WHERE id = $1", private_id
        )
        await conn.execute(
            "UPDATE content.workspace_zettels SET is_private = true, made_private_at = now() WHERE id = $1",
            private_id,
        )

    repo = CommunityGraphRepository()
    graph = repo.get_community_graph(limit=5000, min_strength=0.0)
    node_cz = {str(n["canonical_zettel_id"]) for n in graph["nodes"]}
    assert str(public_cz) in node_cz
    assert str(private_cz) not in node_cz
    # No user identifiers anywhere in nodes.
    for n in graph["nodes"]:
        assert "user_id" not in n and "owner_profile_id" not in n


@pytest.mark.asyncio
async def test_set_private_round_trips_and_audits(asyncpg_pool, mint_user, bulk_insert_zettels):
    user = mint_user(workspace_count=1)
    wz_id = (await bulk_insert_zettels(owner_user=user, n=1, prefix="setpriv"))[0]
    repo = CommunityGraphRepository()
    repo.set_private(workspace_zettel_id=wz_id, private=True, actor_user_id=user.profile_id)
    async with asyncpg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT is_private, made_private_at FROM content.workspace_zettels WHERE id = $1", wz_id
        )
        events = await conn.fetch(
            "SELECT action FROM content.zettel_privacy_events WHERE workspace_zettel_id = $1 ORDER BY created_at",
            wz_id,
        )
    assert row["is_private"] is True
    assert row["made_private_at"] is not None
    assert [e["action"] for e in events][-1] == "make_private"

    repo.set_private(workspace_zettel_id=wz_id, private=False, actor_user_id=user.profile_id)
    async with asyncpg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT is_private FROM content.workspace_zettels WHERE id = $1", wz_id
        )
        events = await conn.fetch(
            "SELECT action FROM content.zettel_privacy_events WHERE workspace_zettel_id = $1 ORDER BY created_at",
            wz_id,
        )
    assert row["is_private"] is False
    assert [e["action"] for e in events][-1] == "make_public"


@pytest.mark.xfail(reason="community_cache_version table lands in Task 0.7")
@pytest.mark.asyncio
async def test_read_cache_version_returns_int(asyncpg_pool):
    repo = CommunityGraphRepository()
    v = repo.read_cache_version()
    assert isinstance(v, int) and v >= 0
