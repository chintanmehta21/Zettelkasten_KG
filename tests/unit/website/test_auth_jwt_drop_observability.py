"""JWT-silent-drop-to-Zoro observability contract.

Production bug 2026-05-25 (Prajeet audit §4.a): when a request's Bearer
JWT fails server-side validation, ``get_optional_user`` swallows the
exception and returns ``None``. Downstream ``_effective_user_id(None)`` then
maps the request to the canonical Zoro UUID. There is NO log entry telling
operators *why* the JWT failed, and NO response header telling the frontend
the auth was downgraded — so the UI keeps showing "Welcome back, Prajeet"
while the API treats the request as anonymous.

Confirmed in Caddy access log for Prajeet's 07:24:17 GMT request:
the Authorization header was present (REDACTED in the log) yet the resulting
``core.operations`` row landed under Zoro's user_id, not Prajeet's. Every
forensic trail this morning hit the same dead end.

This module pins three observability invariants:

  1. **No-Auth-header path stays SILENT** — legitimate anonymous traffic
     must not generate log noise OR set the drop header.
  2. **Bad-JWT path emits a structured ``logger.warning``** and sets
     ``request.state.auth_status = 'jwt-dropped-to-anon'`` so a middleware
     can attach ``X-Auth-Status: jwt-dropped-to-anon`` to the response.
  3. **Valid-JWT path leaves both untouched** — happy path unchanged.

A middleware in ``website/app.py`` reads ``request.state.auth_status`` and
sets the ``X-Auth-Status`` response header. The integration test at the
bottom of this file exercises the full chain through ``create_app()``.
"""
from __future__ import annotations

import logging
import time
from unittest.mock import patch

import jwt as pyjwt
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from website.api.auth import get_optional_user


TEST_SECRET = "test-jwt-secret-that-is-long-enough-for-hs256!!"


