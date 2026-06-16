"""run_view_graph view='global' is built from the community wrapper (no file-store).

@pytest.mark.live. Asserts the published-by-default node appears, meta.source is
'community' (never 'file-store'), and no user_id leaks into global nodes.
"""
from __future__ import annotations

import pytest

from website.api.module_runners.view_graph import run_view_graph
from website.core.supabase_v2.repositories.community_repository import (
    CommunityGraphRepository,
)

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_global_includes_public_node(asyncpg_pool, mint_user, bulk_insert_zettels):
    user = mint_user(workspace_count=1)
    wz_id = (await bulk_insert_zettels(owner_user=user, n=1, prefix="vgglobal"))[0]
    async with asyncpg_pool.acquire() as conn:
        cz = str(await conn.fetchval(
            "SELECT canonical_zettel_id FROM content.workspace_zettels WHERE id = $1", wz_id
        ))
    # Default is public; bump cache so any prior cached payload is invalidated.
    CommunityGraphRepository().bump_cache_version()

    payload = await run_view_graph(user=None, view="global", limit=5000, offset=0, min_strength=0.0)
    node_cz = {str(n.get("canonical_zettel_id")) for n in payload.get("nodes", [])}
    assert cz in node_cz, "default public node missing from view=global"
    assert payload["meta"]["view"] == "global"
    assert payload["meta"]["source"] == "community", "global must be the real community, not file-store"
    for n in payload.get("nodes", []):
        assert "user_id" not in n


@pytest.mark.asyncio
async def test_global_source_is_always_community(asyncpg_pool, mint_user, bulk_insert_zettels):
    """Even if a private-only state existed, source must be 'community' (file-store retired)."""
    payload = await run_view_graph(user=None, view="global", limit=5000, offset=0, min_strength=0.0)
    assert payload["meta"]["source"] == "community"
    for n in payload.get("nodes", []):
        assert "user_id" not in n and "owner_profile_id" not in n
