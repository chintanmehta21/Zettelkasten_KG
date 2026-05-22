"""Tests for the website API routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from website.app import create_app


@pytest.fixture
def client():
    # Clear rate limiter state between tests
    from website.api import zettels_routes
    zettels_routes._RATE_STORE.clear()

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    zettels_routes._RATE_STORE.clear()


class TestHealthEndpoint:
    def test_health_returns_ok(self, client: TestClient) -> None:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestIndexPage:
    def test_index_returns_html(self, client: TestClient) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Zettelkasten" in resp.text

    @pytest.mark.parametrize("path", ["/", "/m/", "/home", "/home/zettels"])
    def test_html_pages_revalidate_asset_references(self, client: TestClient, path: str) -> None:
        resp = client.get(path)
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-cache, max-age=0, must-revalidate"


class TestAddZettelEndpoint:
    def test_missing_url_returns_422(self, client: TestClient) -> None:
        resp = client.post("/api/zettels/add", json={})
        assert resp.status_code == 422

    def test_invalid_url_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/zettels/add",
            json={"url": "not-a-url", "client_action_id": "a", "surface": "landing"},
        )
        assert resp.status_code == 422

    def test_empty_url_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/zettels/add",
            json={"url": "", "client_action_id": "a", "surface": "landing"},
        )
        assert resp.status_code == 422


class TestRateLimit:
    def test_rate_limit_enforced(self, client: TestClient, monkeypatch) -> None:
        """After 10 requests in quick succession, the 11th should be rate-limited.

        PR #39 / Wave-1 A1 (2026-05-20): the route is now always-async (202)
        regardless of pipeline outcome — the inline 200 path is gone. Each
        of the first 10 calls returns 202; the 11th is 429 from the rate
        limiter which fires BEFORE accept (same precondition as before)."""
        from unittest.mock import AsyncMock
        from website.api import zettels_routes

        async def fake_run(body, *, user, effective_user_id):
            return {"status": "succeeded"}

        monkeypatch.setattr(zettels_routes, "_run_add_zettel", fake_run)
        # Stub the ops state machine so the bg _run task doesn't hit real Supabase.
        monkeypatch.setattr(zettels_routes.operations_repo, "accept",
                            lambda **kw: (kw["operation_id"], True))
        monkeypatch.setattr(zettels_routes.operations_repo, "start",
                            lambda **kw: True)
        monkeypatch.setattr(zettels_routes.operations_repo, "finalize",
                            lambda **kw: True)
        monkeypatch.setattr(zettels_routes, "check_async_backpressure",
                            AsyncMock(return_value=None))

        for i in range(10):
            resp = client.post(
                "/api/zettels/add",
                json={
                    "url": f"https://example.com/{i}",
                    "client_action_id": f"a-{i}",
                    "surface": "landing",
                },
            )
            assert resp.status_code == 202

        resp = client.post(
            "/api/zettels/add",
            json={
                "url": "https://example.com/limited",
                "client_action_id": "a-11",
                "surface": "landing",
            },
        )
        assert resp.status_code == 429
