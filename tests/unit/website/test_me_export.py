"""Pin the /api/me/export GDPR/DPDP self-service data export contract.

Wire shape, status codes, pagination, and Content-Disposition header are all
covered. Mocks at the route-module boundary (mirrors
``test_me_ensure_provisioned.py``) so the suite stays offline and pins the
HTTP contract — not implementation internals.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


NARUTO = "550e8400-e29b-41d4-a716-446655440000"
WORKSPACE_ID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture(autouse=True)
def _clear_export_rate_limit():
    """The /api/me/export rate limit uses a module-level dict. Reset it
    between tests so per-user buckets don't leak across the suite (test order
    would otherwise dictate which tests trip the 429 gate)."""
    from website.api.routes import _rate_store
    keys = [k for k in _rate_store if k.startswith("me_export:")]
    for k in keys:
        _rate_store.pop(k, None)
    yield
    for k in keys:
        _rate_store.pop(k, None)


def _stub_user_with_sub(sub: str, *, email: str = "naruto@example.com") -> dict:
    return {
        "sub": sub,
        "email": email,
        "user_metadata": {"full_name": "Naruto Uzumaki"},
    }


def _build_client(user: dict | None) -> TestClient:
    """TestClient with optional get_current_user stub.

    ``user=None`` means leave the dependency unstubbed → real Bearer scheme
    runs and returns 401 (no Authorization header on the request).
    """
    from website.app import create_app
    from website.api import auth as auth_mod

    app = create_app()
    if user is not None:
        async def _stub() -> dict:
            return user
        app.dependency_overrides[auth_mod.get_current_user] = _stub
    return TestClient(app)


def _zettel(idx: int) -> dict:
    return {
        "id": f"00000000-0000-0000-0000-{idx:012d}",
        "canonical_zettel_id": f"cccccccc-cccc-cccc-cccc-{idx:012d}",
        "ai_summary": f"summary-{idx}",
        "user_tags": ["tag-a"],
        "derived_tags": ["d-tag"],
        "created_at": "2026-05-01T00:00:00Z",
        "canonical": {
            "id": f"cccccccc-cccc-cccc-cccc-{idx:012d}",
            "normalized_url": f"https://example.com/{idx}",
            "title": f"Title {idx}",
            "source_type": "web",
            "publication_date": None,
        },
    }


# ────────────────────────────────────────────────────────────────────────────
# 401 / 503 / 404 — error paths
# ────────────────────────────────────────────────────────────────────────────

def test_export_unauthenticated_returns_401():
    """No Authorization header → FastAPI Bearer scheme → 401."""
    client = _build_client(user=None)
    resp = client.get("/api/me/export")
    assert resp.status_code == 401


def test_export_returns_503_when_v2_not_configured():
    """v2 not in use → 503 with structured ``export_unavailable`` code."""
    client = _build_client(_stub_user_with_sub(NARUTO))
    with patch("website.api.routes.use_supabase_v2", return_value=False):
        resp = client.get("/api/me/export")
    assert resp.status_code == 503
    body = resp.json()
    assert body["detail"]["code"] == "export_unavailable"


def test_export_returns_404_when_scope_is_none():
    """No workspace memberships for this profile → 404 ``no_data_for_user``."""
    client = _build_client(_stub_user_with_sub(NARUTO))
    with patch("website.api.routes.use_supabase_v2", return_value=True), \
         patch("website.api.routes.get_supabase_v2_scope_for_read", return_value=None):
        resp = client.get("/api/me/export")
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"]["code"] == "no_data_for_user"


# ────────────────────────────────────────────────────────────────────────────
# 200 happy path — wire shape + headers
# ────────────────────────────────────────────────────────────────────────────

def _success_patches(zettels_per_workspace: list[list[dict]], profile_row: dict | None = None):
    """Common patch bundle: v2 on, scope present, content_repo returns the
    supplied pages per workspace (one page per call until exhausted), profile
    fetch returns ``profile_row``."""
    import uuid as _uuid

    if profile_row is None:
        profile_row = {
            "id": NARUTO,
            "email": "naruto@example.com",
            "display_name": "Naruto Uzumaki",
            "avatar_url": None,
            "created_at": "2026-01-01T00:00:00Z",
        }

    workspace_ids = [_uuid.UUID(WORKSPACE_ID)]
    content_repo = MagicMock()
    # Each call returns one page; subsequent calls return [] to end the loop.
    content_repo.list_workspace_zettels.side_effect = zettels_per_workspace + [[]]

    profile_id = _uuid.UUID(NARUTO)
    scope = (content_repo, profile_id, workspace_ids)

    core_repo = MagicMock()
    core_repo.get_profile.return_value = profile_row

    return {
        "use_supabase_v2": patch("website.api.routes.use_supabase_v2", return_value=True),
        "scope": patch("website.api.routes.get_supabase_v2_scope_for_read", return_value=scope),
        "v2_client": patch("website.api.routes.get_v2_client", return_value=MagicMock()),
        "core_repo": patch("website.api.routes.CoreRepository", return_value=core_repo),
    }


def test_export_returns_canonical_payload_shape_and_attachment_header():
    """Happy path: 200, JSON body has all required keys, attachment header set."""
    client = _build_client(_stub_user_with_sub(NARUTO))
    patches = _success_patches([[_zettel(1), _zettel(2)]])

    with patches["use_supabase_v2"], patches["scope"], patches["v2_client"], patches["core_repo"]:
        resp = client.get("/api/me/export")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Required wire-shape keys
    assert body["export_version"] == "1"
    assert body["format"] == "application/json"  # GDPR Art. 20 machine-readable declaration
    assert body["user_id"] == NARUTO
    assert body["email"] == "naruto@example.com"
    assert body["profile"]["display_name"] == "Naruto Uzumaki"
    assert body["workspaces"] == [WORKSPACE_ID]
    assert len(body["zettels"]) == 2
    assert body["truncated"] is False
    # not_included must be present so users know the export's scope explicitly
    assert isinstance(body["not_included"], list) and len(body["not_included"]) > 0
    assert "exported_at" in body and body["exported_at"].endswith("+00:00")
    # Attachment header so browsers prompt save
    cd = resp.headers.get("content-disposition", "")
    assert cd.startswith("attachment;") and "zettelkasten-export-" in cd and cd.endswith('.json"')
    # No-store so intermediaries don't cache user PII
    assert "no-store" in resp.headers.get("cache-control", "").lower()


def test_export_rate_limited_after_max_calls():
    """5 successful exports in a row → 6th returns 429 with Retry-After header."""
    from website.api.routes import _EXPORT_RATE_LIMIT_MAX
    client = _build_client(_stub_user_with_sub(NARUTO))
    patches = _success_patches([[_zettel(1)]] * (_EXPORT_RATE_LIMIT_MAX + 1))

    with patches["use_supabase_v2"], patches["scope"], patches["v2_client"], patches["core_repo"]:
        # Burn the budget
        for _ in range(_EXPORT_RATE_LIMIT_MAX):
            resp = client.get("/api/me/export")
            assert resp.status_code == 200, f"warm-up call failed: {resp.text[:200]}"
        # The next one MUST be denied
        resp = client.get("/api/me/export")

    assert resp.status_code == 429
    body = resp.json()
    assert body["detail"]["code"] == "export_rate_limited"
    retry_after = resp.headers.get("retry-after")
    assert retry_after is not None and int(retry_after) > 0


def test_export_rate_limit_isolated_per_user():
    """User A's budget exhaustion must NOT block user B."""
    from website.api.routes import _EXPORT_RATE_LIMIT_MAX

    user_a = _stub_user_with_sub(NARUTO, email="a@example.com")
    user_b = _stub_user_with_sub("99999999-9999-9999-9999-999999999999", email="b@example.com")

    # User A burns the budget
    client_a = _build_client(user_a)
    patches = _success_patches([[_zettel(1)]] * (_EXPORT_RATE_LIMIT_MAX + 1))
    with patches["use_supabase_v2"], patches["scope"], patches["v2_client"], patches["core_repo"]:
        for _ in range(_EXPORT_RATE_LIMIT_MAX):
            assert client_a.get("/api/me/export").status_code == 200
        assert client_a.get("/api/me/export").status_code == 429

    # User B should still be free to export
    client_b = _build_client(user_b)
    patches_b = _success_patches([[_zettel(1)]])
    with patches_b["use_supabase_v2"], patches_b["scope"], patches_b["v2_client"], patches_b["core_repo"]:
        resp_b = client_b.get("/api/me/export")
    assert resp_b.status_code == 200, f"per-user isolation broken: {resp_b.text[:200]}"


