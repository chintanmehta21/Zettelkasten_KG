"""content.community_graph_edges_v1 (migration 90) — the cross-user tag backbone.

The whole point of this RPC is that per-workspace kg.kg_edges can NEVER connect
one user's zettel to another's; these tests assert an edge really does form
ACROSS two distinct users, and that the privacy predicate holds for edges the
same way it holds for nodes.

@pytest.mark.live.
"""
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.live


def _node_id(canonical_id) -> str:
    return "web-" + str(canonical_id)[:12]


async def _set_tags(conn, wz_id, tags: list[str]) -> None:
    await conn.execute(
        "UPDATE content.workspace_zettels SET user_tags = $2::text[] WHERE id = $1",
        wz_id,
        tags,
    )


async def _canonical_of(conn, wz_id):
    return await conn.fetchval(
        "SELECT canonical_zettel_id FROM content.workspace_zettels WHERE id = $1", wz_id
    )


@pytest.mark.asyncio
async def test_edge_forms_across_two_different_users(
    asyncpg_pool, mint_user, bulk_insert_zettels
):
    """Two DIFFERENT users sharing rare tags must be connected."""
    seed = uuid.uuid4().hex[:8]
    shared = [f"zz-{seed}-alpha", f"zz-{seed}-beta"]

    user_a = mint_user(workspace_count=1)
    user_b = mint_user(workspace_count=1)
    wz_a = (await bulk_insert_zettels(owner_user=user_a, n=1, prefix=f"ea{seed}"))[0]
    wz_b = (await bulk_insert_zettels(owner_user=user_b, n=1, prefix=f"eb{seed}"))[0]

    async with asyncpg_pool.acquire() as conn:
        await _set_tags(conn, wz_a, shared)
        await _set_tags(conn, wz_b, shared)
        cz_a = await _canonical_of(conn, wz_a)
        cz_b = await _canonical_of(conn, wz_b)
        rows = await conn.fetch(
            "SELECT source_node_id, target_node_id, strength, shared_tags "
            "FROM content.community_graph_edges_v1()"
        )

    a, b = _node_id(cz_a), _node_id(cz_b)
    pairs = {(r["source_node_id"], r["target_node_id"]): r for r in rows}
    edge = pairs.get((a, b)) or pairs.get((b, a))
    assert edge is not None, "cross-user tag backbone produced no edge"
    assert edge["shared_tags"] == 2
    assert 0.0 < edge["strength"] <= 1.0001


@pytest.mark.asyncio
async def test_private_zettel_never_appears_in_any_edge(
    asyncpg_pool, mint_user, bulk_insert_zettels
):
    """Privacy regression gate for EDGES (the node gate lives in the 88 tests).

    A private zettel sharing the exact tags of two public ones must not appear
    as an edge endpoint — its rows are invisible to community_reader, so it
    cannot enter the tag vocabulary, the IDF statistics, or any pair.
    """
    seed = uuid.uuid4().hex[:8]
    shared = [f"zp-{seed}-alpha", f"zp-{seed}-beta"]

    user = mint_user(workspace_count=1)
    wz_ids = await bulk_insert_zettels(owner_user=user, n=3, prefix=f"ep{seed}")
    wz_pub1, wz_pub2, wz_priv = wz_ids

    async with asyncpg_pool.acquire() as conn:
        for wz in (wz_pub1, wz_pub2, wz_priv):
            await _set_tags(conn, wz, shared)
        await conn.execute(
            "UPDATE content.workspace_zettels SET is_private = true, "
            "made_private_at = now() WHERE id = $1",
            wz_priv,
        )
        cz_priv = await _canonical_of(conn, wz_priv)
        rows = await conn.fetch(
            "SELECT source_node_id, target_node_id FROM content.community_graph_edges_v1()"
        )

    private_node = _node_id(cz_priv)
    endpoints = {r["source_node_id"] for r in rows} | {r["target_node_id"] for r in rows}
    assert private_node not in endpoints, (
        "PRIVACY BREACH: a private zettel became an edge endpoint in the "
        "community graph"
    )


@pytest.mark.asyncio
async def test_min_shared_and_strength_floor_are_enforced(asyncpg_pool):
    """Every returned edge must satisfy the RPC's own contract."""
    async with asyncpg_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT strength, shared_tags FROM content.community_graph_edges_v1("
            "p_limit => 4000, p_top_k => 10, p_min_shared => 2, p_min_strength => 0.20)"
        )
    for r in rows:
        assert r["shared_tags"] >= 2
        assert r["strength"] >= 0.20


@pytest.mark.asyncio
async def test_top_k_bounds_node_degree(asyncpg_pool):
    """Hub control: union symmetrisation caps degree at ~2*top_k."""
    top_k = 3
    async with asyncpg_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT source_node_id, target_node_id FROM content.community_graph_edges_v1("
            f"p_limit => 4000, p_top_k => {top_k}, p_min_shared => 1, p_min_strength => 0.05)"
        )
    degree: dict[str, int] = {}
    for r in rows:
        for endpoint in (r["source_node_id"], r["target_node_id"]):
            degree[endpoint] = degree.get(endpoint, 0) + 1
    if degree:
        assert max(degree.values()) <= 2 * top_k


@pytest.mark.asyncio
async def test_edges_only_reference_nodes_the_node_rpc_returns(asyncpg_pool):
    """Edge invariant: no orphan endpoints (the viz throws on unknown ids)."""
    async with asyncpg_pool.acquire() as conn:
        orphans = await conn.fetchval(
            "SELECT COUNT(*) FROM content.community_graph_edges_v1() e "
            "WHERE e.source_node_id NOT IN (SELECT node_id FROM content.community_graph_v1()) "
            "   OR e.target_node_id NOT IN (SELECT node_id FROM content.community_graph_v1())"
        )
    assert orphans == 0
