"""Smoke tests for the gunicorn --preload entrypoint contract."""
from __future__ import annotations


def test_app_importable():
    from website.main import app

    assert app is not None


def test_app_has_health_route():
    from fastapi.testclient import TestClient

    from website.main import app

    # Behavior-based: app.routes is a tree on FastAPI 0.137 (an internal
    # detail). A registered health path returns non-404.
    client = TestClient(app)
    assert (
        client.get("/api/health").status_code != 404
        or client.get("/api/health/warm").status_code != 404
    )
