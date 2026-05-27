"""Unit tests for /api/profile/stats route - mocked auth + mocked runner.

Covers the route's HTTP-level concerns:
  * 200 happy path with ETag/Cache-Control/x-stats-cache headers
  * 304 short-circuit when If-None-Match matches the runner's etag
  * 503 when STATS_TAB_ENABLED=false (kill switch)
  * 503 when caller not in STATS_TAB_ALLOWLIST
  * 429 when per-user rate limit is exceeded
"""
from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from website.api.auth import get_current_user
from website.api.profile_routes import router as profile_router


_FAKE_PROFILE_SUB = "00000000-0000-0000-0000-000000000001"
_FAKE_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000099")


def _stub_user(sub: str = _FAKE_PROFILE_SUB) -> dict:
    return {"sub": sub, "email": "t@test.local"}


def _runner_payload() -> dict:
    """Minimal StatsResponse-like dict with _meta etag/cache_hit."""
    return {
        "meta": {
            "workspace_id": "ws",
            "computed_at": "2026-05-27T10:00:00+00:00",
            "schema_version": 1,
        },
        "main_board": {},
        "general": {},
        "zettel": {},
        "kasten": {},
        "domain": {},
        "activity": {},
        "graph": {},
        "_meta": {"etag": "abc123", "cache_hit": False},
    }


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset module-level rate-limit + singleflight state between tests."""
    from website.api import profile_routes as routes_mod
    from website.api.module_runners import get_user_stats as runner_mod

    routes_mod._STATS_RATE_LIMITER._store.clear()
    runner_mod._IN_FLIGHT.clear()
    yield
    routes_mod._STATS_RATE_LIMITER._store.clear()
    runner_mod._IN_FLIGHT.clear()


def _build_app() -> FastAPI:
    """Fresh FastAPI app with only the profile router and stub auth."""
    app = FastAPI()
    app.include_router(profile_router)

    async def _fake_user():
        return _stub_user()

    app.dependency_overrides[get_current_user] = _fake_user
    return app


def _patch_settings(*, enabled: bool = True, allowlist: str = ""):
    """Return a settings patcher (caller starts via ExitStack)."""
    settings_mock = MagicMock()
    settings_mock.stats_tab_enabled = enabled
    settings_mock.stats_tab_allowlist = allowlist
    return patch(
        "website.api.profile_routes.get_settings", return_value=settings_mock
    )


def _patch_workspace_resolver():
    return patch(
        "website.api.profile_routes._resolve_workspace_id",
        return_value=_FAKE_WORKSPACE_ID,
    )


def _patch_supabase_client():
    """Patch the auth'd supabase client factory (imported lazy in route)."""
    return patch(
        "website.core.supabase_v2.client.get_v2_user_client",
        return_value=MagicMock(),
    )


def _patch_runner_ok(result_factory=None):
    """Patch run_get_user_stats to return a canned payload."""

    async def _runner_ok(*_args, **_kwargs):
        return (result_factory or _runner_payload)()

    return patch(
        "website.api.module_runners.get_user_stats.run_get_user_stats",
        side_effect=_runner_ok,
    )


def test_route_returns_payload_with_etag_header():
    """200: body present, ETag/Cache-Control/x-stats-cache=miss, _meta stripped."""
    app = _build_app()
    with ExitStack() as stack:
        stack.enter_context(_patch_settings())
        stack.enter_context(_patch_workspace_resolver())
        stack.enter_context(_patch_supabase_client())
        stack.enter_context(_patch_runner_ok())

        client = TestClient(app)
        resp = client.get(
            "/api/profile/stats",
            headers={"authorization": "Bearer test-jwt"},
        )

    assert resp.status_code == 200, resp.text
    assert resp.headers.get("etag") == "abc123"
    assert resp.headers.get("cache-control") == "private, max-age=60"
    assert resp.headers.get("x-stats-cache") == "miss"
    body = resp.json()
    assert "_meta" not in body
    assert "main_board" in body


def test_head_route_returns_etag_header_without_body():
    """HEAD: same auth/cache path as GET, but headers only for curl -I smoke."""
    app = _build_app()
    with ExitStack() as stack:
        stack.enter_context(_patch_settings())
        stack.enter_context(_patch_workspace_resolver())
        stack.enter_context(_patch_supabase_client())
        stack.enter_context(_patch_runner_ok())

        client = TestClient(app)
        resp = client.head(
            "/api/profile/stats",
            headers={"authorization": "Bearer test-jwt"},
        )

    assert resp.status_code == 200
    assert resp.headers.get("etag") == "abc123"
    assert resp.headers.get("cache-control") == "private, max-age=60"
    assert resp.headers.get("x-stats-cache") == "miss"
    assert resp.content == b""


def test_route_returns_304_on_matching_if_none_match():
    """304: If-None-Match equal to the runner's etag short-circuits the body."""
    app = _build_app()
    with ExitStack() as stack:
        stack.enter_context(_patch_settings())
        stack.enter_context(_patch_workspace_resolver())
        stack.enter_context(_patch_supabase_client())
        stack.enter_context(_patch_runner_ok())

        client = TestClient(app)
        resp = client.get(
            "/api/profile/stats",
            headers={
                "authorization": "Bearer test-jwt",
                "if-none-match": "abc123",
            },
        )

    assert resp.status_code == 304
    assert resp.headers.get("etag") == "abc123"


def test_route_503_when_disabled():
    """503: kill switch (STATS_TAB_ENABLED=false) hard-stops before auth scope."""
    app = _build_app()
    with ExitStack() as stack:
        stack.enter_context(_patch_settings(enabled=False))

        client = TestClient(app)
        resp = client.get(
            "/api/profile/stats",
            headers={"authorization": "Bearer test-jwt"},
        )

    assert resp.status_code == 503
    assert "disabled" in resp.json()["detail"].lower()


def test_route_503_when_user_not_in_allowlist():
    """503: caller's sub not in STATS_TAB_ALLOWLIST CSV."""
    app = _build_app()
    with ExitStack() as stack:
        stack.enter_context(
            _patch_settings(allowlist="other-uuid-1,other-uuid-2")
        )

        client = TestClient(app)
        resp = client.get(
            "/api/profile/stats",
            headers={"authorization": "Bearer test-jwt"},
        )

    assert resp.status_code == 503
    assert "not enabled" in resp.json()["detail"].lower()


def test_route_429_when_rate_limited():
    """429: rate limiter returns False; route emits Retry-After: 2."""
    app = _build_app()
    with ExitStack() as stack:
        stack.enter_context(_patch_settings())
        # Force the limiter to deny every call.
        rl_mock = MagicMock()
        rl_mock.allow.return_value = False
        stack.enter_context(
            patch("website.api.profile_routes._STATS_RATE_LIMITER", rl_mock)
        )

        client = TestClient(app)
        resp = client.get(
            "/api/profile/stats",
            headers={"authorization": "Bearer test-jwt"},
        )

    assert resp.status_code == 429
    assert resp.headers.get("retry-after") == "2"
