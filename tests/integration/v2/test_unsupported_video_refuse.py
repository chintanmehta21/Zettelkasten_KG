"""H4/T7 — unsupported-video preflight refusal on /api/v2/summarize.

ADR-3 (2026-05-22) CONTRACT CHANGE: ``POST /api/v2/summarize`` is now async-ops
(202 + ``status_url`` + poll). An ``UnsupportedVideoError`` raised mid-pipeline
is a hard exception, so it finalizes the operation as ``failed`` with an
RFC 9457 ``unsupported-video`` error payload on the operations row. These
tests intercept the background ``operations_repo.finalize`` write to assert
that contract — the body ``GET /api/operations/{id}`` subsequently returns.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from website.features.summarization_engine.api.routes import router
from website.features.summarization_engine.core.errors import UnsupportedVideoError


@pytest.fixture(autouse=True)
def _stub_entitlement_gate(monkeypatch):
    """/api/v2/summarize delegates to the shared add-zettel runner so the one
    dedup gate governs it. Entitlement + engine live in the runner module;
    patch there. No Supabase env -> v2 scope is None so the fresh path runs.
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
    # _run_add_zettel passes zettels_routes._gemini_client as the client
    # factory; run_add_zettel_pipeline CALLS it before summarize_url_bundle
    # runs. Stub it so the pipeline reaches summarize_url_bundle (which raises
    # UnsupportedVideoError) instead of dying on a missing-Gemini-key
    # ValueError — that was the order-dependent failure.
    monkeypatch.setattr(
        "website.api.zettels_routes._gemini_client", lambda: object()
    )


def _client_and_captured(monkeypatch) -> tuple[TestClient, dict]:
    """v2-router-only app + stubbed ops state machine so the background
    ``_run`` worker finalizes deterministically. Returns the TestClient and
    the ``captured`` dict recording the finalize call."""
    from website.api import zettels_routes
    from website.api.module_runners import summarization as runner

    captured: dict = {}

    def _finalize(**kw):
        captured["called"] = True
        captured.update(kw)
        return True

    # is_new=False -> _accept_and_spawn records the 202 but spawns NO
    # background _run task. The test drives _run itself (below), so there is
    # no flaky spawn/poll race and no _run task leaking into the next test.
    monkeypatch.setattr(zettels_routes.operations_repo, "accept",
                        lambda **kw: (kw["operation_id"], False))
    monkeypatch.setattr(zettels_routes.operations_repo, "start",
                        lambda **kw: True)
    monkeypatch.setattr(zettels_routes.operations_repo, "finalize", _finalize)
    monkeypatch.setattr(runner, "resolve_redirects",
                        AsyncMock(side_effect=lambda url: url))
    monkeypatch.setattr(runner, "normalize_url", lambda url: url)

    app = FastAPI()
    app.include_router(router)
    return TestClient(app), captured


def _drive_bg_to_finalize(url: str, captured: dict) -> None:
    """Run the v2-summarize pipeline through ``_run`` once, deterministically,
    in the test thread (the route spawns nothing — see the accept stub)."""
    _ = captured
    from website.api import zettels_routes as zr

    operation_id = f"v2-summarize-{url}"
    user_id = zr._effective_user_id(None)
    body = zr.AddZettelRequest(
        url=url, client_action_id=operation_id, persist=False, surface="landing",
    )
    asyncio.run(
        zr._run(
            user_id=user_id,
            operation_id=operation_id,
            pipeline=lambda: zr._run_add_zettel(
                body, user={"sub": str(user_id)}, effective_user_id=user_id
            ),
            persist_requested=False,
        )
    )


@patch("website.api.module_runners.summarization.default_gemini_client")
@patch("website.api.module_runners.summarization.summarize_url_bundle")
def test_unsupported_video_private_finalizes_failed(
    mock_bundle, mock_client, monkeypatch
):
    async def _raise(*a, **kw):
        raise UnsupportedVideoError(reason="private", url="https://youtube.com/watch?v=abc")

    mock_bundle.side_effect = _raise
    mock_client.return_value = object()

    client, captured = _client_and_captured(monkeypatch)
    resp = client.post(
        "/api/v2/summarize", json={"url": "https://youtube.com/watch?v=abc"}
    )
    assert resp.status_code == 202, resp.text

    _drive_bg_to_finalize("https://youtube.com/watch?v=abc", captured)

    assert captured.get("target") == "failed"
    response_body = captured.get("response") or {}
    assert response_body.get("status") == "failed"
    error = captured.get("error") or {}
    # UnsupportedVideoError -> RFC 9457 "Unsupported video" problem.
    assert error.get("title") == "Unsupported video"
    assert error.get("status") == 422
    assert "private" in str(error.get("detail") or "")


@patch("website.api.module_runners.summarization.default_gemini_client")
@patch("website.api.module_runners.summarization.summarize_url_bundle")
def test_unsupported_video_livestream_finalizes_failed(
    mock_bundle, mock_client, monkeypatch
):
    async def _raise(*a, **kw):
        raise UnsupportedVideoError(
            reason="active_livestream", url="https://youtube.com/watch?v=def"
        )

    mock_bundle.side_effect = _raise
    mock_client.return_value = object()

    client, captured = _client_and_captured(monkeypatch)
    resp = client.post(
        "/api/v2/summarize", json={"url": "https://youtube.com/watch?v=def"}
    )
    assert resp.status_code == 202, resp.text

    _drive_bg_to_finalize("https://youtube.com/watch?v=def", captured)

    assert captured.get("target") == "failed"
    error = captured.get("error") or {}
    assert error.get("title") == "Unsupported video"
    assert "active_livestream" in str(error.get("detail") or "")
