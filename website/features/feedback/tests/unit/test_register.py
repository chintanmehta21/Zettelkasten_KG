"""Tests that register(app) wires the feature correctly."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import Mount

from website.features.feedback import register


def test_register_returns_app() -> None:
    app = FastAPI()
    out = register(app)
    assert out is app


def test_register_mounts_static_dir() -> None:
    app = FastAPI()
    register(app)
    # Static dirs are top-level Starlette Mounts (public .path); robust to the
    # FastAPI 0.137 route-tree change, which only wraps include_router nodes.
    mount_paths = [r.path for r in app.routes if isinstance(r, Mount)]
    assert any(p.startswith("/feedback-ui") for p in mount_paths), mount_paths


def test_register_serves_templates_under_feedback_ui() -> None:
    app = FastAPI()
    register(app)
    client = TestClient(app)

    r = client.get("/feedback-ui/templates/modal.html")

    assert r.status_code == 200
    assert "zk-feedback-form" in r.text


def test_register_adds_feedback_router() -> None:
    app = FastAPI()
    register(app)
    # Behavior-based: /api/feedback/health is registered (non-404). app.routes
    # is a tree on FastAPI 0.137, so we probe the route instead of iterating it.
    assert TestClient(app).get("/api/feedback/health").status_code != 404
