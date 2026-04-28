"""Smoke tests for the gunicorn --preload entrypoint contract."""
from __future__ import annotations


def test_app_importable():
    from website.main import app

    assert app is not None


def test_app_has_health_route():
    from website.main import app

    paths = [getattr(r, "path", "") for r in app.routes]
    assert "/api/health" in paths or "/api/health/warm" in paths
