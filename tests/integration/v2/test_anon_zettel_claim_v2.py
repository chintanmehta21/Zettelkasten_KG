"""Live integration tests for the anon → user zettel claim (Item 6).

Marked ``@pytest.mark.live`` — they hit the real v2 Supabase project via the
service-role asyncpg pool and the ``ContentRepository`` RPC wrappers. NOT run
in the default unit suite; run with ``pytest --live tests/integration/v2/
test_anon_zettel_claim_v2.py`` against a test DB.

The DB migration under test: ``supabase/website/_v2/84_anon_zettel_claim.sql``
(``content.tag_anon_zettel`` / ``peek_claimable_anon_zettels`` /
``commit_anon_claim`` + the ``anon_sid`` column + ``content.anon_sessions``).

Construction: a stand-in "anon source" workspace (any workspace acts as Zoro
for the RPCs — they key off ``anon_sid``, not the literal Zoro id) holds
canonical+workspace rows tagged with an anon sid via ``tag_anon_zettel``. A
freshly-minted claiming user then claims them via peek + commit.

Coverage:
  * happy path — N tagged rows claimed into the new user's workspace as
    dual-ownership ('claim'-provenance) rows; the source rows are untouched.
  * first-claim-wins — two commits for the same session; the second returns 0.
  * 24h window — a session older than 24h yields no candidates and commits 0.
  * BOLA — a sid belonging to session A is not claimable when a different sid
    (session B) is presented.
  * quota cap end-to-end — only the affordable subset is inserted; the rest
    stay claimable on a later call once quota replenishes (not asserted here —
    we assert the partial-commit shape).
"""
from __future__ import annotations

import uuid

import asyncpg
import pytest

from website.core.supabase_v2.repositories.content_repository import ContentRepository

pytestmark = pytest.mark.live


# ---------------------------------------------------------------------------
# Seed helpers (service-role asyncpg bypasses RLS for fixture setup)
# ---------------------------------------------------------------------------


async def _seed_tagged_anon_zettel(
    pool: asyncpg.Pool,
    *,
    source_workspace_id: uuid.UUID,
    anon_sid: uuid.UUID,
    age_hours: int | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a canonical + source workspace_zettel, then tag it with anon_sid.

    Returns (canonical_zettel_id, workspace_zettel_id). Uses tag_anon_zettel so
    the session ledger row is created exactly as the capture path would create
    it. ``age_hours`` optionally back-dates the anon_sessions row by that many
    hours (server-side) to exercise the 24h window.
    """
    cz = uuid.uuid4()
    wz = uuid.uuid4()
    norm_url = f"https://anon-claim-{uuid.uuid4().hex[:10]}.example.com/"
    chash = uuid.uuid4().bytes + uuid.uuid4().bytes
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO content.canonical_zettels
                (id, normalized_url, content_hash, source_type, title, body_md)
            VALUES ($1, $2, $3, 'web', 'anon claim seed', 'body')
            """,
            cz, norm_url, chash,
        )
        await conn.execute(
            """
            INSERT INTO content.workspace_zettels
                (id, workspace_id, canonical_zettel_id, ai_summary, user_tags,
                 added_via)
            VALUES ($1, $2, $3, '{"brief_summary":"b","detailed_summary":"d"}',
                    ARRAY['seed']::text[], 'website')
            """,
            wz, source_workspace_id, cz,
        )

    # tag via the RPC under test (creates anon_sessions row + stamps anon_sid).
    ContentRepository().tag_anon_zettel(wz, anon_sid, ip_hash="iphash", ua_hash="uahash")

    if age_hours is not None:
        # asyncpg cannot bind a SQL-expression string as a timestamptz param;
        # pass an integer to make_interval and let Postgres compute the
        # back-dated timestamp against its own clock (matches the RPC's now()).
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE content.anon_sessions "
                "SET created_at = now() - make_interval(hours => $2) WHERE id = $1",
                anon_sid, age_hours,
            )
    return cz, wz