def test_export_paginates_through_multiple_pages():
    """When list_workspace_zettels returns a full page, the route requests
    the next offset until a short page (or empty) appears."""
    client = _build_client(_stub_user_with_sub(NARUTO))
    # First page is exactly _EXPORT_PAGE_SIZE (500) entries → must page again.
    # Second page is short → loop exits.
    from website.api.routes import _EXPORT_PAGE_SIZE
    full_page = [_zettel(i) for i in range(_EXPORT_PAGE_SIZE)]
    short_page = [_zettel(_EXPORT_PAGE_SIZE + i) for i in range(3)]
    patches = _success_patches([full_page, short_page])

    with patches["use_supabase_v2"], patches["scope"], patches["v2_client"], patches["core_repo"]:
        resp = client.get("/api/me/export")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["zettels"]) == _EXPORT_PAGE_SIZE + 3
    assert body["truncated"] is False


def test_export_marks_truncated_when_per_workspace_cap_hit():
    """If a workspace has >= _EXPORT_MAX_PER_WORKSPACE zettels, truncated=True."""
    client = _build_client(_stub_user_with_sub(NARUTO))
    from website.api.routes import _EXPORT_MAX_PER_WORKSPACE, _EXPORT_PAGE_SIZE
    # Construct enough full pages to hit the cap exactly.
    pages = []
    served = 0
    while served < _EXPORT_MAX_PER_WORKSPACE:
        page = [_zettel(served + i) for i in range(_EXPORT_PAGE_SIZE)]
        pages.append(page)
        served += _EXPORT_PAGE_SIZE
    patches = _success_patches(pages)

    with patches["use_supabase_v2"], patches["scope"], patches["v2_client"], patches["core_repo"]:
        resp = client.get("/api/me/export")

    assert resp.status_code == 200
    body = resp.json()
    assert body["truncated"] is True
    assert len(body["zettels"]) >= _EXPORT_MAX_PER_WORKSPACE


