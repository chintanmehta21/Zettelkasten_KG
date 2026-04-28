"""Iter-03 mem-bounded §2.8: GET /api/admin/_proc_stats returns proc stats.

Auth-gated against the single-tenant allowlist at ops/deploy/expected_users.json.
Non-allowlisted users get 404 (NOT 403, to avoid leaking the existence of admin
endpoints).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from website.api import admin_routes
from website.app import create_app

NARUTO = "f2105544-b73d-4946-8329-096d82f070d3"
ZORO = "a57e1f2f-7d89-4cd7-ae39-72c440ed4b4e"
RANDO = "11111111-1111-1111-1111-111111111111"


def _client_with_user(user_sub: str | None) -> TestClient:
    app = create_app()
    if user_sub is None:
        return TestClient(app)
    async def _stub_user():
        return {"sub": user_sub, "email": f"{user_sub}@test"}
    from website.api import auth as auth_mod
    app.dependency_overrides[auth_mod.get_current_user] = _stub_user
    return TestClient(app)


def test_admin_proc_stats_returns_json_for_allowlisted_user(monkeypatch):
    fake_stats = {"vm_rss_kb": 100, "vm_swap_kb": 0, "cgroup_mem_max": 1363148800}
    monkeypatch.setattr(admin_routes, "read_proc_stats", lambda: fake_stats)
    client = _client_with_user(NARUTO)
    r = client.get("/api/admin/_proc_stats")
    assert r.status_code == 200
    body = r.json()
    assert body["vm_rss_kb"] == 100


def test_admin_proc_stats_returns_404_for_random_user():
    client = _client_with_user(RANDO)
    r = client.get("/api/admin/_proc_stats")
    assert r.status_code == 404


def test_admin_proc_stats_returns_401_unauthenticated():
    client = _client_with_user(None)
    r = client.get("/api/admin/_proc_stats")
    assert r.status_code == 401
