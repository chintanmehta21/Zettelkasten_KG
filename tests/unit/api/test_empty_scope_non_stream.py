"""2026-08-01: corpus drift must not present as an HTTP 500.

``EmptyScopeError`` ("Scope resolved to zero Zettels") is raised by
``hybrid.py`` when a Kasten-scoped query matches no zettels — i.e. a DATA
condition, not a code fault. The streaming path has always handled it, emitting
a clean ``empty_scope`` SSE event. The NON-stream path used by
``POST /api/rag/adhoc`` had no catch at all, so it fell through to the app-wide
handler and returned ``500 {"error":"internal_server_error"}`` — and fired an
``#app-errors`` Slack page — every time.

Two consequences that made the 2026-07-31 outage harder to diagnose:
  * an empty/deleted corpus looked identical to a broken pipeline; and
  * ``ask_kasten``'s docstring claimed "the route layer maps these to the
    structured error envelope", which was simply untrue for this error.

Note the quota is consumed BEFORE the answer runs, so each occurrence also
burned a RAG_QUESTION with nothing to show for it. Refunding that is pricing
territory and is deliberately NOT addressed here.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from website.features.rag_pipeline.errors import EmptyScopeError


def test_empty_scope_maps_to_structured_4xx_not_500():
    """The handler must convert EmptyScopeError into a structured client error."""
    from website.app import _register_empty_scope_handler

    app = FastAPI()
    _register_empty_scope_handler(app)

    @app.get("/boom")
    async def boom():
        raise EmptyScopeError("Scope resolved to zero Zettels")

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/boom")

    assert resp.status_code == 422, "corpus drift is a client-visible condition, not a 500"
    body = resp.json()
    assert body["detail"]["code"] == "empty_scope"
    assert "message" in body["detail"]
    # Must not leak internals.
    assert "Traceback" not in resp.text
    assert "internal_server_error" not in resp.text


def test_empty_scope_message_matches_the_streaming_path():
    """Both transports should describe the same condition identically."""
    from website.app import _EMPTY_SCOPE_MESSAGE

    assert "no Zettels" in _EMPTY_SCOPE_MESSAGE


def test_http_exception_still_passes_through():
    """The new handler must not swallow ordinary HTTPExceptions."""
    from website.app import _register_empty_scope_handler

    app = FastAPI()
    _register_empty_scope_handler(app)

    @app.get("/boom")
    async def boom():
        raise HTTPException(status_code=403, detail="Forbidden")

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/boom")
    assert resp.status_code == 403


def test_handler_registered_on_the_real_app():
    import os

    for k, v in (
        ("GEMINI_API_KEY", "ci-stub"),
        ("SUPABASE_V2_URL", "https://ci-stub.supabase.co"),
        ("SUPABASE_V2_ANON_KEY", "a"),
        ("SUPABASE_V2_SERVICE_ROLE_KEY", "s"),
        ("NEXUS_TOKEN_ENCRYPTION_KEY", "7TgtMgeR5dMTnXxW6ULICwhf66A1VpzwuNFuIBqmoe4="),
    ):
        os.environ.setdefault(k, v)

    from website.app import create_app

    app = create_app()
    assert EmptyScopeError in app.exception_handlers


def test_ask_kasten_docstring_no_longer_lies():
    """The docstring claimed the route mapped EmptyScopeError. Now it does."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[3]
        / "website" / "api" / "module_runners" / "ask_kasten.py"
    ).read_text(encoding="utf-8")
    assert "the route layer maps these to the" in src
    # And the claim is now backed by a real handler.
    from website.app import _register_empty_scope_handler  # noqa: F401


@pytest.mark.parametrize("msg", ["Scope resolved to zero Zettels", ""])
def test_handler_is_robust_to_any_message(msg):
    from website.app import _register_empty_scope_handler

    app = FastAPI()
    _register_empty_scope_handler(app)

    @app.get("/boom")
    async def boom():
        raise EmptyScopeError(msg)

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/boom")
    assert resp.status_code == 422
