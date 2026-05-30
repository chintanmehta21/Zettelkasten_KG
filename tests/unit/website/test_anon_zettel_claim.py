"""Unit tests for the anon → user zettel claim backend (Item 6).

Pure-logic + endpoint coverage with all I/O mocked (no DB, no Supabase, no
Gemini). The live end-to-end behaviour (first-claim-wins, 24h window, BOLA,
quota cap against a real DB) is covered by
``tests/integration/v2/test_anon_zettel_claim_v2.py`` (marked live).

Covered here:
  1. Claim quota loop caps at remaining and NEVER lets a 402 reach the client
     (require_entitlement raises 402 on the 2nd candidate → claimed=1,
     capped=True).
  2. ``_check_claim_rate_limit`` allows 3 then blocks (sliding window).
  3. ``AnonSessionCookieMiddleware`` sets ``zk_anon_sid`` (HttpOnly) on an
     un-authenticated response, NOT on an authed response, and NOT when the
     cookie is already present.
  4. Absent / malformed cookie → 200 ``{claimed: 0, capped: false}`` (no leak),
     and anonymous caller → 401.
"""
from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from website.api._middleware import AnonSessionCookieMiddleware
from website.api.auth import get_optional_user
from website.app import create_app


@pytest.fixture(autouse=True)
def _reset_claim_rate_limiter():
    """The claim limiter keys on the client IP via a module-level store; every
    TestClient request presents the same host ("testclient"), so without a
    per-test reset the 3/60s budget leaks across tests and later tests 429.
    Clear it before AND after each test."""
    from website.api import zettels_routes as zr

    zr._CLAIM_RATE_STORE.clear()
    yield
    zr._CLAIM_RATE_STORE.clear()


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _StubRepo:
    """Stub ContentRepository: deterministic peek + record commit args."""

    def __init__(self, candidates):
        self._candidates = candidates
        self.committed_ids = None
        self.commit_calls = 0

    def peek_claimable_anon_zettels(self, new_user, anon_sid):
        return list(self._candidates)

    def commit_anon_claim(self, new_user, anon_sid, canonical_ids):
        self.commit_calls += 1
        self.committed_ids = list(canonical_ids)
        return len(canonical_ids)


def _candidate():
    return {"workspace_zettel_id": str(uuid4()), "canonical_zettel_id": str(uuid4())}


def _authed_client(user_sub: str | None = None) -> tuple[TestClient, str]:
    app = create_app()
    sub = user_sub or str(uuid4())

    async def _fake_user():
        return {"sub": sub}

    app.dependency_overrides[get_optional_user] = _fake_user
    return TestClient(app), sub


# ---------------------------------------------------------------------------
# 1. Quota loop caps at remaining + never surfaces 402
# ---------------------------------------------------------------------------


