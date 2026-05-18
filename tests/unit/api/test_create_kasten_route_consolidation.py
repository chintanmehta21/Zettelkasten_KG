"""Unit tests for the consolidated ``POST /api/rag/sandboxes`` route (Phase C).

NO live Supabase. Two guarantees under test:

1. ``links == []`` (or omitted) → response is BYTE-IDENTICAL to the legacy
   ``create_sandbox`` (v2 dual-path). The consolidation must not change the
   wire contract for existing callers / the Kasten-modal frontend.
2. ``links`` non-empty → 202 Accepted + ``{operation_id, status_url}``; the
   background operation completes and the poll endpoint returns the final
   ``CreateKastenOutput``.

Auth + entitlement are stubbed (the pricing-module-authority rule forbids
seeding entitlements; this no-op bypass is the established pattern in
``tests/integration/v2/test_sandbox_routes_v2.py`` / ``tests/v2/fixtures``).
"""
from __future__ import annotations

import time
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from website.api import sandbox_routes
from website.api.module_runners import create_kasten as ck
from website.app import create_app

NARUTO = uuid.UUID("f2105544-b73d-4946-8329-096d82f070d3")
WS_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
PROFILE_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")


@pytest.fixture(autouse=True)
def _clear_state():
    ck._IDEMPOTENCY_CACHE.clear()
    ck._IN_FLIGHT.clear()
    sandbox_routes._KASTEN_OPERATIONS.clear()
    sandbox_routes._KASTEN_OP_TASKS.clear()
    yield
    ck._IDEMPOTENCY_CACHE.clear()
    ck._IN_FLIGHT.clear()
    sandbox_routes._KASTEN_OPERATIONS.clear()
    sandbox_routes._KASTEN_OP_TASKS.clear()


def _kasten_row(name: str, kid: uuid.UUID) -> dict:
    return {
        "id": str(kid),
        "name": name,
        "description": "",
        "icon": "stack",
        "color": "#14b8a6",
        "default_quality": "fast",
        "created_at": "2026-05-18T00:00:00Z",
        "updated_at": "2026-05-18T00:00:00Z",
        "last_used_at": None,
    }


def _build_app(monkeypatch, rag_repo: MagicMock):
    """Build the app with auth + entitlement stubbed and the v2 scope mocked."""
    async def _noop(*_a, **_kw):
        return None

    monkeypatch.setattr(sandbox_routes, "require_entitlement", _noop)
    # v2 dual-path gate: _v2_scope_for → (rag_repo, profile_id, workspace_id).
    monkeypatch.setattr(
        sandbox_routes,
        "_v2_scope_for",
        lambda user: (rag_repo, PROFILE_ID, WS_ID),
    )
    app = create_app()
    app.dependency_overrides[sandbox_routes.get_current_user] = lambda: {
        "sub": str(NARUTO),
        "email": "naruto@test",
    }
    return app


def _app_client(monkeypatch, rag_repo: MagicMock):
    """A non-persistent client.

    Each request runs on its own short-lived event loop (Starlette's
    ``TestClient`` opens a fresh blocking portal per request when NOT used as
    a context manager). This is the correct harness for the synchronous
    create-only path (request fully completes before returning), but it
    CANNOT be used to poll a fire-and-forget background task across two
    requests — see ``_app_client_persistent``.
    """
    return TestClient(_build_app(monkeypatch, rag_repo))


def _app_client_persistent(monkeypatch, rag_repo: MagicMock) -> TestClient:
    """A context-managed client (single persistent event loop across requests).

    Starlette's ``TestClient.__enter__`` opens ONE ``anyio`` blocking portal
    (one event loop) that survives for the whole ``with`` block, mirroring the
    single long-lived loop a real uvicorn worker runs. The async create-Kasten
    path (D3) is a fire-and-forget ``asyncio.create_task`` whose lifetime must
    outlive the 202 response — that is only valid on a persistent loop. With a
    per-request loop the background task is cancelled at POST teardown (the
    original ``CancelledError`` root cause). Caller MUST use ``with``.
    """
    return TestClient(_build_app(monkeypatch, rag_repo))


def test_links_omitted_is_byte_identical_to_legacy(monkeypatch):
    """No ``links`` key → identical JSON to the pre-Phase-C v2 create path.

    The legacy v2 path returns ``{"sandbox": _serialize_kasten_v2(row)}``. The
    consolidated route, with links omitted, must fall straight through to that
    exact code (the Phase C branch is gated on ``if body.links``). We assert
    the response equals an independent ``_serialize_kasten_v2`` of the same row.
    """
    kid = uuid.uuid4()
    row = _kasten_row("legacy-shape", kid)
    rag_repo = MagicMock()
    rag_repo.create_kasten.return_value = row

    client = _app_client(monkeypatch, rag_repo)
    resp = client.post(
        "/api/rag/sandboxes",
        json={"name": "legacy-shape", "default_quality": "fast"},
    )
    assert resp.status_code == 200
    expected = {"sandbox": sandbox_routes._serialize_kasten_v2(row)}
    assert resp.json() == expected
    # The runner path was NOT taken — legacy create_kasten called directly once.
    rag_repo.create_kasten.assert_called_once()


