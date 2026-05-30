"""R5 (2026-05-30): /api/me must NEVER return an empty avatar_url.

DB-as-source-of-truth: prefer core.profiles.avatar_url, fall back to the
curated default (avatar_00.svg), and stop echoing the JWT user_metadata
avatar (migration 78 strips it → "" → looked like a wipe on the frontend).

Pins:
- v2 path, profile.avatar_url set → returns it verbatim.
- v2 path, profile.avatar_url null → returns DEFAULT_AVATAR_URL (never "").
- jwt_fallback path (v2 disabled) → returns DEFAULT_AVATAR_URL (never the JWT claim).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from website.api.routes import DEFAULT_AVATAR_URL


NARUTO = "550e8400-e29b-41d4-a716-446655440000"


def _build_client(user: dict) -> TestClient:
    from website.api import auth as auth_mod
    from website.app import create_app

    app = create_app()

    async def _stub() -> dict:
        return user

    app.dependency_overrides[auth_mod.get_current_user] = _stub
    return TestClient(app)


def _user(metadata: dict | None = None) -> dict:
    return {
        "sub": NARUTO,
        "email": "naruto@example.com",
        "user_metadata": metadata if metadata is not None else {"full_name": "Naruto Uzumaki"},
    }


def _profile(avatar_url):
    return {
        "id": NARUTO,
        "email": "naruto@example.com",
        "display_name": "Naruto Uzumaki",
        "avatar_url": avatar_url,
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def test_me_v2_returns_db_avatar_when_set():
    repo_instance = MagicMock()
    repo_instance.get_profile = MagicMock(return_value=_profile("/artifacts/avatars/avatar_42.svg"))
    repo_cls = MagicMock(return_value=repo_instance)

    with patch("website.api.routes.use_supabase_v2", return_value=True), \
         patch("website.api.routes.get_supabase_v2_scope_for_read",
               return_value=(MagicMock(), NARUTO, [])), \
         patch("website.core.supabase_v2.client.get_v2_client", return_value=MagicMock()), \
         patch("website.core.supabase_v2.repositories.core_repository.CoreRepository", repo_cls), \
         patch("website.features.web_monitor.maybe_fire_signup_alert"):
        client = _build_client(_user())
        resp = client.get("/api/me", headers={"Authorization": "Bearer fake.jwt"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["profile_source"] == "v2"
    assert body["avatar_url"] == "/artifacts/avatars/avatar_42.svg"


def test_me_v2_returns_curated_default_when_db_avatar_null():
    repo_instance = MagicMock()
    repo_instance.get_profile = MagicMock(return_value=_profile(None))
    repo_cls = MagicMock(return_value=repo_instance)

    with patch("website.api.routes.use_supabase_v2", return_value=True), \
         patch("website.api.routes.get_supabase_v2_scope_for_read",
               return_value=(MagicMock(), NARUTO, [])), \
         patch("website.core.supabase_v2.client.get_v2_client", return_value=MagicMock()), \
         patch("website.core.supabase_v2.repositories.core_repository.CoreRepository", repo_cls), \
         patch("website.features.web_monitor.maybe_fire_signup_alert"):
        client = _build_client(_user())
        resp = client.get("/api/me", headers={"Authorization": "Bearer fake.jwt"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["profile_source"] == "v2"
    assert body["avatar_url"] == DEFAULT_AVATAR_URL
    assert body["avatar_url"] != ""


def test_me_sets_private_no_store_cache_header():
    """R4a: /api/me is a personalized payload — must carry Cache-Control:
    private, no-store so neither the browser HTTP cache nor Cloudflare serves
    a stale profile after an avatar save."""
    with patch("website.api.routes.use_supabase_v2", return_value=False):
        client = _build_client(_user())
        resp = client.get("/api/me", headers={"Authorization": "Bearer fake.jwt"})

    assert resp.status_code == 200
    cc = resp.headers.get("cache-control", "")
    assert "private" in cc and "no-store" in cc, f"unexpected Cache-Control: {cc!r}"


def test_me_jwt_fallback_returns_curated_default_not_jwt_claim():
    """v2 disabled → jwt_fallback path. Even if the JWT carries a (stale, external)
    avatar_url, R5 serves the curated default instead of echoing it."""
    with patch("website.api.routes.use_supabase_v2", return_value=False):
        client = _build_client(_user(metadata={
            "full_name": "Naruto Uzumaki",
            "avatar_url": "https://lh3.googleusercontent.com/evil-stale.jpg",
        }))
        resp = client.get("/api/me", headers={"Authorization": "Bearer fake.jwt"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["profile_source"] == "jwt_fallback"
    assert body["avatar_url"] == DEFAULT_AVATAR_URL
    assert "googleusercontent" not in body["avatar_url"]
