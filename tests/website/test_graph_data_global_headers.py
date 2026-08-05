"""Unit test: /api/graph cache headers branch on view + my-anon hard-401.

view=global  public edge-cacheable, Vary: Accept-Encoding only, no Set-Cookie.
view=my      private, never edge-cacheable. Anonymous view=my  401. Settings are
mocked (get_settings() unmocked raises SystemExit(1)).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DB_SCHEMA_VERSION", "v2")
    from website.app import create_app
    return TestClient(create_app())


def _patch_runner(payload):
    # Patch run_view_graph where graph_data imports it (function-local import).
    return patch(
        "website.api.module_runners.view_graph.run_view_graph",
        return_value=payload,
    )


def test_global_response_is_public_no_cookie(client):
    payload = {"nodes": [], "links": [], "total_nodes": 0, "meta": {"view": "global", "source": "community"}}
    with _patch_runner(payload):
        resp = client.get("/api/graph?view=global&min_strength=0.3")
    assert resp.status_code in (200, 304)
    cc = resp.headers.get("Cache-Control", "")
    assert "public" in cc, cc
    assert "s-maxage=300" in cc, cc
    assert "stale-while-revalidate=600" in cc, cc
    assert "private" not in cc, cc
    assert resp.headers.get("Vary") == "Accept-Encoding"
    assert "set-cookie" not in {k.lower() for k in resp.headers.keys()}


def test_my_response_stays_private(monkeypatch):
    """Authed view=my must return private Cache-Control, never public."""
    monkeypatch.setenv("DB_SCHEMA_VERSION", "v2")
    from website.api.auth import get_optional_user
    from website.app import create_app

    app = create_app()
    # FastAPI dependency override: replace get_optional_user with a sync
    # callable that returns a fake authenticated user dict.
    app.dependency_overrides[get_optional_user] = lambda: {"sub": "u-test-1"}

    payload = {"nodes": [], "links": [], "total_nodes": 0, "meta": {"view": "my", "source": "v2"}}
    with TestClient(app) as client, _patch_runner(payload):
        resp = client.get("/api/graph?view=my&min_strength=0.3")
    cc = resp.headers.get("Cache-Control", "")
    assert "private" in cc, cc
    assert "public" not in cc, cc
    # Must NOT advertise Vary: Authorization (Cloudflare ignores it; false safety).
    assert "authorization" not in resp.headers.get("Vary", "").lower()


def test_anonymous_my_is_hard_401(client):
    """Anonymous explicit view=my  401 (Rev 3 hard-401), not an empty graph."""
    resp = client.get("/api/graph?view=my")
    assert resp.status_code == 401, resp.text
    assert "bearer" in resp.headers.get("WWW-Authenticate", "").lower()


def test_anonymous_global_still_ok(client):
    payload = {"nodes": [], "links": [], "total_nodes": 0, "meta": {"view": "global", "source": "community"}}
    with _patch_runner(payload):
        resp = client.get("/api/graph?view=global")
    assert resp.status_code in (200, 304)


def test_anonymous_omitted_view_resolves_global_ok(client):
    """No view + anonymous resolves to global  200, NOT 401."""
    payload = {"nodes": [], "links": [], "total_nodes": 0, "meta": {"view": "global", "source": "community"}}
    with _patch_runner(payload):
        resp = client.get("/api/graph")
    assert resp.status_code in (200, 304)