def test_links_empty_list_is_byte_identical_to_legacy(monkeypatch):
    """Explicit ``links: []`` is also create-only and byte-identical."""
    kid = uuid.uuid4()
    row = _kasten_row("empty-links", kid)
    rag_repo = MagicMock()
    rag_repo.create_kasten.return_value = row

    client = _app_client(monkeypatch, rag_repo)
    resp = client.post(
        "/api/rag/sandboxes",
        json={"name": "empty-links", "links": [], "default_quality": "fast"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"sandbox": sandbox_routes._serialize_kasten_v2(row)}


def test_links_present_returns_202_then_operation_completes(monkeypatch):
    """Non-empty links → 202 + status_url; the op finishes + poll returns it."""
    kid = uuid.uuid4()
    rag_repo = MagicMock()
    rag_repo.create_kasten.return_value = _kasten_row("with-links", kid)
    rag_repo.add_zettels_to_kasten.return_value = 1

    content_repo = MagicMock()
    wz = uuid.uuid4()
    content_repo.resolve_workspace_zettel_id_by_url.return_value = wz

    async def _fake_pipeline(*_a, **_kw):
        return {
            "status": "succeeded",
            "operation_id": "op",
            "summary": {"source_url": "https://x.example.com/"},
            "persistence": {
                "requested": True,
                "persisted": True,
                "file_store": True,
                "supabase": True,
                "duplicate": False,
            },
            "quality": {"confidence": "ok"},
            "node_id": "web-x",
            "workspace_zettel_id": "CANONICAL",
        }

    # Context-managed client → ONE persistent event loop spans the POST and
    # all poll GETs (mirrors a real uvicorn worker). The background create-
    # Kasten task created during the 202 POST survives into the poll GETs
    # because (a) the loop is the same and (b) sandbox_routes._KASTEN_OP_TASKS
    # holds a strong reference (mirror of zettels_routes._OPERATION_TASKS).
    with patch.object(ck, "RAGRepository", return_value=rag_repo), patch(
        "website.core.persist.get_supabase_v2_scope",
        return_value=(content_repo, PROFILE_ID, WS_ID),
    ), patch(
        "website.api.routes.invalidate_user_graph", return_value=1
    ), patch.object(
        ck,
        "run_add_zettel_pipeline",
        side_effect=_fake_pipeline,
    ), _app_client_persistent(monkeypatch, rag_repo) as client:
        resp = client.post(
            "/api/rag/sandboxes",
            json={
                "name": "with-links",
                "links": ["https://x.example.com/"],
                "client_action_id": "cak-route-async",
            },
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "accepted"
        assert body["operation_id"] == "cak-route-async"
        status_url = body["status_url"]
        assert status_url == "/api/rag/sandboxes/operations/cak-route-async"

        # Poll until terminal. The background task resolves near-instantly
        # with all I/O mocked; each poll GET yields control back to the
        # shared loop so the background task can make progress. A bounded
        # loop with a tiny sleep keeps it deterministic + non-flaky.
        final = None
        for _ in range(100):
            poll = client.get(status_url)
            if poll.status_code == 200:
                final = poll.json()
                break
            time.sleep(0.02)
        assert final is not None, "operation did not complete"
        assert final["status"] == "succeeded"
        assert final["kasten"]["id"] == str(kid)
        assert len(final["ingested"]) == 1
        assert final["ingested"][0]["workspace_zettel_id"] == str(wz)
        assert final["failed"] == []


def test_links_present_without_v2_scope_is_501(monkeypatch):
    """Link-ingest has no v1 equivalent → clear 501, not a misleading fallthrough."""
    async def _noop(*_a, **_kw):
        return None

    monkeypatch.setattr(sandbox_routes, "require_entitlement", _noop)
    monkeypatch.setattr(sandbox_routes, "_v2_scope_for", lambda user: None)
    app = create_app()
    app.dependency_overrides[sandbox_routes.get_current_user] = lambda: {
        "sub": str(NARUTO),
        "email": "naruto@test",
    }
    client = TestClient(app)
    resp = client.post(
        "/api/rag/sandboxes",
        json={"name": "no-v2", "links": ["https://x.example.com/"]},
    )
    assert resp.status_code == 501


def test_malformed_link_rejected_at_request_validation(monkeypatch):
    """A bad URL in ``links`` is a 422 request-validation error (no Kasten)."""
    rag_repo = MagicMock()
    client = _app_client(monkeypatch, rag_repo)
    resp = client.post(
        "/api/rag/sandboxes",
        json={"name": "bad", "links": ["javascript:alert(1)"]},
    )
    assert resp.status_code == 422
    rag_repo.create_kasten.assert_not_called()


def test_poll_unknown_operation_is_404(monkeypatch):
    rag_repo = MagicMock()
    client = _app_client(monkeypatch, rag_repo)
    resp = client.get("/api/rag/sandboxes/operations/does-not-exist")
    assert resp.status_code == 404


# ── P1 regression (Codex review #3261718805): cross-tenant op-store leak ──


def test_op_store_is_tenant_scoped_no_cross_user_leak():
    """The async create-Kasten op store MUST be keyed by the authenticated
    subject, not by ``operation_id`` alone (which can be a user-supplied
    Kasten name). Two users using the SAME operation_id must NOT see each
    other's record, and each must still read their own."""
    user_a = "f2105544-b73d-4946-8329-096d82f070d3"
    user_b = "00000000-0000-0000-0000-0000000000bb"
    op = "My Research"  # same name → same operation_id for both users

    sandbox_routes._kasten_op_put(user_a, op, {"status": "accepted", "who": "A"})
    sandbox_routes._kasten_op_put(user_b, op, {"status": "done", "who": "B"})

    a = sandbox_routes._kasten_op_get(user_a, op)
    b = sandbox_routes._kasten_op_get(user_b, op)
    assert a is not None and a["who"] == "A", "user A must read their own op"
    assert b is not None and b["who"] == "B", "user B must read their own op"
    assert a is not b and a["who"] != b["who"], "records must be isolated"

    # A user who never created this op (or replays another's id) sees nothing.
    assert sandbox_routes._kasten_op_get("11111111-1111-1111-1111-111111111111", op) is None
    # Distinct scoped keys actually exist in the store (not one shared key).
    assert sandbox_routes._scoped_op_key(user_a, op) != sandbox_routes._scoped_op_key(user_b, op)
    assert len(sandbox_routes._KASTEN_OPERATIONS) == 2


def test_poll_endpoint_cannot_read_another_users_operation(monkeypatch):
    """End-to-end: user B polling user A's operation_id gets 404, never A's
    payload (the P1 cross-tenant read path)."""
    rag_repo = MagicMock()
    app = _build_app(monkeypatch, rag_repo)

    # Seed an operation owned by user A directly in the store.
    user_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    sandbox_routes._kasten_op_put(
        user_a, "shared-name", {"status": "done", "secret": "A-only"}
    )

    # The app's auth override returns NARUTO (≠ user_a) — i.e. "user B".
    with TestClient(app) as client:
        resp = client.get("/api/rag/sandboxes/operations/shared-name")
    assert resp.status_code == 404, (
        "polling another user's operation_id must 404, not leak their payload"
    )
    assert "A-only" not in resp.text


# ── P1 regression (Codex review #3261831595): idempotency not bypassed ──


def test_terminal_failed_op_is_not_replayed_retry_runs(monkeypatch):
    """A pre-existing FAILED op record (same operation_id, within TTL) must
    NOT short-circuit the route — the request falls through so
    run_create_kasten_pipeline can retry (failures are never cached by the
    runner). The stale failed payload must NOT be returned."""
    async def _stub_pipeline(*_a, **_kw):
        return {"status": "succeeded", "operation_id": "cak-retry", "fresh": True}

    monkeypatch.setattr(
        sandbox_routes, "run_create_kasten_pipeline", _stub_pipeline
    )
    rag_repo = MagicMock()
    with _app_client_persistent(monkeypatch, rag_repo) as client:
        # Seed a stale TERMINAL failed record for this user+operation_id.
        sandbox_routes._kasten_op_put(
            str(NARUTO), "cak-retry",
            {"status": "failed", "operation_id": "cak-retry", "error": "STALE"},
        )
        resp = client.post(
            "/api/rag/sandboxes",
            json={"name": "n", "links": ["https://x.example.com/"],
                  "client_action_id": "cak-retry"},
        )
    assert resp.status_code == 202, "must start a fresh run, not replay failed"
    body = resp.json()
    assert body.get("status") == "accepted"
    assert body.get("error") != "STALE", "stale failed payload must NOT leak"


def test_inflight_accepted_op_is_short_circuited(monkeypatch):
    """A genuinely IN-FLIGHT (accepted) duplicate IS short-circuited with 202
    pointing at the existing op (don't spawn a redundant task)."""
    async def _stub_pipeline(*_a, **_kw):
        return {"status": "succeeded", "operation_id": "cak-inflight"}

    monkeypatch.setattr(
        sandbox_routes, "run_create_kasten_pipeline", _stub_pipeline
    )
    rag_repo = MagicMock()
    with _app_client_persistent(monkeypatch, rag_repo) as client:
        sandbox_routes._kasten_op_put(
            str(NARUTO), "cak-inflight",
            {"status": "accepted", "operation_id": "cak-inflight",
             "status_url": "/api/rag/sandboxes/operations/cak-inflight"},
        )
        resp = client.post(
            "/api/rag/sandboxes",
            json={"name": "n", "links": ["https://x.example.com/"],
                  "client_action_id": "cak-inflight"},
        )
    assert resp.status_code == 202
    assert resp.json().get("status") == "accepted"
