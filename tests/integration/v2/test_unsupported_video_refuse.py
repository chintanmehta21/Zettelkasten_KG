"""H4/T7 — route handler returns HTTP 422 with unsupported_video_type on preflight refuse."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from website.features.summarization_engine.api.routes import router
from website.features.summarization_engine.core.errors import UnsupportedVideoError


@pytest.fixture(autouse=True)
def _stub_entitlement_gate(monkeypatch):
    """/api/v2/summarize now delegates to the shared add-zettel runner so the
    one dedup gate governs it. The entitlement gate + engine live in the
    runner module; patch there. No Supabase env -> v2 scope is None so the
    fresh path runs (engine is mocked below).
    """
    async def _allow(*_args, **_kwargs):
        return None
    monkeypatch.setattr(
        "website.api.module_runners.summarization.require_entitlement",
        _allow,
    )
    monkeypatch.setattr(
        "website.core.persist.get_supabase_v2_scope",
        lambda *_a, **_k: None,
    )


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@patch("website.api.module_runners.summarization.default_gemini_client")
@patch("website.api.module_runners.summarization.summarize_url_bundle")
def test_unsupported_video_private_returns_422(mock_bundle, mock_client):
    async def _raise(*a, **kw):
        raise UnsupportedVideoError(reason="private", url="https://youtube.com/watch?v=abc")

    mock_bundle.side_effect = _raise
    mock_client.return_value = object()

    resp = _client().post(
        "/api/v2/summarize", json={"url": "https://youtube.com/watch?v=abc"}
    )
    assert resp.status_code == 422
    detail = resp.json().get("detail", {})
    assert detail["error"] == "unsupported_video_type"
    assert detail["reason"] == "private"
    assert detail["confidence"] == "insufficient"
    assert detail["quality_signals"]["source_tier"] == "preflight_refused"
    assert detail["quality_signals"]["input_chars"] == 0


@patch("website.api.module_runners.summarization.default_gemini_client")
@patch("website.api.module_runners.summarization.summarize_url_bundle")
def test_unsupported_video_livestream_returns_422(mock_bundle, mock_client):
    async def _raise(*a, **kw):
        raise UnsupportedVideoError(
            reason="active_livestream", url="https://youtube.com/watch?v=def"
        )

    mock_bundle.side_effect = _raise
    mock_client.return_value = object()

    resp = _client().post(
        "/api/v2/summarize", json={"url": "https://youtube.com/watch?v=def"}
    )
    assert resp.status_code == 422
    detail = resp.json().get("detail", {})
    assert detail["error"] == "unsupported_video_type"
    assert detail["reason"] == "active_livestream"
