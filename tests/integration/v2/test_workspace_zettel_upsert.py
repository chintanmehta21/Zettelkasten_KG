"""Integration tests for content.upsert_workspace_zettel (incident 2026-05-23).

Background — what failed and why this RPC exists
-------------------------------------------------
Migration 66_workspace_zettels_partial_indexes.sql replaced the table-level
`UNIQUE (workspace_id, canonical_zettel_id)` with a PARTIAL UNIQUE INDEX
`uq_workspace_zettel_active ... WHERE deleted_at IS NULL`. The visible Trash
+ Restore UX needs this so a soft-deleted row no longer occupies the unique
slot.

PostgREST's `?on_conflict=col1,col2` URL grammar cannot express the WHERE
predicate that PG partial-index inference requires (PostgREST issue #2123,
open since 2022). Every `.table('workspace_zettels').upsert(...)` therefore
returned `postgrest.exceptions.APIError 42P10 — there is no unique or
exclusion constraint matching the ON CONFLICT specification`, and the route
surfaced kg-write-failed 502 to the client. Root-caused live on master
882ca320 during Naruto e2e (operation zettel:1779551217529:kxhc5k66eu8).

The fix routes the write through this RPC, which uses native PG syntax
`INSERT ... ON CONFLICT (workspace_id, canonical_zettel_id) WHERE deleted_at
IS NULL DO UPDATE ...` and correctly matches the partial unique index.

Cases covered
-------------
1. Fresh insert returns a uuid; row is visible with deleted_at IS NULL.
2. Repeat insert with same (workspace_id, canonical_zettel_id) returns the
   SAME uuid (UPDATE branch) and refreshes the mutable columns.
3. After soft-delete + re-insert: a NEW row lands (intentional per migration
   66 — the partial index does not see the tombstone), the tombstone is
   untouched, and both rows coexist in the table (one live, one trashed).
4. Concurrent inserters race the partial unique index — exactly ONE wins
   the insert; the others get the same uuid via DO UPDATE.

All tests marked @pytest.mark.live — they hit the live v2 Supabase project.
"""
from __future__ import annotations

import asyncio
import uuid

import asyncpg
import pytest


pytestmark = pytest.mark.live


_UPSERT_RPC_SQL = (
    "SELECT content.upsert_workspace_zettel("
    "$1::uuid, $2::uuid, $3::text, $4::text, $5::text[], $6::text, $7::boolean, $8::text"
    ") AS id"
)

_CANONICAL_RPC_SQL = (
    "SELECT id, was_new FROM content.upsert_canonical_zettel"
    "($1::text, $2::bytea, $3::text, $4::text, $5::text, $6::date, $7::jsonb)"
)


# A hand-rolled core.profiles insert is NOT viable: profiles_id_fkey references
# auth.users(id), so a synthetic profile_id always violates the FK. Auth users
# must be minted through the GoTrue admin API (mint_user) — that fires the
# profile -> personal-workspace trigger chain and uses the e2e-*@test.com naming
# the session-finish sweeper relies on. Raw SQL users would leak forever.


async def _make_canonical(pool: asyncpg.Pool) -> uuid.UUID:
    """Insert a throwaway canonical_zettel and return its id."""
    url = f"https://wz-upsert-test-{uuid.uuid4().hex[:12]}.example.com/"
    h = uuid.uuid4().bytes + uuid.uuid4().bytes
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            _CANONICAL_RPC_SQL,
            url, h, "web", "wz-upsert-canonical", "body",
            None, "{}",
        )
        return row["id"]


