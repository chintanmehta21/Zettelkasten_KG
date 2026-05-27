"""When SLACK_BOT_TOKEN_FEEDBACK is empty, the route returns 503."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from website.features.feedback.api.routes import build_router
from website.features.feedback.core.settings import get_feedback_settings


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    get_feedback_settings.cache_clear()
    yield
    get_feedback_settings.cache_clear()


def test_submit_returns_503_when_token_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "SLACK_BOT_TOKEN_FEEDBACK",
        "SLACK_CHANNEL_FEEDBACK",
        "SECRET_FEEDBACK_COOKIE",
    ):
        monkeypatch.delenv(var, raising=False)

    app = FastAPI()
    # No slack_client_factory override — route will check settings and 503.
    app.include_router(build_router(), prefix="/api/feedback")
    client = TestClient(app)

    r = client.post(
        "/api/feedback/submit",
        data={"intent": "issue", "subject": "x",
              "description": "Long enough description here."},
    )
    assert r.status_code == 503
