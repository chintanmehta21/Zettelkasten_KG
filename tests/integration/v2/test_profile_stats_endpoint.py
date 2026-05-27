"""Integration tests for GET /api/profile/stats (live HTTP path).

Exercises route -> runner -> repository -> SECURITY DEFINER RPCs -> DB.
@pytest.mark.live so the suite is skipped by default; runs when migrations
79/80/81/82 are applied + Supabase v2 env vars are set.

Companion to:
- tests/integration/v2/test_profile_stats_rpc.py (RPC-only)
- tests/unit/website/test_profile_routes.py (mocked route)
- tests/unit/website/user_stats/ (mocked unit tests for module pieces)
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def live_app():
    """Build the real FastAPI app (with all routers) for end-to-end tests.

    Import inside the fixture so module-level imports don't fire during
    collection on non-live test runs.
    """
    from website.app import create_app

    return create_app()


@pytest.fixture
def live_client(live_app):
    return TestClient(live_app)


@pytest.mark.asyncio
async def test_endpoint_returns_full_payload(live_client, mint_user, seed_zettels):
    """200 + ETag header + payload shape includes all 7 sections + meta."""
    user = mint_user(workspace_count=1)
    workspace_id = user.workspace_ids[0]
    await seed_zettels(workspace_id, count=5)

    resp = live_client.get(
        "/api/profile/stats",
        headers={"authorization": f"Bearer {user.jwt}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("etag", "") != ""
    assert resp.headers.get("cache-control") == "private, max-age=60"
    assert resp.headers.get("x-stats-cache") in ("hit", "miss")

    body = resp.json()
    # All 7 sections + meta should be present.
    assert {"meta", "main_board", "general", "zettel", "kasten",
            "domain", "activity", "graph"} <= set(body.keys())
    # meta.workspace_id should round-trip.
    assert body["meta"]["workspace_id"] == str(workspace_id)
    # main_board.zettels lifetime should reflect the 5 seeded zettels.
    assert body["main_board"]["zettels"]["lifetime_count"] == 5
    # Quota fields should be present (composed by runner; "free" plan caps).
    assert "zettels_quota" in body["main_board"]
    assert "kastens_quota" in body["main_board"]
    # plan.tier should be the hardcoded "free" for v1.
    assert body["general"]["plan"]["tier"] == "free"


@pytest.mark.asyncio
async def test_endpoint_returns_304_on_matching_etag(
    live_client, mint_user, seed_zettels
):
    """If-None-Match with the current ETag -> 304 Not Modified."""
    user = mint_user(workspace_count=1)
    workspace_id = user.workspace_ids[0]
    await seed_zettels(workspace_id, count=3)

    # First call to get a fresh ETag.
    r1 = live_client.get(
        "/api/profile/stats",
        headers={"authorization": f"Bearer {user.jwt}"},
    )
    assert r1.status_code == 200
    etag = r1.headers["etag"]

    # Second call with the same ETag should short-circuit.
    r2 = live_client.get(
        "/api/profile/stats",
        headers={
            "authorization": f"Bearer {user.jwt}",
            "if-none-match": etag,
        },
    )
    assert r2.status_code == 304
    assert r2.headers.get("etag") == etag


@pytest.mark.asyncio
async def test_endpoint_503_when_disabled(live_app, live_client, mint_user):
    """Kill-switch path: stats_tab_enabled=False -> 503."""
    import unittest.mock as mock

    from website.api import profile_routes as routes_mod

    user = mint_user(workspace_count=1)
    fake_settings = mock.MagicMock()
    fake_settings.stats_tab_enabled = False
    fake_settings.stats_tab_allowlist = ""

    # Patch the get_settings call inside the route at request time.
    with mock.patch.object(routes_mod, "get_settings", return_value=fake_settings):
        resp = live_client.get(
            "/api/profile/stats",
            headers={"authorization": f"Bearer {user.jwt}"},
        )
    assert resp.status_code == 503
    assert "disabled" in resp.json()["detail"].lower()


# TODO(v1.5): test semaphore saturation requires concurrent client harness;
# left as a manual smoke test. Operator can saturate by hammering with
# `xargs -P 5 curl ...` and observe Retry-After: 5 on the 503.
