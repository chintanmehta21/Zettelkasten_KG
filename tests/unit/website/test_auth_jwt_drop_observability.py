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
        r
        for r in caplog.records
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
        r
        for r in caplog.records
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
        resp = client.get("/probe", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_sub"] == "550e8400-e29b-41d4-a716-446655440000"
    assert body["auth_status"] is None
    drop_warnings = [
        r
        for r in caplog.records
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


# ── 5. Token-missing-but-expected path (post-Prajeet 2026-05-26 03:41 UTC) ──
#
# Second Prajeet stranding — a request landed under Zoro NOT because the
# JWT was rejected, but because no JWT was sent at all. Root cause: the
# desktop landing form submits before auth-core.js finishes RESTORE; the
# token-missing-when-expected case is invisible to the §5.2 fix (which
# only catches sent-but-invalid JWTs). This test class pins the
# observability contract for that gap.


@patch("website.api.auth._get_jwt_secret", return_value=TEST_SECRET)
def test_zk_auth_intent_header_marks_token_missing_expected(_secret) -> None:
    """When the client signals ``Zk-Auth-Intent: bearer`` but no
    Authorization is attached, ``get_optional_user`` must mark the request
    as ``token-missing-but-expected`` so the response surfaces
    ``X-Auth-Status``. RFC 6648-compliant header naming (no X- prefix)."""
    client = TestClient(_build_probe_app())
    resp = client.get("/probe", headers={"Zk-Auth-Intent": "bearer"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_sub"] is None
    assert body["auth_status"] == "token-missing-but-expected"


@patch("website.api.auth._get_jwt_secret", return_value=TEST_SECRET)
def test_zk_auth_intent_emits_warning_log(_secret, caplog) -> None:
    """The missing-token branch MUST log a structured WARNING on the
    ``website.api.auth`` logger so operators can grep droplet stdout for
    expected-but-absent auth — mirrors the JWT-drop warning channel."""
    client = TestClient(_build_probe_app())
    with caplog.at_level(logging.WARNING, logger="website.api.auth"):
        resp = client.get("/probe", headers={"Zk-Auth-Intent": "bearer"})
    assert resp.status_code == 200
    warnings = [
        r
        for r in caplog.records
        if r.name == "website.api.auth" and r.levelno == logging.WARNING
    ]
    assert len(warnings) == 1, (
        f"Expected exactly 1 token-missing warning; got {len(warnings)}: "
        f"{[r.message for r in warnings]!r}"
    )
    msg = warnings[0].getMessage().lower()
    assert "expected" in msg and "missing" in msg, (
        f"Warning must name the failure mode (expected/missing): {msg!r}"
    )


@patch("website.api.auth._get_jwt_secret", return_value=TEST_SECRET)
def test_no_authorization_no_hint_stays_silent(_secret, caplog) -> None:
    """Legitimate anonymous traffic (no Authorization, no Zk-Auth-Intent)
    must NOT emit a warning OR set request.state.auth_status. This is the
    backstop against turning every anon visitor into log noise."""
    client = TestClient(_build_probe_app())
    with caplog.at_level(logging.WARNING, logger="website.api.auth"):
        resp = client.get("/probe")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_sub"] is None
    assert body["auth_status"] is None, (
        f"Legitimate anon must NOT set auth_status. Got: {body!r}"
    )
    warnings = [
        r
        for r in caplog.records
        if r.name == "website.api.auth" and r.levelno == logging.WARNING
    ]
    assert not warnings, (
        f"Legitimate anon must produce zero WARNINGs. Got: {[r.message for r in warnings]!r}"
    )


@patch("website.api.auth._get_jwt_secret", return_value=TEST_SECRET)
def test_token_missing_response_has_no_www_authenticate(_secret) -> None:
    """WWW-Authenticate carries RFC 6750 ``invalid_token`` semantics — only
    valid when a JWT was actually sent and rejected. For the
    token-missing-but-expected case there is no token to call invalid, so
    the response MUST NOT include WWW-Authenticate (it would misdirect
    clients into thinking we received a bad token). The X-Auth-Status
    and Cache-Control: private, no-store headers still apply."""
    from website.app import create_app

    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/graph", headers={"Zk-Auth-Intent": "bearer"})
    assert resp.headers.get("X-Auth-Status") == "token-missing-but-expected", (
        f"Expected X-Auth-Status on token-missing request; "
        f"got headers={dict(resp.headers)!r}, status={resp.status_code}"
    )
    assert "WWW-Authenticate" not in resp.headers, (
        f"WWW-Authenticate must not appear when no token was actually sent. "
        f"Got: {resp.headers.get('WWW-Authenticate')!r}"
    )
    # Cloudflare cache-poisoning mitigation — applies to every auth_status
    # value, not just the JWT-drop case.
    assert resp.headers.get("Cache-Control") == "private, no-store", (
        f"Expected Cache-Control: private, no-store on degraded-anon response; "
        f"got {resp.headers.get('Cache-Control')!r}"
    )


@patch("website.api.auth._get_jwt_secret", return_value=TEST_SECRET)
def test_authorization_present_ignores_intent_hint(_secret) -> None:
    """When BOTH Authorization (valid JWT) AND Zk-Auth-Intent are sent, the
    JWT path wins and the hint is ignored — happy path must stay clean."""
    client = TestClient(_build_probe_app())
    token = _make_jwt()
    resp = client.get(
        "/probe",
        headers={
            "Authorization": f"Bearer {token}",
            "Zk-Auth-Intent": "bearer",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_sub"] == "550e8400-e29b-41d4-a716-446655440000"
    assert body["auth_status"] is None, (
        f"Valid JWT path must not set auth_status even when hint present. Got: {body!r}"
    )


# ── 6. Server-side heuristic: spa-inferred-anon ───────────────────────────
#
# When the client didn't send Zk-Auth-Intent (likely cause: auth-core.js
# itself crashed before installing the zkFetch wrapper, or browserCache shim
# is gone), the backend falls back to inferring "SPA-shaped anonymous" from
# the request signature: same-origin Sec-Fetch-Site + frontend Idempotency-Key
# shape + real-browser UA. Lower confidence than the explicit hint — it CAN
# false-positive on a first-time anonymous visitor using the landing form —
# but it's the only signal we have when the client side itself is broken.


SPA_HEURISTIC_HEADERS = {
    "Sec-Fetch-Site": "same-origin",
    "Idempotency-Key": "zettel:landing:1779766878937:abc123xyz",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Firefox/151.0",
}


@patch("website.api.auth._get_jwt_secret", return_value=TEST_SECRET)
def test_spa_heuristic_fires_on_full_signature(_secret) -> None:
    """All three SPA signature signals present + no Authorization + no
    Zk-Auth-Intent → ``spa-inferred`` auth_status. Catches the case where
    the client-side init itself failed (no auth-core.js, no browserCache,
    so no explicit hint either)."""
    client = TestClient(_build_probe_app())
    resp = client.get("/probe", headers=SPA_HEURISTIC_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["auth_status"] == "spa-inferred"


@patch("website.api.auth._get_jwt_secret", return_value=TEST_SECRET)
def test_spa_heuristic_skipped_when_intent_present(_secret) -> None:
    """When ``Zk-Auth-Intent`` is explicitly set, the high-confidence
    ``token-missing-but-expected`` branch must win — the heuristic must NOT
    overwrite it with the lower-confidence ``spa-inferred`` value."""
    client = TestClient(_build_probe_app())
    resp = client.get(
        "/probe",
        headers={**SPA_HEURISTIC_HEADERS, "Zk-Auth-Intent": "bearer"},
    )
    assert resp.status_code == 200
    assert resp.json()["auth_status"] == "token-missing-but-expected", (
        "When client explicitly hints intent, the high-confidence value "
        "must win over the lower-confidence server heuristic."
    )


@patch("website.api.auth._get_jwt_secret", return_value=TEST_SECRET)
def test_spa_heuristic_skipped_for_non_browser_ua(_secret) -> None:
    """A real browser UA is required — curl / requests-lib / bots must NOT
    trip the heuristic (false-positive noise from API explorers)."""
    client = TestClient(_build_probe_app())
    for ua in [
        "curl/8.5.0",
        "python-requests/2.31.0",
        "wget/1.21",
        "Googlebot/2.1",
        "",  # absent UA also fails the real-browser check
    ]:
        headers = {**SPA_HEURISTIC_HEADERS, "User-Agent": ua}
        resp = client.get("/probe", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["auth_status"] is None, (
            f"Non-browser UA {ua!r} must NOT trip the SPA heuristic. "
            f"Got: {resp.json()!r}"
        )


@patch("website.api.auth._get_jwt_secret", return_value=TEST_SECRET)
def test_spa_heuristic_skipped_for_cross_origin(_secret) -> None:
    """Cross-origin requests cannot be SPA-init failures of OUR SPA — they
    must not trip the heuristic."""
    client = TestClient(_build_probe_app())
    headers = {**SPA_HEURISTIC_HEADERS, "Sec-Fetch-Site": "cross-site"}
    resp = client.get("/probe", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["auth_status"] is None


@patch("website.api.auth._get_jwt_secret", return_value=TEST_SECRET)
def test_spa_heuristic_skipped_for_non_spa_idem_key(_secret) -> None:
    """Idempotency-Key without the frontend op_id shape (``zettel:<surface>:
    <ms>:<rand>``) must not trip the heuristic — only the SPA emits this
    exact pattern via add_zettel_api.js::makeActionId."""
    client = TestClient(_build_probe_app())
    for idem_key in [
        "",  # absent
        "user-provided-key-12345",  # caller-chosen
        "zettel:foo",  # truncated — fewer than 3 colons
        "POST-/api/zettels/add-2026-05-26",  # generic
    ]:
        headers = {**SPA_HEURISTIC_HEADERS, "Idempotency-Key": idem_key}
        resp = client.get("/probe", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["auth_status"] is None, (
            f"Non-SPA Idempotency-Key {idem_key!r} must not trip heuristic. "
            f"Got: {resp.json()!r}"
        )


@patch("website.api.auth._get_jwt_secret", return_value=TEST_SECRET)
def test_spa_inferred_response_has_no_www_authenticate(_secret) -> None:
    """Same RFC 6750 rule as token-missing-but-expected: no JWT was sent,
    so WWW-Authenticate would misdirect. X-Auth-Status + Cache-Control
    still apply."""
    from website.app import create_app

    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/graph", headers=SPA_HEURISTIC_HEADERS)
    assert resp.headers.get("X-Auth-Status") == "spa-inferred"
    assert "WWW-Authenticate" not in resp.headers
    assert resp.headers.get("Cache-Control") == "private, no-store"


# ── 7. _compute_auth_intent helper (persistence into core.operations) ─────


class _FakeRequest:
    """Minimal Request stub for _compute_auth_intent unit tests — only the
    ``state`` attribute matters."""

    class _State:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    def __init__(self, auth_status: str | None = None):
        self.state = self._State()
        if auth_status is not None:
            self.state.auth_status = auth_status


def test_compute_auth_intent_returns_ok_for_authenticated_request() -> None:
    """Authenticated request (user dict present, no auth_status tag) →
    persisted ``auth_intent='ok'`` so we can grep succeeded ops by the
    legit-authenticated pathway."""
    from website.api.zettels_routes import _compute_auth_intent

    user = {"sub": "550e8400-e29b-41d4-a716-446655440000", "email": "u@x.com"}
    assert _compute_auth_intent(_FakeRequest(), user) == "ok"


def test_compute_auth_intent_returns_anon_for_legit_anonymous() -> None:
    """No user, no auth_status tag → persisted ``auth_intent='anon'``.
    Distinguishes intentional anonymous visitors from degraded-auth cases."""
    from website.api.zettels_routes import _compute_auth_intent

    assert _compute_auth_intent(_FakeRequest(), None) == "anon"


def test_compute_auth_intent_passes_through_auth_status_token_missing() -> None:
    """``token-missing-but-expected`` tag set by get_optional_user (client
    sent Zk-Auth-Intent hint) must persist verbatim as auth_intent so
    forensic queries can join the request to its observability tier."""
    from website.api.zettels_routes import _compute_auth_intent

    req = _FakeRequest(auth_status="token-missing-but-expected")
    assert _compute_auth_intent(req, None) == "token-missing-but-expected"


def test_compute_auth_intent_passes_through_jwt_dropped() -> None:
    """``jwt-dropped-to-anon`` tag (JWT sent but rejected) persists too —
    distinguishes JWT-invalid from token-missing in the operations log."""
    from website.api.zettels_routes import _compute_auth_intent

    req = _FakeRequest(auth_status="jwt-dropped-to-anon")
    assert _compute_auth_intent(req, None) == "jwt-dropped-to-anon"


def test_compute_auth_intent_passes_through_spa_inferred() -> None:
    """``spa-inferred`` tag (server-side heuristic) persists too —
    lower-confidence than the explicit hint but still queryable."""
    from website.api.zettels_routes import _compute_auth_intent

    req = _FakeRequest(auth_status="spa-inferred")
    assert _compute_auth_intent(req, None) == "spa-inferred"


def test_compute_auth_intent_auth_status_wins_over_user() -> None:
    """If somehow BOTH user is present AND auth_status is tagged (defensive
    case — shouldn't happen in practice), prefer the tag so we don't lose
    the forensic signal. auth_status semantics are stronger than presence."""
    from website.api.zettels_routes import _compute_auth_intent

    user = {"sub": "550e8400-e29b-41d4-a716-446655440000"}
    req = _FakeRequest(auth_status="token-missing-but-expected")
    assert _compute_auth_intent(req, user) == "token-missing-but-expected"
