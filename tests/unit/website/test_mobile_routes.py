"""/m/zettels, /m/kastens, /m/profile always return 200 — auth gate is client-side.

The original iter-2a design used a server-side cookie check + 302 redirect for
gated pages. That approach was wrong: this codebase persists Supabase sessions
in localStorage (storageKey 'zk-auth-token' in auth-core.js), not cookies, so
the server can't reliably tell whether a real user is signed in. The gate now
lives in the page JS (zettels.js / kastens.js): they fetch /api/zettels or
/api/sandboxes with a Bearer token from window.getAuthToken and redirect to
/m/profile on a 401 or missing token (zettels keeps the just-captured stash
visible for the anon Summarize flow).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from website.app import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def test_zettels_always_200(client):
    r = client.get(
        "/m/zettels", follow_redirects=False, headers={"User-Agent": "iPhone"}
    )
    assert r.status_code == 200


def test_kastens_always_200(client):
    r = client.get(
        "/m/kastens", follow_redirects=False, headers={"User-Agent": "iPhone"}
    )
    assert r.status_code == 200


def test_profile_always_200(client):
    r = client.get("/m/profile", headers={"User-Agent": "iPhone"})
    assert r.status_code == 200


def test_zettels_just_captured_query_param_kept(client):
    """?just_captured=<id> passes through (zettels.js reads it to surface
    the freshly-captured zettel for anon viewers)."""
    r = client.get(
        "/m/zettels?just_captured=abc-123",
        follow_redirects=False,
        headers={"User-Agent": "iPhone"},
    )
    assert r.status_code == 200


def test_mobile_routes_inject_avatar_script(client):
    """All three new mobile pages must inject /m/js/avatar.js (T3) — that
    shared renderer is the only way the header avatar updates after sign-in."""
    for path in ("/m/zettels", "/m/kastens", "/m/profile"):
        r = client.get(path, headers={"User-Agent": "iPhone"})
        assert r.status_code == 200, path
        assert "/m/js/avatar.js" in r.text, path
