"""POST /api/monitor/pricing-visit — authenticated beacon endpoint.

Guards the screenshot regression: curl/internal/docker traffic was hitting
the old server-side notify_pricing_visit on GET /pricing because that path
had no auth gate. The beacon endpoint replaces that path — its
``Depends(get_current_user)`` rejects unauthenticated callers up-front so
the notifier is only ever reached for real users with a profile UUID.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from website.app import create_app
from website.features.web_monitor import User_Activity as ua_mod

NARUTO = "f2105544-b73d-4946-8329-096d82f070d3"


@pytest.fixture(autouse=True)
def _reset_pricing_throttle():
    ua_mod._pricing_seen_at.clear()
    yield
    ua_mod._pricing_seen_at.clear()


def _client_with_user(user: dict | None) -> TestClient:
    app = create_app()
    if user is not None:
        async def _stub_user():
            return user
        from website.api import auth as auth_mod
        app.dependency_overrides[auth_mod.get_current_user] = _stub_user
    return TestClient(app)


def test_pricing_beacon_rejects_unauthenticated_caller():
    """The whole point of moving the alert behind this endpoint: curl
    without a JWT (the screenshot case) gets 401 and never reaches the
    notifier. If this test ever fails, the auth gate has regressed."""
    client = _client_with_user(None)
    r = client.post("/api/monitor/pricing-visit")
    assert r.status_code == 401


def test_pricing_beacon_invokes_notifier_with_full_name_and_country(monkeypatch):
    """With a valid JWT, the beacon resolves display_name from user_metadata
    and forwards cf-ipcountry to the notifier as country_code."""
    captured: dict = {}

    async def _capture_notify(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(ua_mod, "notify_pricing_visit", _capture_notify)

    client = _client_with_user(
        {
            "sub": NARUTO,
            "email": "naruto@example.com",
            "user_metadata": {"full_name": "Naruto Uzumaki"},
        }
    )
    r = client.post(
        "/api/monitor/pricing-visit",
        headers={"cf-ipcountry": "IN", "user-agent": "Mozilla/5.0 test"},
    )
    assert r.status_code == 202

    # The endpoint schedules the notifier via create_task; give the loop a
    # beat to drain. TestClient runs each request in a fresh loop so we
    # cannot just await — but asyncio.sleep inside a sync test isn't valid
    # either. Instead, schedule a tiny synchronous wait via the next request
    # which forces TestClient to spin the loop.
    for _ in range(10):
        if captured:
            break
        client.get("/api/health")  # cheap hit to spin the loop

    assert captured.get("user_id") == NARUTO
    assert captured.get("display_name") == "Naruto Uzumaki"
    assert captured.get("email") == "naruto@example.com"
    assert captured.get("country_code") == "IN"


def test_pricing_beacon_falls_back_to_email_local_when_metadata_empty(monkeypatch):
    """No full_name in JWT metadata = display_name resolves via email
    local-part inside notify_pricing_visit. The beacon itself just passes
    None for display_name in that case (no DB lookup)."""
    captured: dict = {}

    async def _capture_notify(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(ua_mod, "notify_pricing_visit", _capture_notify)

    client = _client_with_user(
        {
            "sub": NARUTO,
            "email": "naruto@example.com",
            "user_metadata": {},  # no name fields
        }
    )
    r = client.post("/api/monitor/pricing-visit")
    assert r.status_code == 202

    for _ in range(10):
        if captured:
            break
        client.get("/api/health")

    assert captured.get("user_id") == NARUTO
    assert captured.get("display_name") is None
    assert captured.get("email") == "naruto@example.com"
