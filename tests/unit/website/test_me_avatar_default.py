"""R5 (avatar reconcile, 2026-05-30): /api/me read-time avatar curation.

DB-as-source-of-truth with read-time curation: /api/me serves the stored avatar
ONLY if it matches the curated allowlist (0-119), else a curated default, and
NEVER echoes the (user-modifiable, external) JWT user_metadata.avatar_url, and
NEVER returns "". Closes the recurring re-population hole: Supabase re-writes
user_metadata on every OAuth login, so the gate must live at read time.

Pins:
- v2 path, curated DB value → returned verbatim.
- v2 path, NULL DB value → curated default.
- v2 path, NON-curated DB value (external URL) → curated default (read-time gate).
- jwt_fallback path → curated default, never the JWT claim.
- /api/me carries Cache-Control: private, no-store.
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


def _run_v2(profile_row):
    repo_instance = MagicMock()
    repo_instance.get_profile = MagicMock(return_value=profile_row)
    repo_cls = MagicMock(return_value=repo_instance)
    with patch("website.api.routes.use_supabase_v2", return_value=True), \
         patch("website.api.routes.get_supabase_v2_scope_for_read",
               return_value=(MagicMock(), NARUTO, [])), \
         patch("website.core.supabase_v2.client.get_v2_client", return_value=MagicMock()), \
         patch("website.core.supabase_v2.repositories.core_repository.CoreRepository", repo_cls), \
         patch("website.features.web_monitor.maybe_fire_signup_alert"):
        client = _build_client(_user())
        return client.get("/api/me", headers={"Authorization": "Bearer fake.jwt"})


def test_me_v2_returns_curated_db_avatar():
    resp = _run_v2(_profile("/artifacts/avatars/avatar_99.svg"))  # 99 in [0,119]
    assert resp.status_code == 200
    body = resp.json()
    assert body["profile_source"] == "v2"
    assert body["avatar_url"] == "/artifacts/avatars/avatar_99.svg"


def test_me_v2_curates_null_db_avatar_to_default():
    resp = _run_v2(_profile(None))
    assert resp.status_code == 200
    assert resp.json()["avatar_url"] == DEFAULT_AVATAR_URL


def test_me_v2_curates_noncurated_db_avatar_to_default():
    """Read-time gate: an external/non-curated value in core.profiles.avatar_url
    (e.g. a synced IdP URL) is NEVER reflected — defaults instead."""
    resp = _run_v2(_profile("https://lh3.googleusercontent.com/evil.jpg"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["avatar_url"] == DEFAULT_AVATAR_URL
    assert "googleusercontent" not in body["avatar_url"]


def test_me_v2_rejects_out_of_range_avatar():
    """avatar_120 is past the curated set (0-119) → default."""
    resp = _run_v2(_profile("/artifacts/avatars/avatar_120.svg"))
    assert resp.status_code == 200
    assert resp.json()["avatar_url"] == DEFAULT_AVATAR_URL


def test_me_sets_private_no_store_cache_header():
    with patch("website.api.routes.use_supabase_v2", return_value=False):
        client = _build_client(_user())
        resp = client.get("/api/me", headers={"Authorization": "Bearer fake.jwt"})
    assert resp.status_code == 200
    cc = resp.headers.get("cache-control", "")
    assert "private" in cc and "no-store" in cc, f"unexpected Cache-Control: {cc!r}"


def test_me_jwt_fallback_returns_curated_default_not_jwt_claim():
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