def test_claim_quota_loop_caps_and_never_raises_402():
    """3 candidates, quota exhausts on the 2nd require_entitlement call. The
    loop must STOP (cap at 1 affordable), commit ONLY that one canonical id,
    and the endpoint must return 200 with capped=True — the 402 NEVER reaches
    the client."""
    client, _sub = _authed_client()
    candidates = [_candidate(), _candidate(), _candidate()]
    repo = _StubRepo(candidates)

    call_count = {"n": 0}

    async def _fake_require_entitlement(meter, user, *, action_id=None):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise HTTPException(status_code=402, detail={"code": "quota_exhausted"})
        return None

    with _patch_repo(repo), patch(
        "website.api.zettels_routes.require_entitlement",
        side_effect=_fake_require_entitlement,
    ):
        r = client.post(
            "/api/zettels/claim-anon-session",
            headers={"Authorization": "Bearer x"},
            cookies={"zk_anon_sid": str(uuid4())},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["claimed"] == 1
    assert body["capped"] is True
    # Only the first (affordable) canonical id was committed.
    assert repo.commit_calls == 1
    assert len(repo.committed_ids) == 1
    assert repo.committed_ids[0] == candidates[0]["canonical_zettel_id"]


def test_claim_all_affordable_not_capped():
    """When quota covers every candidate, capped=False and all ids committed."""
    client, _sub = _authed_client()
    candidates = [_candidate(), _candidate()]
    repo = _StubRepo(candidates)

    async def _always_ok(meter, user, *, action_id=None):
        return None

    with _patch_repo(repo), patch(
        "website.api.zettels_routes.require_entitlement", side_effect=_always_ok
    ):
        r = client.post(
            "/api/zettels/claim-anon-session",
            headers={"Authorization": "Bearer x"},
            cookies={"zk_anon_sid": str(uuid4())},
        )

    body = r.json()
    assert r.status_code == 200
    assert body["claimed"] == 2
    assert body["capped"] is False
    assert len(repo.committed_ids) == 2


def test_claim_passes_new_user_sub_into_entitlement_gate():
    """The quota gate must be called with {'sub': <new_user_sub>} so it
    actually consumes (require_entitlement is a no-op when user is None)."""
    client, sub = _authed_client()
    candidates = [_candidate()]
    repo = _StubRepo(candidates)
    seen = {}

    async def _capture(meter, user, *, action_id=None):
        seen["user"] = user
        seen["action_id"] = action_id
        return None

    with _patch_repo(repo), patch(
        "website.api.zettels_routes.require_entitlement", side_effect=_capture
    ):
        r = client.post(
            "/api/zettels/claim-anon-session",
            headers={"Authorization": "Bearer x"},
            cookies={"zk_anon_sid": str(uuid4())},
        )

    assert r.status_code == 200
    assert seen["user"] == {"sub": sub}
    assert seen["action_id"].startswith("claim-")


# ---------------------------------------------------------------------------
# 2. Rate-limit helper
# ---------------------------------------------------------------------------


def test_check_claim_rate_limit_allows_3_then_blocks():
    from website.api import zettels_routes as zr

    ip = f"203.0.113.{uuid4().int % 250}"
    zr._CLAIM_RATE_STORE.pop(ip, None)
    assert zr._check_claim_rate_limit(ip) is True
    assert zr._check_claim_rate_limit(ip) is True
    assert zr._check_claim_rate_limit(ip) is True
    # 4th within the window is blocked.
    assert zr._check_claim_rate_limit(ip) is False
    zr._CLAIM_RATE_STORE.pop(ip, None)


def test_claim_endpoint_rate_limited_returns_429():
    client, _sub = _authed_client()
    from website.api import zettels_routes as zr

    candidates = [_candidate()]
    repo = _StubRepo(candidates)

    async def _ok(meter, user, *, action_id=None):
        return None

    # Pre-fill the window so the very next call is rejected. Use the IP the
    # TestClient presents (testserver → request.client.host == "testclient").
    with _patch_repo(repo), patch(
        "website.api.zettels_routes.require_entitlement", side_effect=_ok
    ), patch.object(zr, "_check_claim_rate_limit", return_value=False):
        r = client.post(
            "/api/zettels/claim-anon-session",
            headers={"Authorization": "Bearer x"},
            cookies={"zk_anon_sid": str(uuid4())},
        )
    assert r.status_code == 429


# ---------------------------------------------------------------------------
# 3. Cookie middleware
# ---------------------------------------------------------------------------


def _cookie_app() -> FastAPI:
    """Minimal app wired with only AnonSessionCookieMiddleware, plus a route
    that can mark the request authenticated (mirrors what get_current_user
    does) and echo the same-request request.state.anon_sid."""
    app = FastAPI()

    @app.get("/anon")
    async def anon_route(request: Request):
        return JSONResponse({"state_sid": getattr(request.state, "anon_sid", None)})

    @app.get("/authed")
    async def authed_route(request: Request):
        request.state.authenticated = True
        return JSONResponse({"ok": True})

    app.add_middleware(AnonSessionCookieMiddleware)
    return app


def _set_cookie_for(resp, name: str):
    """Return the raw Set-Cookie header string for `name`, or None."""
    for hk, hv in resp.headers.raw if hasattr(resp.headers, "raw") else []:
        if hk.decode().lower() == "set-cookie" and hv.decode().startswith(f"{name}="):
            return hv.decode()
    # Fallback for httpx Response: scan multi-valued header.
    raw = resp.headers.get_list("set-cookie") if hasattr(resp.headers, "get_list") else []
    for v in raw:
        if v.startswith(f"{name}="):
            return v
    return None


def test_cookie_set_on_anon_response_httponly():
    app = _cookie_app()
    with TestClient(app) as client:
        r = client.get("/anon")
    assert r.status_code == 200
    sc = _set_cookie_for(r, "zk_anon_sid")
    assert sc is not None, f"zk_anon_sid not set; headers={r.headers}"
    low = sc.lower()
    assert "httponly" in low
    assert "secure" in low
    assert "samesite=lax" in low
    assert "path=/" in low
    assert "max-age=2592000" in low
    # Same-request state was populated so capture can tag immediately.
    assert r.json()["state_sid"]


def test_cookie_not_set_on_authed_response():
    app = _cookie_app()
    with TestClient(app) as client:
        r = client.get("/authed")
    assert r.status_code == 200
    assert _set_cookie_for(r, "zk_anon_sid") is None


def test_cookie_not_set_when_already_present():
    app = _cookie_app()
    existing = str(uuid4())
    with TestClient(app) as client:
        r = client.get("/anon", cookies={"zk_anon_sid": existing})
    assert r.status_code == 200
    # No re-issue when the request already carries the cookie.
    assert _set_cookie_for(r, "zk_anon_sid") is None
    # And request.state was NOT overwritten (no mint on this request).
    assert r.json()["state_sid"] is None


# ---------------------------------------------------------------------------
# 4. Absent/invalid cookie + auth gating
# ---------------------------------------------------------------------------


def test_claim_absent_cookie_returns_zero():
    client, _sub = _authed_client()
    repo = _StubRepo([_candidate()])

    async def _ok(meter, user, *, action_id=None):
        return None

    with _patch_repo(repo), patch(
        "website.api.zettels_routes.require_entitlement", side_effect=_ok
    ):
        r = client.post(
            "/api/zettels/claim-anon-session",
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 200
    assert r.json() == {"claimed": 0, "capped": False}
    # Repo was never consulted — no cookie, nothing to claim.
    assert repo.commit_calls == 0


def test_claim_invalid_cookie_returns_zero():
    client, _sub = _authed_client()
    repo = _StubRepo([_candidate()])

    async def _ok(meter, user, *, action_id=None):
        return None

    with _patch_repo(repo), patch(
        "website.api.zettels_routes.require_entitlement", side_effect=_ok
    ):
        r = client.post(
            "/api/zettels/claim-anon-session",
            headers={"Authorization": "Bearer x"},
            cookies={"zk_anon_sid": "not-a-uuid"},
        )
    assert r.status_code == 200
    assert r.json() == {"claimed": 0, "capped": False}
    assert repo.commit_calls == 0


def test_claim_unauthenticated_returns_401():
    """Anonymous caller (no auth) → 401: nothing to claim INTO."""
    client = TestClient(create_app())
    r = client.post(
        "/api/zettels/claim-anon-session",
        cookies={"zk_anon_sid": str(uuid4())},
    )
    assert r.status_code == 401


def test_claim_empty_candidates_returns_zero():
    client, _sub = _authed_client()
    repo = _StubRepo([])  # session valid but nothing claimable

    async def _ok(meter, user, *, action_id=None):
        return None

    with _patch_repo(repo), patch(
        "website.api.zettels_routes.require_entitlement", side_effect=_ok
    ):
        r = client.post(
            "/api/zettels/claim-anon-session",
            headers={"Authorization": "Bearer x"},
            cookies={"zk_anon_sid": str(uuid4())},
        )
    assert r.status_code == 200
    assert r.json() == {"claimed": 0, "capped": False}
    assert repo.commit_calls == 0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _patch_repo(repo):
    """Patch the ContentRepository symbol imported lazily inside the claim
    handler. The handler does ``from ...content_repository import
    ContentRepository`` at call time, so we patch it at its source module."""
    return patch(
        "website.core.supabase_v2.repositories.content_repository.ContentRepository",
        return_value=repo,
    )