async def _new_user_owns_canonical(
    pool: asyncpg.Pool, *, workspace_id: uuid.UUID, canonical_id: uuid.UUID
) -> bool:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 1 FROM content.workspace_zettels
            WHERE workspace_id = $1 AND canonical_zettel_id = $2
              AND deleted_at IS NULL AND added_via = 'claim'
            """,
            workspace_id, canonical_id,
        )
    return row is not None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_happy_path_claims_tagged_rows(asyncpg_pool, mint_user):
    source = mint_user(workspace_count=1)
    claimer = mint_user(workspace_count=1)
    source_ws = source.workspace_ids[0]
    claimer_ws = claimer.workspace_ids[0]
    anon_sid = uuid.uuid4()

    cz1, _ = await _seed_tagged_anon_zettel(
        asyncpg_pool, source_workspace_id=source_ws, anon_sid=anon_sid
    )
    cz2, _ = await _seed_tagged_anon_zettel(
        asyncpg_pool, source_workspace_id=source_ws, anon_sid=anon_sid
    )

    repo = ContentRepository()
    candidates = repo.peek_claimable_anon_zettels(claimer.profile_id, anon_sid)
    assert len(candidates) == 2

    canonical_ids = [c["canonical_zettel_id"] for c in candidates]
    inserted = repo.commit_anon_claim(claimer.profile_id, anon_sid, canonical_ids)
    assert inserted == 2

    assert await _new_user_owns_canonical(
        asyncpg_pool, workspace_id=claimer_ws, canonical_id=cz1
    )
    assert await _new_user_owns_canonical(
        asyncpg_pool, workspace_id=claimer_ws, canonical_id=cz2
    )
    # Source rows untouched (Zoro keeps its rows).
    async with asyncpg_pool.acquire() as conn:
        src_count = await conn.fetchval(
            "SELECT count(*) FROM content.workspace_zettels "
            "WHERE workspace_id = $1 AND deleted_at IS NULL",
            source_ws,
        )
    assert src_count == 2


async def test_first_claim_wins(asyncpg_pool, mint_user):
    source = mint_user(workspace_count=1)
    claimer = mint_user(workspace_count=1)
    anon_sid = uuid.uuid4()
    cz1, _ = await _seed_tagged_anon_zettel(
        asyncpg_pool, source_workspace_id=source.workspace_ids[0], anon_sid=anon_sid
    )

    repo = ContentRepository()
    first = repo.commit_anon_claim(claimer.profile_id, anon_sid, [cz1])
    assert first == 1
    # Second commit for the same (now-claimed) session returns 0.
    second = repo.commit_anon_claim(claimer.profile_id, anon_sid, [cz1])
    assert second == 0
    # And peek now returns nothing (session marked claimed).
    assert repo.peek_claimable_anon_zettels(claimer.profile_id, anon_sid) == []


async def test_24h_window_excludes_stale_session(asyncpg_pool, mint_user):
    source = mint_user(workspace_count=1)
    claimer = mint_user(workspace_count=1)
    anon_sid = uuid.uuid4()
    cz1, _ = await _seed_tagged_anon_zettel(
        asyncpg_pool,
        source_workspace_id=source.workspace_ids[0],
        anon_sid=anon_sid,
        age_hours=25,
    )

    repo = ContentRepository()
    # Stale session → no candidates and commit is a no-op.
    assert repo.peek_claimable_anon_zettels(claimer.profile_id, anon_sid) == []
    assert repo.commit_anon_claim(claimer.profile_id, anon_sid, [cz1]) == 0


async def test_bola_other_session_sid_not_claimable(asyncpg_pool, mint_user):
    source = mint_user(workspace_count=1)
    claimer = mint_user(workspace_count=1)
    sid_a = uuid.uuid4()
    sid_b = uuid.uuid4()
    cz_a, _ = await _seed_tagged_anon_zettel(
        asyncpg_pool, source_workspace_id=source.workspace_ids[0], anon_sid=sid_a
    )

    repo = ContentRepository()
    # Presenting sid_b (a different/unknown session) yields nothing — sid_a's
    # rows are not exposed, and committing cz_a under sid_b inserts nothing.
    assert repo.peek_claimable_anon_zettels(claimer.profile_id, sid_b) == []
    assert repo.commit_anon_claim(claimer.profile_id, sid_b, [cz_a]) == 0


async def test_quota_cap_partial_commit(asyncpg_pool, mint_user):
    """End-to-end quota-cap shape at the DB layer: the endpoint passes ONLY the
    affordable canonical ids to commit; the DB inserts exactly those. Here we
    simulate "only 1 of 2 affordable" by committing a 1-element subset, then
    confirm the un-committed canonical is no longer claimable (session marked)."""
    source = mint_user(workspace_count=1)
    claimer = mint_user(workspace_count=1)
    anon_sid = uuid.uuid4()
    cz1, _ = await _seed_tagged_anon_zettel(
        asyncpg_pool, source_workspace_id=source.workspace_ids[0], anon_sid=anon_sid
    )
    cz2, _ = await _seed_tagged_anon_zettel(
        asyncpg_pool, source_workspace_id=source.workspace_ids[0], anon_sid=anon_sid
    )

    repo = ContentRepository()
    candidates = repo.peek_claimable_anon_zettels(claimer.profile_id, anon_sid)
    assert len(candidates) == 2

    # Affordable subset = first candidate only (mirrors the endpoint's quota
    # loop breaking on a 402 after the first reservation).
    inserted = repo.commit_anon_claim(
        claimer.profile_id, anon_sid, [candidates[0]["canonical_zettel_id"]]
    )
    assert inserted == 1

    # Session is now claimed (first-claim-wins) → the unaffordable cz2 is no
    # longer claimable even though it was never inserted. This is the accepted
    # trade-off: one claim attempt per browser session.
    assert repo.peek_claimable_anon_zettels(claimer.profile_id, anon_sid) == []
    assert await _new_user_owns_canonical(
        asyncpg_pool, workspace_id=claimer.workspace_ids[0], canonical_id=cz1
    )
    assert not await _new_user_owns_canonical(
        asyncpg_pool, workspace_id=claimer.workspace_ids[0], canonical_id=cz2
    )
