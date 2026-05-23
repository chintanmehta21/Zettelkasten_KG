"""Tests for the popup Refresh button endpoint (website/features/refresh_button).

Focused unit coverage:
- Route is mounted under /api/zettels/refresh.
- Anonymous calls are rejected (401) because refresh requires login + a quota
  credit.
- The handler delegates to refresh_zettel_summary with the URL the client
  posted and the JWT 'sub' resolved to a UUID.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from website.api.auth import get_optional_user
from website.app import create_app


_USER_SUB = "00000000-0000-0000-0000-000000000001"


def _unauthed_client() -> TestClient:
    return TestClient(create_app())


def _authed_client() -> TestClient:
    app = create_app()

    async def _fake_user():
        return {"sub": _USER_SUB, "email": "x@y.z"}

    app.dependency_overrides[get_optional_user] = _fake_user
    return TestClient(app)


def test_refresh_route_is_mounted():
    app = create_app()
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/zettels/refresh" in paths


def test_refresh_rejects_anonymous():
    """No user → 401. Refresh is always a charged operation; we never let
    anon callers bypass the dedup gate for free."""
    r = _unauthed_client().post(
        "/api/zettels/refresh", json={"url": "https://example.com/a"}
    )
    assert r.status_code == 401


def test_refresh_invokes_summary_pipeline_with_url():
    """When a logged-in user POSTs a URL, refresh_zettel_summary is called
    with that URL and the JWT 'sub' resolved as the effective_user_id."""
    fake_payload = {
        "title": "Refreshed title",
        "summary": "fresh body",
        "brief_summary": "fresh brief",
        "detailed_summary": "fresh body",
        "tags": ["new"],
        "source_type": "web",
        "source_url": "https://example.com/a",
        "one_line_summary": "fresh brief",
        "tokens_used": 0,
        "latency_ms": 0,
        "metadata": {},
        "refreshed_at": "2026-05-23T00:00:00+00:00",
        "refreshed_by_user_id": _USER_SUB,
        "normalized_url": "https://example.com/a",
        "write_status": "skipped_no_supabase",
    }

    with patch(
        "website.features.refresh_button.refresh_routes.refresh_zettel_summary",
        new=AsyncMock(return_value=fake_payload),
    ) as mock_refresh:
        r = _authed_client().post(
            "/api/zettels/refresh",
            json={"url": "https://example.com/a", "client_action_id": "act-1"},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "Refreshed title"
    assert body["refreshed_at"] == "2026-05-23T00:00:00+00:00"
    assert mock_refresh.await_count == 1
    kwargs = mock_refresh.await_args.kwargs
    assert kwargs["url"] == "https://example.com/a"
    assert str(kwargs["effective_user_id"]) == _USER_SUB
    assert kwargs["client_action_id"] == "act-1"
