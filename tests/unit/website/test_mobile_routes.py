"""Auth-gate + redirect tests for /m/zettels, /m/kastens, /m/profile."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from website.app import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def test_zettels_unauth_redirects_to_profile(client):
    r = client.get("/m/zettels", follow_redirects=False, headers={"User-Agent": "iPhone"})
    assert r.status_code == 302
    assert r.headers["location"] == "/m/profile"


def test_kastens_unauth_redirects_to_profile(client):
    r = client.get("/m/kastens", follow_redirects=False, headers={"User-Agent": "iPhone"})
    assert r.status_code == 302
    assert r.headers["location"] == "/m/profile"


def test_profile_always_200(client):
    r = client.get("/m/profile", headers={"User-Agent": "iPhone"})
    assert r.status_code == 200


def test_zettels_just_captured_anon_allowed(client):
    """Anon Summarize redirects to /m/zettels?just_captured=<id>; do NOT bounce."""
    r = client.get(
        "/m/zettels?just_captured=abc-123",
        follow_redirects=False,
        headers={"User-Agent": "iPhone"},
    )
    assert r.status_code == 200


@patch("website.app._has_supabase_session", return_value=True)
def test_zettels_auth_renders(mock_sess, client):
    r = client.get("/m/zettels", headers={"User-Agent": "iPhone"})
    assert r.status_code == 200


@patch("website.app._has_supabase_session", return_value=True)
def test_kastens_auth_renders(mock_sess, client):
    r = client.get("/m/kastens", headers={"User-Agent": "iPhone"})
    assert r.status_code == 200
