"""Feedback loader is injected into desktop and mobile shells."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from website.app import create_app


@asynccontextmanager
async def _noop_lifespan(_app):
    yield


def test_desktop_shell_injects_feedback_loader() -> None:
    app = create_app(lifespan=_noop_lifespan)
    client = TestClient(app)

    r = client.get("/?desktop=1")

    assert r.status_code == 200
    assert "/feedback-ui/feedback.js" in r.text


def test_mobile_shell_injects_feedback_loader() -> None:
    app = create_app(lifespan=_noop_lifespan)
    client = TestClient(app)

    r = client.get("/m/")

    assert r.status_code == 200
    assert "/feedback-ui/feedback.js" in r.text
