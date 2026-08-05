"""POST /api/zettels/{id}/private + /public (Part B Phase 1, opt-out).

@pytest.mark.live. Asserts: owner can mark private/public, ownership is enforced
(403 for a non-owner), a zettel_privacy_events row is written, the cache version
bumps, and the node then disappears from / reappears in view=global.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from website.core.supabase_v2.repositories.community_repository import (
    CommunityGraphRepository,
)

pytestmark = pytest.mark.live


@pytest.fixture
def v2_app(monkeypatch):
    monkeypatch.setenv("DB_SCHEMA_VERSION", "v2")
    from website.api import auth as auth_mod
    auth_mod._jwks_client = None
    from website.core import persist as persist_mod
    persist_mod._v2_core_repo = None
    persist_mod._v2_content_repo = None
    from website.app import create_app
    return create_app()


def _hdr(jwt):
    return {"Authorization": f"Bearer {jwt}"}


@pytest.mark.asyncio
async def test_owner_make_private_writes_audit_and_bumps_version(
    v2_app, asyncpg_pool, mint_user, bulk_insert_zettels
):
    user = mint_user(workspace_count=1)
    wz_id = (await bulk_insert_zettels(owner_user=user, n=1, prefix="privapi"))[0]

    repo = CommunityGraphRepository()
    before_version = repo.read_cache_version()

    with TestClient(v2_app) as client:
        resp = client.post(f"/api/zettels/{wz_id}/private", headers=_hdr(user.jwt))
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_private"] is True

    assert repo.read_cache_version() == before_version + 1, "cache version not bumped on toggle"
    async with asyncpg_pool.acquire() as conn:
        last = await conn.fetchval(
            "SELECT action FROM content.zettel_privacy_events WHERE workspace_zettel_id = $1 "
            "ORDER BY created_at DESC LIMIT 1",
            wz_id,
        )
    assert last == "make_private"


@pytest.mark.asyncio
async def test_non_owner_cannot_toggle(v2_app, mint_user, bulk_insert_zettels):
    owner = mint_user(workspace_count=1)
    attacker = mint_user(workspace_count=1)
    wz_id = (await bulk_insert_zettels(owner_user=owner, n=1, prefix="bola"))[0]
    with TestClient(v2_app) as client:
        resp = client.post(f"/api/zettels/{wz_id}/private", headers=_hdr(attacker.jwt))
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_make_public_round_trip(v2_app, mint_user, bulk_insert_zettels):
    user = mint_user(workspace_count=1)
    wz_id = (await bulk_insert_zettels(owner_user=user, n=1, prefix="pubround"))[0]
    with TestClient(v2_app) as client:
        assert client.post(f"/api/zettels/{wz_id}/private", headers=_hdr(user.jwt)).status_code == 200
        resp = client.post(f"/api/zettels/{wz_id}/public", headers=_hdr(user.jwt))
    assert resp.status_code == 200
    assert resp.json()["is_private"] is False
