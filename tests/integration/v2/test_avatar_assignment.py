"""Tests for the default-avatar trigger and backfill (migration 76)."""
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
            "SELECT raw_user_meta_data->>'avatar_url' AS url FROM auth.users WHERE id = $1",
            user.auth_user_id,
        )
    assert row is not None
    assert AVATAR_PATTERN.match(row["url"] or ""), f"Bad avatar_url: {row['url']!r}"


async def test_zoro_pinned_to_avatar_00(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        url = await conn.fetchval(
            "SELECT raw_user_meta_data->>'avatar_url' FROM auth.users WHERE id = $1",
            ZORO_USER_ID,
        )
    assert url == "/artifacts/avatars/avatar_00.svg"


async def test_naruto_pinned_to_avatar_01(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        url = await conn.fetchval(
            "SELECT raw_user_meta_data->>'avatar_url' FROM auth.users WHERE id = $1",
            NARUTO_USER_ID,
        )
    assert url == "/artifacts/avatars/avatar_01.svg"


async def test_no_google_or_gravatar_remains(asyncpg_pool):
    """After backfill, no user should retain a third-party-hosted avatar URL."""
    async with asyncpg_pool.acquire() as conn:
        count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM auth.users
            WHERE raw_user_meta_data->>'avatar_url' LIKE '%googleusercontent.com%'
               OR raw_user_meta_data->>'avatar_url' LIKE '%gravatar.com%'
            """
        )
    assert count == 0
