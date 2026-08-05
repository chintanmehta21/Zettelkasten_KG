"""Migration 88: content.community_graph_v1 forced-predicate RPC.

@pytest.mark.live. Calls the RPC via the service_role client (the app's real
connection — BYPASSRLS) and asserts: only PUBLIC rows (is_private=false), no
user_id, dedup by canonical, attribution display_name.
"""
from __future__ import annotations

import pytest

from website.core.supabase_v2.client import get_v2_client

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_rpc_is_owned_by_community_reader(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        owner = await conn.fetchval(
            """
            SELECT r.rolname
              FROM pg_proc p
              JOIN pg_namespace n ON n.oid = p.pronamespace
              JOIN pg_roles r ON r.oid = p.proowner
             WHERE n.nspname = 'content' AND p.proname = 'community_graph_v1'
             LIMIT 1
            """
        )
    assert owner == "community_reader", f"RPC must be owned by community_reader, got {owner!r}"


@pytest.mark.asyncio
async def test_execute_granted_to_service_role(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        granted = await conn.fetchval(
            """
            SELECT has_function_privilege(
                'service_role',
                'content.community_graph_v1(int, float)',
                'EXECUTE'
            )
            """
        )
    assert granted is True, "service_role must have EXECUTE on community_graph_v1"


@pytest.mark.asyncio
async def test_rpc_returns_public_only_no_user_id(asyncpg_pool, mint_user, bulk_insert_zettels):
    user = mint_user(workspace_count=1)
    wz_ids = await bulk_insert_zettels(owner_user=user, n=2, prefix="rpcpub")
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

    client = get_v2_client()
    resp = client.schema("content").rpc(
        "community_graph_v1", {"p_limit": 5000, "p_min_strength": 0.0}
    ).execute()
    rows = resp.data or []
    cz_ids = {str(r.get("canonical_zettel_id")) for r in rows}
    assert str(public_cz) in cz_ids, "public canonical missing from community graph"
    assert str(private_cz) not in cz_ids, "PRIVATE canonical leaked into community graph"
    for r in rows:
        assert "user_id" not in r, f"user_id leaked in payload: {r}"
        assert "owner_profile_id" not in r
        assert "made_private_at" not in r


@pytest.mark.asyncio
async def test_rpc_attribution_present(asyncpg_pool, mint_user, bulk_insert_zettels):
    """Public rows carry author_display_name (attribution model)."""
    user = mint_user(workspace_count=1)
    wz_ids = await bulk_insert_zettels(owner_user=user, n=1, prefix="rpcattr")
    wz_id = wz_ids[0]
    async with asyncpg_pool.acquire() as conn:
        public_cz = await conn.fetchval(
            "SELECT canonical_zettel_id FROM content.workspace_zettels WHERE id = $1", wz_id
        )

    client = get_v2_client()
    resp = client.schema("content").rpc(
        "community_graph_v1", {"p_limit": 5000, "p_min_strength": 0.0}
    ).execute()
    rows = resp.data or []
    match = next((r for r in rows if str(r.get("canonical_zettel_id")) == str(public_cz)), None)
    assert match is not None, "public zettel not returned by RPC"
    # author_display_name must be present (may be None if profile has no display_name set,
    # but the key itself must exist in the row shape).
    assert "author_display_name" in match, f"attribution key missing from row: {match}"


@pytest.mark.asyncio
async def test_rpc_dedups_canonical_across_two_savers(asyncpg_pool, mint_user):
    """Two users saving the SAME canonical (both public) → exactly one community node."""
    user_a = mint_user(workspace_count=1)
    user_b = mint_user(workspace_count=1)
    async with asyncpg_pool.acquire() as conn:
        cz_id = await conn.fetchval(
            """
            INSERT INTO content.canonical_zettels (id, normalized_url, content_hash, source_type, title)
            VALUES (gen_random_uuid(), 'https://dedup-' || gen_random_uuid()::text || '.example.com/',
                    decode(md5(random()::text), 'hex'), 'web', 'dedup shared')
            RETURNING id
            """
        )
        for u in (user_a, user_b):
            await conn.execute(
                """
                INSERT INTO content.workspace_zettels
                  (workspace_id, canonical_zettel_id, ai_summary, user_tags, added_via, is_private)
                VALUES ($1, $2, '', ARRAY['dedup']::text[], 'website', false)
                """,
                u.workspace_ids[0], cz_id,
            )
    client = get_v2_client()
    resp = client.schema("content").rpc(
        "community_graph_v1", {"p_limit": 5000, "p_min_strength": 0.0}
    ).execute()
    matches = [r for r in (resp.data or []) if str(r.get("canonical_zettel_id")) == str(cz_id)]
    assert len(matches) == 1, f"expected 1 deduped node, got {len(matches)}"
