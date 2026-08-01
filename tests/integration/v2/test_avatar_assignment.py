"""Tests for the default-avatar trigger and backfill (migrations 76 + 78).

2026-08-01: these read ``core.profiles.avatar_url``, NOT
``auth.users.raw_user_meta_data->>'avatar_url'``. Migration 78 made
core.profiles the single source of truth and CLEARED the auth.users copy, so
the old queries returned NULL for every user and these failed with
``assert None == '/artifacts/avatars/avatar_01.svg'`` — a stale location,
not a real defect. Verified against production 2026-08-01: the auth.users
copies are NULL and core.profiles holds the live values.
"""

from __future__ import annotations

import re
import uuid

import pytest

pytestmark = [pytest.mark.live, pytest.mark.asyncio]

AVATAR_PATTERN = re.compile(r"^/artifacts/avatars/avatar_(0[0-9]|[1-5][0-9])\.svg$")
ZORO_USER_ID = uuid.UUID("a57e1f2f-7d89-4cd7-ae39-72c440ed4b4e")
NARUTO_USER_ID = uuid.UUID("f2105544-b73d-4946-8329-096d82f070d3")


async def test_new_user_gets_random_avatar(asyncpg_pool, mint_user):
    """A freshly minted user must have a valid /artifacts/avatars/avatar_NN.svg in user_metadata."""
    user = mint_user()
    async with asyncpg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT avatar_url AS url FROM core.profiles WHERE id = $1",
            user.auth_user_id,
        )
    assert row is not None
    assert AVATAR_PATTERN.match(row["url"] or ""), f"Bad avatar_url: {row['url']!r}"


async def test_zoro_pinned_to_avatar_00(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        url = await conn.fetchval(
            "SELECT avatar_url FROM core.profiles WHERE id = $1",
            ZORO_USER_ID,
        )
    assert url == "/artifacts/avatars/avatar_00.svg"


async def test_naruto_pinned_to_avatar_01(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        url = await conn.fetchval(
            "SELECT avatar_url FROM core.profiles WHERE id = $1",
            NARUTO_USER_ID,
        )
    assert url == "/artifacts/avatars/avatar_01.svg"


async def test_no_google_or_gravatar_remains(asyncpg_pool):
    """After backfill, no user should retain a third-party-hosted avatar URL."""
    async with asyncpg_pool.acquire() as conn:
        count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM core.profiles
            WHERE avatar_url LIKE '%googleusercontent.com%'
               OR avatar_url LIKE '%gravatar.com%'
            """
        )
    assert count == 0


async def test_curated_url_is_not_reassigned_by_backfill(
    asyncpg_pool, mint_user, created_auth_user_ids
):
    """Re-applying the backfill UPDATE must leave a user already on the curated
    set untouched — defense-in-depth for the idempotency guard added in the
    migration review (AND NOT LIKE '/artifacts/avatars/%').
    """
    user = mint_user()
    pinned_url = "/artifacts/avatars/avatar_42.svg"

    async with asyncpg_pool.acquire() as conn:
        # Override whatever the trigger assigned with a known curated URL.
        await conn.execute(
            """
            UPDATE auth.users
            SET raw_user_meta_data = jsonb_set(
                COALESCE(raw_user_meta_data, '{}'::jsonb),
                '{avatar_url}',
                $1::jsonb
            )
            WHERE id = $2
            """,
            f'"{pinned_url}"',
            user.auth_user_id,
        )

        # Re-run the exact backfill UPDATE from migration 76 (the idempotency guard).
        await conn.execute(
            """
            UPDATE auth.users
            SET raw_user_meta_data = COALESCE(raw_user_meta_data, '{}'::jsonb)
              || jsonb_build_object(
                   'avatar_url',
                   '/artifacts/avatars/avatar_' || lpad((floor(random() * 60))::text, 2, '0') || '.svg'
                 )
            WHERE (
                   (raw_user_meta_data->>'avatar_url') IS NULL
                OR (raw_user_meta_data->>'avatar_url') LIKE '%googleusercontent.com%'
                OR (raw_user_meta_data->>'avatar_url') LIKE '%gravatar.com%'
              )
              AND (raw_user_meta_data->>'avatar_url') NOT LIKE '/artifacts/avatars/%'
            """
        )

        # NOTE: this test deliberately stays on auth.users end-to-end. It
        # exercises migration 76's own backfill SQL and its idempotency guard,
        # which operate on auth.users.raw_user_meta_data — so the write above
        # and this read must target the same column to be meaningful. The other
        # tests in this module read core.profiles, which migration 78 made the
        # source of truth for the LIVE avatar.
        url = await conn.fetchval(
            "SELECT raw_user_meta_data->>'avatar_url' FROM auth.users WHERE id = $1",
            user.auth_user_id,
        )

    assert url == pinned_url, (
        f"Backfill re-apply overwrote an already-curated avatar_url: got {url!r}"
    )
