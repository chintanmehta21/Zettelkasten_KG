"""Server-side Google native (ID-token) sign-in flow.

PR #135 — Option B. The teal button keeps a full-page redirect (identical UX
to the legacy ``signInWithOAuth`` flow) but the OAuth round-trip now stays on
our own domain so the Google consent screen shows "Zettelkasten /
zettelkasten.in" instead of ``<ref>.supabase.co``.

Three routes / behaviours are covered here:

* ``GET /api/auth/config`` gains a ``google_client_id`` field (the frontend
  feature-flag: empty ⇒ keep the legacy hosted flow).
* ``GET /api/auth/google/start`` sets a SameSite=Lax state cookie and 302s to
  Google's auth endpoint with our callback as ``redirect_uri``.
* ``GET /api/auth/google/callback`` enforces the state-cookie CSRF check,
  exchanges the code server-side (mocked here), and serves a no-store handoff
  page that calls ``supabase.auth.signInWithIdToken``.

All tests are pure server-side (no live Google/Supabase) — the token exchange
is monkeypatched at ``routes._exchange_google_code``.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from website.api import routes
from website.app import create_app


CLIENT_ID = "test-client-id.apps.googleusercontent.com"
CLIENT_SECRET = "test-secret-value"
# Reused Nexus YouTube OAuth client (operator chose to reuse it rather than mint
# a new client). The backend resolves GOOGLE_OAUTH_* first, then NEXUS_YOUTUBE_*.
NEXUS_CLIENT_ID = "nexus-yt-client.apps.googleusercontent.com"
NEXUS_CLIENT_SECRET = "nexus-yt-secret-value"
BASE_URL = "https://zettelkasten.test"


def _make_client(monkeypatch, *, configured: bool = True) -> TestClient:
    routes._rate_store.clear()
    # Isolate from any ambient Nexus YouTube creds so the resolver is
    # deterministic for the GOOGLE_OAUTH_*-only cases below.
    monkeypatch.delenv("NEXUS_YOUTUBE_CLIENT_ID", raising=False)
    monkeypatch.delenv("NEXUS_YOUTUBE_CLIENT_SECRET", raising=False)
    if configured:
        monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", CLIENT_ID)
        monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", CLIENT_SECRET)
        monkeypatch.setenv("PUBLIC_BASE_URL", BASE_URL)
    else:
        monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
        monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    app = create_app()
    # follow_redirects=False so we can assert the 302 Location to Google.
    # base_url https so the httpx cookie jar persists the Secure state cookie
    # (over http it would silently drop it) and request.scheme is https.
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


# --------------------------------------------------------------------------- #
# /api/auth/config — feature flag                                             #
# --------------------------------------------------------------------------- #

class TestAuthConfigGoogleClientId:
    def test_config_exposes_client_id_when_set(self, monkeypatch) -> None:
        client = _make_client(monkeypatch, configured=True)
        body = client.get("/api/auth/config").json()
        assert body["google_client_id"] == CLIENT_ID

    def test_config_blank_client_id_when_unset(self, monkeypatch) -> None:
        client = _make_client(monkeypatch, configured=False)
        body = client.get("/api/auth/config").json()
        # Field always present (stable wire shape) but empty ⇒ frontend keeps
        # the legacy hosted flow. Must never leak a secret.
        assert body.get("google_client_id", "") == ""
        assert "google_client_secret" not in body
        assert CLIENT_SECRET not in client.get("/api/auth/config").text


# --------------------------------------------------------------------------- #
# /api/auth/google/start — redirect to Google                                 #
# --------------------------------------------------------------------------- #

class TestGoogleStart:
    def test_start_redirects_to_google_auth_endpoint(self, monkeypatch) -> None:
        client = _make_client(monkeypatch)
        resp = client.get("/api/auth/google/start", params={"return_to": "/home"})
        assert resp.status_code in (302, 307)
        loc = resp.headers["location"]
        parsed = urlparse(loc)
        assert parsed.scheme == "https"
        assert parsed.netloc == "accounts.google.com"
        assert parsed.path == "/o/oauth2/v2/auth"

    def test_start_includes_required_oauth_params(self, monkeypatch) -> None:
        client = _make_client(monkeypatch)
        resp = client.get("/api/auth/google/start", params={"return_to": "/home"})
        q = parse_qs(urlparse(resp.headers["location"]).query)
        assert q["client_id"] == [CLIENT_ID]
        assert q["response_type"] == ["code"]
        assert q["redirect_uri"] == [f"{BASE_URL}/api/auth/google/callback"]
        # OIDC scopes required for an id_token + profile.
        scope = q["scope"][0]
        for token in ("openid", "email", "profile"):
            assert token in scope
        assert q["state"][0]  # non-empty CSRF token

    def test_start_sets_state_cookie(self, monkeypatch) -> None:
        client = _make_client(monkeypatch)
        resp = client.get("/api/auth/google/start", params={"return_to": "/home"})
        set_cookie = resp.headers.get("set-cookie", "")
        assert "g_oauth_state" in set_cookie
        # Lax so the cookie survives Google's top-level redirect back to us;
        # HttpOnly so client JS can't read the CSRF token.
        assert "samesite=lax" in set_cookie.lower()
        assert "httponly" in set_cookie.lower()

    def test_start_state_param_matches_cookie(self, monkeypatch) -> None:
        client = _make_client(monkeypatch)
        resp = client.get("/api/auth/google/start", params={"return_to": "/home"})
        url_state = parse_qs(urlparse(resp.headers["location"]).query)["state"][0]
        cookie_state = client.cookies.get("g_oauth_state")
        assert cookie_state == url_state

    def test_start_rejects_open_redirect_return_to(self, monkeypatch) -> None:
        client = _make_client(monkeypatch)
        resp = client.get(
            "/api/auth/google/start",
            params={"return_to": "https://evil.example/phish"},
        )
        # Still redirects to Google, but the unsafe return_to must not be
        # retained — it is coerced to the default and never echoed to Google.
        assert resp.status_code in (302, 307)
        assert "evil.example" not in resp.headers["location"]

    def test_start_not_configured_is_harmless(self, monkeypatch) -> None:
        client = _make_client(monkeypatch, configured=False)
        resp = client.get("/api/auth/google/start", params={"return_to": "/home"})
        # Defensive: a stray hit when the flow is disabled must NOT 500 and must
        # never redirect to Google.
        assert resp.status_code in (302, 307, 404, 503)
        if resp.status_code in (302, 307):
            assert "accounts.google.com" not in resp.headers["location"]


# --------------------------------------------------------------------------- #
# /api/auth/google/callback — CSRF + exchange + handoff                       #
# --------------------------------------------------------------------------- #

class TestGoogleCallback:
    def test_callback_missing_state_cookie_is_rejected(self, monkeypatch) -> None:
        client = _make_client(monkeypatch)
        resp = client.get(
            "/api/auth/google/callback",
            params={"code": "abc", "state": "anything"},
        )
        assert resp.status_code == 400

    def test_callback_mismatched_state_is_rejected(self, monkeypatch) -> None:
        client = _make_client(monkeypatch)
        client.cookies.set("g_oauth_state", "cookie-state")
        resp = client.get(
            "/api/auth/google/callback",
            params={"code": "abc", "state": "url-state-different"},
        )
        assert resp.status_code == 400

    def test_callback_google_error_is_handled(self, monkeypatch) -> None:
        client = _make_client(monkeypatch)
        client.cookies.set("g_oauth_state", "s1")
        resp = client.get(
            "/api/auth/google/callback",
            params={"state": "s1", "error": "access_denied"},
        )
        # User declined consent — must degrade gracefully, never 500.
        assert resp.status_code in (302, 307, 400)

    def test_callback_exchanges_and_serves_handoff(self, monkeypatch) -> None:
        captured = {}

        async def _fake_exchange(code: str, redirect_uri: str) -> dict:
            captured["code"] = code
            captured["redirect_uri"] = redirect_uri
            return {"id_token": "FAKE.GOOGLE.IDTOKEN", "token_type": "Bearer"}

        monkeypatch.setattr(routes, "_exchange_google_code", _fake_exchange)

        client = _make_client(monkeypatch)
        client.cookies.set("g_oauth_state", "s2")
        client.cookies.set("g_oauth_return", "/home")
        resp = client.get(
            "/api/auth/google/callback",
            params={"code": "auth-code-123", "state": "s2"},
        )
        assert resp.status_code == 200
        assert captured["code"] == "auth-code-123"
        assert captured["redirect_uri"] == f"{BASE_URL}/api/auth/google/callback"
        body = resp.text
        # Handoff page drives the client-side native sign-in.
        assert "signInWithIdToken" in body
        assert "FAKE.GOOGLE.IDTOKEN" in body
        # Never cache an identity-bearing page.
        assert "no-store" in resp.headers.get("cache-control", "").lower()

    def test_callback_consumes_state_cookie(self, monkeypatch) -> None:
        async def _fake_exchange(code: str, redirect_uri: str) -> dict:
            return {"id_token": "FAKE.GOOGLE.IDTOKEN"}

        monkeypatch.setattr(routes, "_exchange_google_code", _fake_exchange)
        client = _make_client(monkeypatch)
        client.cookies.set("g_oauth_state", "s3")
        resp = client.get(
            "/api/auth/google/callback",
            params={"code": "c", "state": "s3"},
        )
        # The one-time state cookie must be cleared after use (no replay).
        set_cookie = resp.headers.get("set-cookie", "")
        assert "g_oauth_state" in set_cookie
        assert ("max-age=0" in set_cookie.lower()) or ("expires=" in set_cookie.lower())


# --------------------------------------------------------------------------- #
# Credential reuse — fall back to the existing Nexus YouTube OAuth client.     #
# --------------------------------------------------------------------------- #

def _make_nexus_client(monkeypatch) -> TestClient:
    """App configured with ONLY the Nexus YouTube creds (no dedicated vars)."""
    routes._rate_store.clear()
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("NEXUS_YOUTUBE_CLIENT_ID", NEXUS_CLIENT_ID)
    monkeypatch.setenv("NEXUS_YOUTUBE_CLIENT_SECRET", NEXUS_CLIENT_SECRET)
    monkeypatch.setenv("PUBLIC_BASE_URL", BASE_URL)
    return TestClient(create_app(), base_url="https://testserver", follow_redirects=False)


class TestNexusYoutubeCredentialReuse:
    def test_config_falls_back_to_nexus_youtube_client_id(self, monkeypatch) -> None:
        client = _make_nexus_client(monkeypatch)
        body = client.get("/api/auth/config").json()
        assert body["google_client_id"] == NEXUS_CLIENT_ID
        # The secret must never be in the public config under any name.
        assert NEXUS_CLIENT_SECRET not in client.get("/api/auth/config").text

    def test_start_works_with_nexus_youtube_creds(self, monkeypatch) -> None:
        client = _make_nexus_client(monkeypatch)
        resp = client.get("/api/auth/google/start", params={"return_to": "/home"})
        assert resp.status_code in (302, 307)
        q = parse_qs(urlparse(resp.headers["location"]).query)
        assert q["client_id"] == [NEXUS_CLIENT_ID]
        assert q["redirect_uri"] == [f"{BASE_URL}/api/auth/google/callback"]

    def test_dedicated_google_client_takes_precedence(self, monkeypatch) -> None:
        # Both present ⇒ explicit GOOGLE_OAUTH_* overrides the shared Nexus client.
        routes._rate_store.clear()
        monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", CLIENT_ID)
        monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", CLIENT_SECRET)
        monkeypatch.setenv("NEXUS_YOUTUBE_CLIENT_ID", NEXUS_CLIENT_ID)
        monkeypatch.setenv("NEXUS_YOUTUBE_CLIENT_SECRET", NEXUS_CLIENT_SECRET)
        monkeypatch.setenv("PUBLIC_BASE_URL", BASE_URL)
        client = TestClient(create_app(), base_url="https://testserver", follow_redirects=False)
        body = client.get("/api/auth/config").json()
        assert body["google_client_id"] == CLIENT_ID