def _make_jwt(payload: dict | None = None, secret: str = TEST_SECRET) -> str:
    defaults = {
        "sub": "550e8400-e29b-41d4-a716-446655440000",
        "email": "test@example.com",
        "aud": "authenticated",
        "role": "authenticated",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    defaults.update(payload or {})
    return pyjwt.encode(defaults, secret, algorithm="HS256")


def _build_probe_app() -> FastAPI:
    """Tiny app that exposes the request.state.auth_status the dep set.

    Keeps the unit tests independent of website.app.create_app (which would
    bring up Supabase clients, lifespan hooks, etc.). The integration test
    at the bottom of this file runs against the real factory.
    """
    app = FastAPI()

    @app.get("/probe")
    async def probe(
        request: Request,
        user: dict | None = Depends(get_optional_user),
    ):
        return {
            "user_sub": user["sub"] if user else None,
            "auth_status": getattr(request.state, "auth_status", None),
        }

    return app


# ── 1. Legitimate anonymous (no Authorization header) ─────────────────────


@patch("website.api.auth._get_jwt_secret", return_value=TEST_SECRET)
def test_no_auth_header_does_not_log_warning(_secret, caplog) -> None:
    """A request with NO Authorization header is a legitimate anonymous
    caller — it must not generate any WARNING-level log line nor leak a
    drop-status to the response."""
    client = TestClient(_build_probe_app())
    with caplog.at_level(logging.WARNING, logger="website.api.auth"):
        resp = client.get("/probe")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_sub"] is None
    assert body["auth_status"] is None, (
        "Legitimate anon path must not set request.state.auth_status"
    )
    drop_warnings = [
        r for r in caplog.records
        if r.name == "website.api.auth" and "jwt" in r.message.lower()
    ]
    assert not drop_warnings, (
        f"Legitimate anon must not emit JWT-drop warning. Got: {drop_warnings!r}"
    )


# ── 2. Bad-JWT path (the bug being fixed) ─────────────────────────────────


@patch("website.api.auth._get_jwt_secret", return_value=TEST_SECRET)
def test_invalid_jwt_emits_structured_warning(_secret, caplog) -> None:
    """A request with a malformed/invalid Bearer JWT must emit a single
    WARNING-level log line on the ``website.api.auth`` logger so operators
    can grep droplet stdout for the cause. The log line must name the
    exception type (e.g. DecodeError) so triage is one keystroke."""
    client = TestClient(_build_probe_app())
    with caplog.at_level(logging.WARNING, logger="website.api.auth"):
        resp = client.get("/probe", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 200
    drop_warnings = [
        r for r in caplog.records
        if r.name == "website.api.auth" and r.levelno == logging.WARNING
    ]
    assert len(drop_warnings) == 1, (
        f"Expected exactly 1 JWT-drop warning; got {len(drop_warnings)}: "
        f"{[r.message for r in drop_warnings]!r}"
    )
    msg = drop_warnings[0].getMessage().lower()
    assert "jwt" in msg or "token" in msg, (
        f"Warning message should name the auth failure: {msg!r}"
    )


@patch("website.api.auth._get_jwt_secret", return_value=TEST_SECRET)
def test_invalid_jwt_sets_request_state_auth_status(_secret) -> None:
    """The dependency must mark the request as ``jwt-dropped-to-anon`` on
    request.state so a downstream middleware can surface the header."""
    client = TestClient(_build_probe_app())
    resp = client.get("/probe", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 200
    assert resp.json()["auth_status"] == "jwt-dropped-to-anon"


@patch("website.api.auth._get_jwt_secret", return_value=TEST_SECRET)
def test_expired_jwt_also_marks_dropped(_secret) -> None:
    """Expired JWTs must follow the same observability contract as malformed
    JWTs — they are a separate exception class (``ExpiredSignatureError``)
    but the user-facing outcome is identical."""
    client = TestClient(_build_probe_app())
    token = _make_jwt({"exp": int(time.time()) - 100})
    resp = client.get("/probe", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["user_sub"] is None
    assert resp.json()["auth_status"] == "jwt-dropped-to-anon"


@patch("website.api.auth._get_jwt_secret", return_value=TEST_SECRET)
def test_wrong_signature_jwt_marks_dropped(_secret) -> None:
    """A JWT signed with the wrong secret must hit the same drop branch."""
    client = TestClient(_build_probe_app())
    token = _make_jwt({}, secret="wrong-secret-wrong-secret-wrong-secret!!")
    resp = client.get("/probe", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["auth_status"] == "jwt-dropped-to-anon"


# ── 3. Valid-JWT happy path ───────────────────────────────────────────────


@patch("website.api.auth._get_jwt_secret", return_value=TEST_SECRET)
def test_valid_jwt_does_not_set_drop_marker(_secret, caplog) -> None:
    """The happy path must not regress — valid JWTs leave both
    request.state.auth_status AND the warning channel untouched."""
    client = TestClient(_build_probe_app())
    token = _make_jwt()
    with caplog.at_level(logging.WARNING, logger="website.api.auth"):
        resp = client.get(
            "/probe", headers={"Authorization": f"Bearer {token}"}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_sub"] == "550e8400-e29b-41d4-a716-446655440000"
    assert body["auth_status"] is None
    drop_warnings = [
        r for r in caplog.records
        if r.name == "website.api.auth" and r.levelno == logging.WARNING
    ]
    assert not drop_warnings, (
        f"Valid JWT must not emit drop warning. Got: {drop_warnings!r}"
    )


# ── 4. End-to-end: X-Auth-Status response header via real middleware ──────


@patch("website.api.auth._get_jwt_secret", return_value=TEST_SECRET)
def test_response_carries_x_auth_status_on_jwt_drop(_secret) -> None:
    """End-to-end: when a bad JWT triggers the drop branch, the response
    from a route depending on ``get_optional_user`` MUST carry
    ``X-Auth-Status: jwt-dropped-to-anon`` (the middleware in
    website/app.py reads ``request.state.auth_status`` and writes the
    header). This is the signal the frontend uses to know it should
    re-auth rather than silently submitting under Zoro."""
    from website.app import create_app

    app = create_app()
    client = TestClient(app)
    # /api/auth/config is a simple route that doesn't depend on get_optional_user;
    # /api/health/live is unauthenticated. We need a route that resolves the
    # auth dep. /api/me is the canonical one but it requires get_current_user
    # (raises 401). Use /api/graph which calls get_optional_user.
    resp = client.get("/api/graph", headers={"Authorization": "Bearer garbage"})
    # 200 (anon graph) or 503 (DB unavailable in test env) — we just need to
    # confirm the dep fired and the middleware set the header on the response.
    assert resp.headers.get("X-Auth-Status") == "jwt-dropped-to-anon", (
        f"Expected X-Auth-Status header on bad-JWT response; "
        f"got headers={dict(resp.headers)!r}, status={resp.status_code}"
    )
    # RFC 6750 §3 — the WWW-Authenticate header tells the client *why*
    # the JWT was rejected so it can prompt re-auth instead of treating
    # the anon body as canonical.
    assert resp.headers.get("WWW-Authenticate", "").startswith(
        'Bearer error="invalid_token"'
    ), (
        f"Expected RFC 6750 WWW-Authenticate on bad-JWT response; "
        f"got {resp.headers.get('WWW-Authenticate')!r}"
    )
    # Cloudflare cache-poisoning mitigation — an anonymous response with a
    # drop marker must NEVER be cached and re-served to another caller.
    assert resp.headers.get("Cache-Control") == "private, no-store", (
        f"Expected Cache-Control: private, no-store on bad-JWT response; "
        f"got {resp.headers.get('Cache-Control')!r}"
    )


@patch("website.api.auth._get_jwt_secret", return_value=TEST_SECRET)
def test_response_has_no_x_auth_status_on_anonymous(_secret) -> None:
    """The header MUST NOT appear on responses where auth wasn't attempted
    or where it succeeded — only the explicit drop path sets it."""
    from website.app import create_app

    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/graph")  # No Authorization header at all
    assert "X-Auth-Status" not in resp.headers, (
        f"Header must not appear on legitimate anon. Got: {dict(resp.headers)!r}"
    )