async def _cleanup_workspace(pool: asyncpg.Pool, workspace_id: uuid.UUID) -> None:
    """Drop only the rows this test wrote.

    The workspace/profile/auth-user themselves belong to ``mint_user`` and are
    torn down by its fixture — deleting them here would double-free and race
    that teardown.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM content.workspace_zettels WHERE workspace_id = $1",
            workspace_id,
        )


@pytest.mark.asyncio
async def test_fresh_insert_returns_uuid_and_row_lands_live(asyncpg_pool: asyncpg.Pool, mint_user):
    workspace_id = mint_user(workspace_count=1).workspace_ids[0]
    canonical_id = await _make_canonical(asyncpg_pool)
    try:
        async with asyncpg_pool.acquire() as conn:
            row = await conn.fetchrow(
                _UPSERT_RPC_SQL,
                workspace_id, canonical_id, "ai summary 1", "engine-v1",
                ["tag-a", "tag-b"], "user note 1", False, "website",
            )
        assert row is not None
        wz_id = row["id"]
        assert isinstance(wz_id, uuid.UUID)
        async with asyncpg_pool.acquire() as conn:
            db_row = await conn.fetchrow(
                "SELECT id, deleted_at, ai_summary, user_tags "
                "FROM content.workspace_zettels WHERE id = $1",
                wz_id,
            )
        assert db_row["deleted_at"] is None
        assert db_row["ai_summary"] == "ai summary 1"
        assert list(db_row["user_tags"]) == ["tag-a", "tag-b"]
    finally:
        await _cleanup_workspace(asyncpg_pool, workspace_id)


@pytest.mark.asyncio
async def test_repeat_with_same_pair_updates_in_place(asyncpg_pool: asyncpg.Pool, mint_user):
    workspace_id = mint_user(workspace_count=1).workspace_ids[0]
    canonical_id = await _make_canonical(asyncpg_pool)
    try:
        async with asyncpg_pool.acquire() as conn:
            row_a = await conn.fetchrow(
                _UPSERT_RPC_SQL,
                workspace_id, canonical_id, "first", "engine-v1",
                ["t1"], None, False, "website",
            )
            row_b = await conn.fetchrow(
                _UPSERT_RPC_SQL,
                workspace_id, canonical_id, "second", "engine-v2",
                ["t2", "t3"], "noted", True, "share",
            )
        # SAME uuid — UPDATE branch, not a new INSERT.
        assert row_a["id"] == row_b["id"]
        async with asyncpg_pool.acquire() as conn:
            db_row = await conn.fetchrow(
                "SELECT ai_summary, ai_summary_engine_version, user_tags, "
                "user_note, pinned, added_via, deleted_at "
                "FROM content.workspace_zettels WHERE id = $1",
                row_b["id"],
            )
            cnt = await conn.fetchval(
                "SELECT COUNT(*) FROM content.workspace_zettels "
                "WHERE workspace_id = $1 AND canonical_zettel_id = $2",
                workspace_id, canonical_id,
            )
        # Mutable columns refreshed to the second-call values.
        assert db_row["ai_summary"] == "second"
        assert db_row["ai_summary_engine_version"] == "engine-v2"
        assert list(db_row["user_tags"]) == ["t2", "t3"]
        assert db_row["user_note"] == "noted"
        assert db_row["pinned"] is True
        assert db_row["added_via"] == "share"
        assert db_row["deleted_at"] is None
        # No duplicate row.
        assert cnt == 1
    finally:
        await _cleanup_workspace(asyncpg_pool, workspace_id)


@pytest.mark.asyncio
async def test_re_add_after_soft_delete_creates_new_row(asyncpg_pool: asyncpg.Pool, mint_user):
    """Migration 66 semantics: a re-add after soft-delete must land a NEW
    workspace_zettel row, NOT silently restore the tombstoned one. The
    partial index does not see the tombstone, so ON CONFLICT does not
    fire and INSERT proceeds; both rows coexist with the same
    (workspace_id, canonical_zettel_id) — one live, one trashed."""
    workspace_id = mint_user(workspace_count=1).workspace_ids[0]
    canonical_id = await _make_canonical(asyncpg_pool)
    try:
        async with asyncpg_pool.acquire() as conn:
            row_a = await conn.fetchrow(
                _UPSERT_RPC_SQL,
                workspace_id, canonical_id, "first", "engine-v1",
                ["t1"], None, False, "website",
            )
            # Soft-delete the live row (mark tombstone).
            await conn.execute(
                "UPDATE content.workspace_zettels SET deleted_at = now() "
                "WHERE id = $1",
                row_a["id"],
            )
            row_b = await conn.fetchrow(
                _UPSERT_RPC_SQL,
                workspace_id, canonical_id, "second", "engine-v2",
                ["t2"], None, False, "website",
            )
        assert row_a["id"] != row_b["id"], (
            "After soft-delete, a re-add must land as a NEW row (per "
            "migration 66 partial-unique semantics). Same uuid means the "
            "RPC accidentally restored the tombstone."
        )
        async with asyncpg_pool.acquire() as conn:
            tombstone = await conn.fetchrow(
                "SELECT deleted_at, ai_summary FROM content.workspace_zettels WHERE id = $1",
                row_a["id"],
            )
            live = await conn.fetchrow(
                "SELECT deleted_at, ai_summary FROM content.workspace_zettels WHERE id = $1",
                row_b["id"],
            )
        # Tombstone untouched.
        assert tombstone["deleted_at"] is not None
        assert tombstone["ai_summary"] == "first"
        # Live row is fresh and writable.
        assert live["deleted_at"] is None
        assert live["ai_summary"] == "second"
    finally:
        await _cleanup_workspace(asyncpg_pool, workspace_id)


@pytest.mark.asyncio
async def test_concurrent_inserters_exactly_one_wins_others_update(
    asyncpg_pool: asyncpg.Pool, mint_user,
):
    """Ten concurrent inserts on the same (workspace_id, canonical_zettel_id).
    PG INSERT ON CONFLICT is atomic — exactly one row exists at the end,
    and every caller returns that one uuid."""
    workspace_id = mint_user(workspace_count=1).workspace_ids[0]
    canonical_id = await _make_canonical(asyncpg_pool)
    try:
        async def _one() -> uuid.UUID:
            async with asyncpg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    _UPSERT_RPC_SQL,
                    workspace_id, canonical_id, "race", "engine-race",
                    ["race"], None, False, "website",
                )
                return row["id"]

        ids = await asyncio.gather(*[_one() for _ in range(10)])
        # All callers see the SAME row id.
        assert len(set(ids)) == 1, f"expected single uuid, saw {set(ids)}"
        async with asyncpg_pool.acquire() as conn:
            cnt = await conn.fetchval(
                "SELECT COUNT(*) FROM content.workspace_zettels "
                "WHERE workspace_id = $1 AND canonical_zettel_id = $2 "
                "AND deleted_at IS NULL",
                workspace_id, canonical_id,
            )
        # Partial unique index held — exactly one live row.
        assert cnt == 1
    finally:
        await _cleanup_workspace(asyncpg_pool, workspace_id)
