"""Tests for the website API routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from website.app import create_app


@pytest.fixture
def client():
    # Clear rate limiter state between tests
    from website.api import routes
    routes._rate_store.clear()

    app = create_app()
    return TestClient(app)


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


class TestSummarizeEndpoint:
    def test_missing_url_returns_422(self, client: TestClient) -> None:
        resp = client.post("/api/summarize", json={})
        assert resp.status_code == 422

    def test_invalid_url_returns_422(self, client: TestClient) -> None:
        resp = client.post("/api/summarize", json={"url": "not-a-url"})
        assert resp.status_code == 422

    def test_empty_url_returns_422(self, client: TestClient) -> None:
        resp = client.post("/api/summarize", json={"url": ""})
        assert resp.status_code == 422

    def test_successful_summarize(self, client: TestClient) -> None:
        mock_result = {
            "title": "Test Title",
            "summary": "Test summary",
            "brief_summary": "Brief",
            "tags": ["source/web"],
            "source_type": "web",
            "source_url": "https://example.com",
            "one_line_summary": "One liner",
            "is_raw_fallback": False,
            "tokens_used": 100,
            "latency_ms": 500,
            "metadata": {},
        }

        with patch("website.api.routes.summarize_url", new_callable=AsyncMock, return_value=mock_result):
            resp = client.post("/api/summarize", json={"url": "https://example.com"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Test Title"
        assert data["source_type"] == "web"

    def test_pipeline_error_returns_500(self, client: TestClient) -> None:
        with patch("website.api.routes.summarize_url", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            resp = client.post("/api/summarize", json={"url": "https://example.com"})

        assert resp.status_code == 500
        assert "boom" in resp.json()["detail"]


class TestRateLimit:
    def test_rate_limit_enforced(self, client: TestClient) -> None:
        """After 10 requests in quick succession, the 11th should be rate-limited."""
        mock_result = {
            "title": "t",
            "summary": "s",
            "brief_summary": "b",
            "tags": ["source/web"],
            "source_type": "web",
            "source_url": "https://example.com",
            "one_line_summary": "o",
            "is_raw_fallback": False,
            "tokens_used": 0,
            "latency_ms": 0,
            "metadata": {},
        }
        with patch("website.api.routes.summarize_url", new_callable=AsyncMock, return_value=mock_result):
            for _ in range(10):
                resp = client.post("/api/summarize", json={"url": "https://example.com"})
                assert resp.status_code == 200

            resp = client.post("/api/summarize", json={"url": "https://example.com"})
            assert resp.status_code == 429
