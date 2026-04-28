"""Tests for the /api/health/warm pre-warm endpoint."""
from __future__ import annotations

from fastapi.testclient import TestClient

from website.app import create_app


def test_health_warm_returns_200():
    client = TestClient(create_app())
    r = client.get("/api/health/warm")
    assert r.status_code == 200
    body = r.json()
    assert body["warmed"] is True


def test_health_warm_reports_rerank_ms_field():
    """Warm endpoint must return a numeric ``rerank_ms`` regardless of model presence."""
    client = TestClient(create_app())
    r = client.get("/api/health/warm")
    body = r.json()
    assert "rerank_ms" in body
    assert isinstance(body["rerank_ms"], (int, float))
    assert body["rerank_ms"] >= 0
