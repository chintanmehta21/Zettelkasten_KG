"""/api/profile route tests with mocked Supabase repository.

Adaptation notes (starlette 1.0.0 + httpx 0.28):
- ``cookies=`` per-request kwarg is deprecated in starlette 1.0; we use
  ``headers={"Cookie": ...}`` instead to pass the auth cookie.
- ``@patch("...._require_user")`` does not override FastAPI Depends because
  the Depends() captures the function reference at import time. We use
  ``app.dependency_overrides[_require_user]`` for the three tests that need
  an authenticated user.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from website.app import create_app
from website.features.user_profile.routes import _require_user


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)


def test_get_profile_unauth_returns_401(client):
    r = client.get("/api/profile")
    assert r.status_code == 401


def test_patch_profile_unauth_returns_401(client):
    r = client.patch("/api/profile", json={"avatar_url": "/artifacts/avatars/avatar_07.svg"})
    assert r.status_code == 401


@patch("website.features.user_profile.routes.repository.update_avatar")
def test_patch_profile_success(mock_update, app):
    mock_update.return_value = {"id": "user-1", "email": "x@y.z", "avatar_url": "/artifacts/avatars/avatar_22.svg"}
    app.dependency_overrides[_require_user] = lambda: {
        "id": "user-1", "email": "x@y.z", "avatar_url": "/artifacts/avatars/avatar_00.svg"
    }
    try:
        r = TestClient(app).patch(
            "/api/profile",
            json={"avatar_url": "/artifacts/avatars/avatar_22.svg"},
        )
        assert r.status_code == 200
        assert r.json()["avatar_url"] == "/artifacts/avatars/avatar_22.svg"
    finally:
        app.dependency_overrides.clear()


def test_patch_profile_invalid_url_returns_422(app):
    app.dependency_overrides[_require_user] = lambda: {
        "id": "u", "email": "x", "avatar_url": "/artifacts/avatars/avatar_00.svg"
    }
    try:
        r = TestClient(app).patch(
            "/api/profile",
            json={"avatar_url": "/artifacts/avatars/avatar_60.svg"},
        )
        assert r.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_patch_profile_path_traversal_returns_422(app):
    app.dependency_overrides[_require_user] = lambda: {
        "id": "u", "email": "x", "avatar_url": "/artifacts/avatars/avatar_00.svg"
    }
    try:
        r = TestClient(app).patch(
            "/api/profile",
            json={"avatar_url": "/artifacts/avatars/../../etc/passwd"},
        )
        assert r.status_code == 422
    finally:
        app.dependency_overrides.clear()