def test_export_profile_fetch_failure_returns_503():
    """If CoreRepository.get_profile raises, the route surfaces 503 with
    ``export_failed`` rather than 500."""
    import uuid as _uuid

    client = _build_client(_stub_user_with_sub(NARUTO))
    workspace_ids = [_uuid.UUID(WORKSPACE_ID)]
    profile_id = _uuid.UUID(NARUTO)
    content_repo = MagicMock()
    scope = (content_repo, profile_id, workspace_ids)

    core_repo = MagicMock()
    core_repo.get_profile.side_effect = RuntimeError("v2 hiccup")

    with patch("website.api.routes.use_supabase_v2", return_value=True), \
         patch("website.api.routes.get_supabase_v2_scope_for_read", return_value=scope), \
         patch("website.api.routes.get_v2_client", return_value=MagicMock()), \
         patch("website.api.routes.CoreRepository", return_value=core_repo):
        resp = client.get("/api/me/export")

    assert resp.status_code == 503
    body = resp.json()
    assert body["detail"]["code"] == "export_failed"


def test_export_continues_when_zettel_page_fails_but_marks_truncated():
    """If list_workspace_zettels raises mid-page, the route logs + sets
    truncated=True instead of erroring the whole export."""
    client = _build_client(_stub_user_with_sub(NARUTO))
    import uuid as _uuid

    workspace_ids = [_uuid.UUID(WORKSPACE_ID)]
    profile_id = _uuid.UUID(NARUTO)
    content_repo = MagicMock()
    # First page succeeds, second raises.
    content_repo.list_workspace_zettels.side_effect = [
        [_zettel(i) for i in range(500)],
        RuntimeError("network blip"),
    ]
    scope = (content_repo, profile_id, workspace_ids)

    core_repo = MagicMock()
    core_repo.get_profile.return_value = {"id": NARUTO, "email": "n@example.com", "display_name": "N"}

    with patch("website.api.routes.use_supabase_v2", return_value=True), \
         patch("website.api.routes.get_supabase_v2_scope_for_read", return_value=scope), \
         patch("website.api.routes.get_v2_client", return_value=MagicMock()), \
         patch("website.api.routes.CoreRepository", return_value=core_repo):
        resp = client.get("/api/me/export")

    assert resp.status_code == 200
    body = resp.json()
    assert body["truncated"] is True
    assert len(body["zettels"]) == 500  # got the first page; second page failed
