"""LOAD-BEARING PRIVACY PROOF — community read never leaks PRIVATE rows.

The app connects to Supabase via service_role (BYPASSRLS). This gate proves the
community read path (CommunityGraphRepository → community_graph_v1) still NEVER
returns an is_private=true row, that a default (public) zettel DOES appear, that
flipping private->public toggles presence, that no user_id is present, and that
no edge connects to a private node.

DO NOT DELETE OR SKIP THIS TEST. A failure here is a privacy breach, not a flake.
@pytest.mark.live.
"""
from __future__ import annotations

import pytest

from website.core.supabase_v2.repositories.community_repository import (
    CommunityGraphRepository,
)

pytestmark = pytest.mark.live


async def _cz_for(conn, wz_id):
    return await conn.fetchval(
        "SELECT canonical_zettel_id FROM content.workspace_zettels WHERE id = $1", wz_id
    )


@pytest.mark.asyncio
async def test_private_never_in_community_under_service_role(
    asyncpg_pool, mint_user, bulk_insert_zettels
):
    """Assertion (1): is_private=true zettel NEVER appears even via service_role/BYPASSRLS.
    Assertion (2): a default (unmarked, is_private=false) zettel DOES appear.
    """
    user = mint_user(workspace_count=1)
    wz_ids = await bulk_insert_zettels(owner_user=user, n=5, prefix="gate")
    # Mark 4 private; leave 1 public (default is_private=false via migration 85).
    async with asyncpg_pool.acquire() as conn:
        await conn.executemany(
            "UPDATE content.workspace_zettels SET is_private = true, made_private_at = now() WHERE id = $1",
            [(wz,) for wz in wz_ids[1:]],
        )
        private_cz = {str(await _cz_for(conn, wz)) for wz in wz_ids[1:]}
        public_cz = str(await _cz_for(conn, wz_ids[0]))

    # Call through the app's real path: service_role client → forced-predicate RPC.
    repo = CommunityGraphRepository()
    graph = repo.get_community_graph(limit=5000, min_strength=0.0)
    returned_cz = {str(n["canonical_zettel_id"]) for n in graph["nodes"]}

    leaked = returned_cz & private_cz
    assert not leaked, f"PRIVACY BREACH: private canonicals returned under service_role: {leaked}"
    assert public_cz in returned_cz, (
        "default (public) zettel must appear in community graph"
    )


@pytest.mark.asyncio
async def test_make_private_then_public_toggles_node_presence(
    asyncpg_pool, mint_user, bulk_insert_zettels
):
    """Assertion (3): toggling private→public flips node presence in the community graph."""
    user = mint_user(workspace_count=1)
    wz_id = (await bulk_insert_zettels(owner_user=user, n=1, prefix="toggle"))[0]
    async with asyncpg_pool.acquire() as conn:
        cz = str(await _cz_for(conn, wz_id))

    repo = CommunityGraphRepository()

    # Default = public (is_private=false via migration 85 DEFAULT false) → present.
    assert cz in {str(n["canonical_zettel_id"]) for n in repo.get_community_graph()["nodes"]}, (
        "default public zettel missing from community graph"
    )

    # Mark private → must vanish.
    repo.set_private(workspace_zettel_id=wz_id, private=True, actor_user_id=user.profile_id)
    assert cz not in {str(n["canonical_zettel_id"]) for n in repo.get_community_graph()["nodes"]}, (
        "marking private did not remove the node from community graph"
    )

    # Mark public again → must reappear.
    repo.set_private(workspace_zettel_id=wz_id, private=False, actor_user_id=user.profile_id)
    assert cz in {str(n["canonical_zettel_id"]) for n in repo.get_community_graph()["nodes"]}, (
        "marking public did not restore the node in community graph"
    )


@pytest.mark.asyncio
async def test_no_user_id_and_edges_only_between_public(
    asyncpg_pool, mint_user, bulk_insert_zettels
):
    """Assertion (4): no user_id/owner_profile_id field in any returned node.
    Assertion (5): no edge connects to a private node (invariant asserted now;
                   Phase 1 ships zero edges so the link list is empty, but the
                   check is future-proof for Phase 3 edge computation).
    """
    user = mint_user(workspace_count=1)
    wz_ids = await bulk_insert_zettels(owner_user=user, n=2, prefix="edge")
    # Mark one private so we have both kinds in the DB.
    async with asyncpg_pool.acquire() as conn:
        await conn.execute(
            "UPDATE content.workspace_zettels SET is_private = true, made_private_at = now() WHERE id = $1",
            wz_ids[1],
        )

    repo = CommunityGraphRepository()
    graph = repo.get_community_graph()

    # (4) No user identifier in ANY node payload.
    for n in graph["nodes"]:
        assert "user_id" not in n, (
            f"user_id leaked in community node payload: {n}"
        )
        assert "owner_profile_id" not in n, (
            f"owner_profile_id leaked in community node payload: {n}"
        )
        assert "made_private_at" not in n, (
            f"made_private_at leaked in community node payload: {n}"
        )

    # (5) Every edge endpoint must reference a node that is in the public set.
    # Phase 1 ships zero edges; this guard fires if/when Phase 3 adds them.
    node_ids = {n["id"] for n in graph["nodes"]}
    for link in graph["links"]:
        src = link["source"] if isinstance(link["source"], str) else link["source"]["id"]
        dst = link["target"] if isinstance(link["target"], str) else link["target"]["id"]
        assert src in node_ids, (
            f"edge source {src!r} is not in the public node set — "
            f"edge may connect to a private node"
        )
        assert dst in node_ids, (
            f"edge target {dst!r} is not in the public node set — "
            f"edge may connect to a private node"
        )
