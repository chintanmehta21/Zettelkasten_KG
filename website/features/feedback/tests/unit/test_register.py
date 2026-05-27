"""Tests that register(app) wires the feature correctly."""
from __future__ import annotations

from fastapi import FastAPI

from website.features.feedback import register


def test_register_returns_app() -> None:
    app = FastAPI()
    out = register(app)
    assert out is app


def test_register_mounts_static_dir() -> None:
    app = FastAPI()
    register(app)
    routes = [r.path for r in app.routes]
    assert any(p.startswith("/feedback-ui") for p in routes), routes


def test_register_adds_feedback_router() -> None:
    app = FastAPI()
    register(app)
    paths = [r.path for r in app.routes]
    # /api/feedback/health is part of the router
    assert any("/api/feedback/health" in p for p in paths), paths
