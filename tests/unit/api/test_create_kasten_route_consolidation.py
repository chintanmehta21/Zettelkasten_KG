"""Unit tests for the consolidated ``POST /api/rag/sandboxes`` route.

Updated for the new_apis_1a refactor (locked 2026-05-23):

* The per-process ``_KASTEN_OPERATIONS`` / ``_kasten_op_put`` / etc. were
  removed in favour of the DB-backed ``core.operations`` row (single
  source of truth across gunicorn workers). Tests now mock
  ``operations_repo`` with a stateful in-memory shim.
* ``_IDEMPOTENCY_CACHE`` runner-level result cache was removed (D4).
  The ``_IN_FLIGHT`` singleflight stays.
* The new ``SandboxCreateRequest`` accepts ``selection_mode``,
  ``source_types``, ``workspace_zettel_ids`` (new_apis1.md spec).
* The route honours an ``Idempotency-Key`` header as the canonical op id.

Auth + entitlement are stubbed per the pricing-module-authority rule —
never seed entitlements, never invent meter values.
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


# ─────────────────────────────────────────────────────────────────────────
# Stateful operations_repo shim
# ─────────────────────────────────────────────────────────────────────────


class _OperationsRepoShim:
    """Tiny in-memory stand-in for ``website.core.operations_repo``.

    Implements accept/start/finalize/get_operation/count_in_flight/cancel
    with realistic semantics so a route test can exercise the full
    accept→spawn→poll→finalize→read flow without a live DB. Keyed by
    ``(user_id, operation_id)`` so the route's user-scoped BOLA filter
    works naturally.
    """

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict] = {}

    # ---- methods called by route + worker ---------------------------------

    def accept(
        self,
        *,
        user_id,
        operation_id: str,
        request_hash: str,
        accepted_body: dict,
        ttl_seconds: int = 86400,
    ):
        del ttl_seconds  # honoured by real impl; ignored by shim
        key = (str(user_id), operation_id)
        existing = self.rows.get(key)
        if existing is not None and existing.get("status") in (
            "queued",
            "running",
            "accepted",
        ):
            if existing.get("request_hash") == request_hash:
                # Idempotent replay of the canonical op.
                return (operation_id, False)
            # Different body — caller's pre-check should have caught this; if
            # it slipped through we still record a fresh row.
        self.rows[key] = {
            "operation_id": operation_id,
            "user_id": str(user_id),
            "request_hash": request_hash,
            "status": "accepted",
            "response": dict(accepted_body),
            "error": None,
            "created_at": "2026-05-23T00:00:00Z",
            "updated_at": "2026-05-23T00:00:00Z",
        }
        return (operation_id, True)

    def start(self, *, user_id, operation_id: str) -> bool:
        key = (str(user_id), operation_id)
        if key not in self.rows:
            return False
        if self.rows[key]["status"] != "accepted":
            return False
        self.rows[key]["status"] = "running"
        return True

    def finalize(
        self,
        *,
        user_id,
        operation_id: str,
        target: str,
        response: dict | None = None,
        error: dict | None = None,
    ) -> bool:
        key = (str(user_id), operation_id)
        if key not in self.rows:
            return False
        if self.rows[key]["status"] not in ("accepted", "running"):
            return False
        self.rows[key]["status"] = target
        if response is not None:
            self.rows[key]["response"] = response
        if error is not None:
            self.rows[key]["error"] = error
        return True

    def get_operation(self, *, user_id, operation_id: str):
        key = (str(user_id), operation_id)
        return dict(self.rows[key]) if key in self.rows else None

    def count_in_flight_for_user(self, *, user_id) -> int:
        return sum(
            1
            for (u, _), r in self.rows.items()
            if u == str(user_id) and r["status"] in ("queued", "running", "accepted")
        )

    def cancel(self, *, user_id, operation_id: str) -> bool:
        return self.finalize(
            user_id=user_id,
            operation_id=operation_id,
            target="cancelled",
        )


@pytest.fixture(autouse=True)
def _clear_state():
    """Reset the singleflight + live-tasks maps between tests.

    D4 (locked 2026-05-23): per-process result caches are gone. Only
    ``_IN_FLIGHT`` (runner singleflight) and ``_LIVE_TASKS_KASTEN``
    (route strong-ref / cancel target) survive.
    """
    ck._IN_FLIGHT.clear()
    sandbox_routes._LIVE_TASKS_KASTEN.clear()
    yield
    ck._IN_FLIGHT.clear()
    sandbox_routes._LIVE_TASKS_KASTEN.clear()


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
    monkeypatch.setattr(
        sandbox_routes,
        "_v2_scope_for",
        lambda user: (rag_repo, PROFILE_ID, WS_ID),
    )
    monkeypatch.setattr(
        sandbox_routes,
        "get_supabase_v2_scope",
        lambda sub: (rag_repo, PROFILE_ID, WS_ID),
    )
    app = create_app()
    app.dependency_overrides[sandbox_routes.get_current_user] = lambda: {
        "sub": str(NARUTO),
        "email": "naruto@test",
    }
    return app


def _app_client(monkeypatch, rag_repo: MagicMock):
    """A non-persistent client for the synchronous create-only path."""
    return TestClient(_build_app(monkeypatch, rag_repo))


def _app_client_persistent(monkeypatch, rag_repo: MagicMock) -> TestClient:
    """Context-managed client (single persistent event loop)."""
    return TestClient(_build_app(monkeypatch, rag_repo))


# ─────────────────────────────────────────────────────────────────────────
# Legacy / create-only path (unchanged by this iteration)
# ─────────────────────────────────────────────────────────────────────────


def test_links_omitted_is_byte_identical_to_legacy(monkeypatch):
    """No ``links`` key → identical JSON to the pre-iter-1a v2 create path.

    The legacy v2 path returns ``{"sandbox": _serialize_kasten_v2(row)}``.
    The consolidated route, with no membership-bearing fields set, falls
    straight through to that exact code (the async runner is gated on
    ``has_members or explicit_async``). new_apis1.md requirement.
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


# ─────────────────────────────────────────────────────────────────────────
# Async create-with-members path (D3 + D4 + new_apis_1a)
# ─────────────────────────────────────────────────────────────────────────


def test_links_present_returns_202_then_operation_completes(monkeypatch):
    """Non-empty links → 202 + status_url; the op finishes + poll returns it.

    Stateful operations_repo shim provides realistic accept→start→
    finalize→get semantics so the route's full DB-backed flow exercises
    end-to-end without a live DB.
    """
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

    ops_shim = _OperationsRepoShim()

    with patch.object(ck, "RAGRepository", return_value=rag_repo), patch(
        "website.core.persist.get_supabase_v2_scope",
        return_value=(content_repo, PROFILE_ID, WS_ID),
    ), patch(
        "website.api.routes.invalidate_user_graph", return_value=1
    ), patch.object(
        ck,
        "run_add_zettel_pipeline",
        side_effect=_fake_pipeline,
    ), patch(
        "website.core.operations_repo.accept", side_effect=ops_shim.accept,
    ), patch(
        "website.core.operations_repo.start", side_effect=ops_shim.start,
    ), patch(
        "website.core.operations_repo.finalize", side_effect=ops_shim.finalize,
    ), patch(
        "website.core.operations_repo.get_operation",
        side_effect=ops_shim.get_operation,
    ), patch(
        "website.core.operations_repo.count_in_flight_for_user",
        side_effect=ops_shim.count_in_flight_for_user,
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

        # Poll until terminal. With all I/O mocked the background task
        # finishes near-instantly; bounded loop keeps the assertion
        # deterministic.
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
        # new_apis1.md: selection summary surfaces resolved_member_count.
        assert "selection" in final
        assert final["selection"]["resolved_member_count"] == 1


def test_links_present_without_v2_scope_is_501(monkeypatch):
    """Membership-bearing request without a v2 scope → clear 501.

    No v1 equivalent for the v2-only runner; entitlement must NOT have
    been consumed for the unsupported path (no billable failure).
    """
    _charged: list[bool] = []

    async def _charge(*_a, **_kw):
        _charged.append(True)

    monkeypatch.setattr(sandbox_routes, "require_entitlement", _charge)
    monkeypatch.setattr(sandbox_routes, "get_supabase_v2_scope", lambda sub: None)
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
    assert _charged == []


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


def test_poll_unknown_operation_returns_transient_202(monkeypatch):
    """Unknown op id → transient 202 pending (cross-worker replication gap).

    new_apis_1a (D3): the polling route delegates to
    ``_async_ops.render_operation_status`` which serves a 202 + Retry-After
    when the operations row isn't visible yet to this worker's read
    replica. The previous 404 leaked the row's non-existence; the 202
    pending is bounded by the client's poll budget.
    """
    rag_repo = MagicMock()
    ops_shim = _OperationsRepoShim()

    with patch(
        "website.core.operations_repo.get_operation",
        side_effect=ops_shim.get_operation,
    ):
        client = _app_client(monkeypatch, rag_repo)
        resp = client.get("/api/rag/sandboxes/operations/does-not-exist")
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["operation_id"] == "does-not-exist"
    # The status_url must point back at the sandbox-polling URL (D3:
    # legacy alias preserved for backward compat; /api/operations/{id}
    # also works since they read the same core.operations row).
    assert body["status_url"].endswith("/api/rag/sandboxes/operations/does-not-exist")


# ─────────────────────────────────────────────────────────────────────────
# new_apis_1a additions: selection_mode + Idempotency-Key
# ─────────────────────────────────────────────────────────────────────────


def test_selection_mode_source_requires_source_types(monkeypatch):
    """``selection_mode='source'`` with empty ``source_types`` → 422.

    The Pydantic model_validator catches per-mode constraint violations
    before the route handler runs; runner-side defense-in-depth would
    also trip.
    """
    rag_repo = MagicMock()
    client = _app_client(monkeypatch, rag_repo)
    resp = client.post(
        "/api/rag/sandboxes",
        json={
            "name": "src-empty",
            "selection_mode": "source",
            "source_types": [],
        },
    )
    assert resp.status_code == 422
    rag_repo.create_kasten.assert_not_called()


def test_selection_mode_specific_requires_workspace_zettel_ids(monkeypatch):
    """``selection_mode='specific'`` with empty ``workspace_zettel_ids`` → 422."""
    rag_repo = MagicMock()
    client = _app_client(monkeypatch, rag_repo)
    resp = client.post(
        "/api/rag/sandboxes",
        json={
            "name": "spec-empty",
            "selection_mode": "specific",
            "workspace_zettel_ids": [],
        },
    )
    assert resp.status_code == 422


def test_selection_mode_all_must_have_no_other_inputs(monkeypatch):
    """``selection_mode='all'`` with non-empty source_types → 422."""
    rag_repo = MagicMock()
    client = _app_client(monkeypatch, rag_repo)
    resp = client.post(
        "/api/rag/sandboxes",
        json={
            "name": "all-with-extras",
            "selection_mode": "all",
            "source_types": ["web"],
        },
    )
    assert resp.status_code == 422


def test_idempotency_key_header_overrides_client_action_id(monkeypatch):
    """The IETF-draft ``Idempotency-Key`` header is the canonical op id.

    A request with ``Idempotency-Key: X`` and ``client_action_id: Y`` must
    spawn an op keyed by X (the header wins). Round-trip via status_url +
    poll confirms the canonical id flowed through the operations_repo.
    """
    kid = uuid.uuid4()
    rag_repo = MagicMock()
    rag_repo.create_kasten.return_value = _kasten_row("hdr-wins", kid)
    rag_repo.add_zettels_to_kasten.return_value = 0

    content_repo = MagicMock()
    ops_shim = _OperationsRepoShim()

    async def _fake_pipeline(*_a, **_kw):
        return {
            "status": "succeeded",
            "operation_id": "ignored",
            "summary": {"source_url": "https://y.example.com/"},
            "persistence": {
                "requested": True,
                "persisted": True,
                "file_store": True,
                "supabase": True,
                "duplicate": False,
            },
            "quality": {"confidence": "ok"},
            "node_id": "web-y",
            "workspace_zettel_id": "C",
        }

    with patch.object(ck, "RAGRepository", return_value=rag_repo), patch(
        "website.core.persist.get_supabase_v2_scope",
        return_value=(content_repo, PROFILE_ID, WS_ID),
    ), patch(
        "website.api.routes.invalidate_user_graph", return_value=1
    ), patch.object(
        ck, "run_add_zettel_pipeline", side_effect=_fake_pipeline,
    ), patch(
        "website.core.operations_repo.accept", side_effect=ops_shim.accept,
    ), patch(
        "website.core.operations_repo.start", side_effect=ops_shim.start,
    ), patch(
        "website.core.operations_repo.finalize", side_effect=ops_shim.finalize,
    ), patch(
        "website.core.operations_repo.get_operation",
        side_effect=ops_shim.get_operation,
    ), patch(
        "website.core.operations_repo.count_in_flight_for_user",
        side_effect=ops_shim.count_in_flight_for_user,
    ), _app_client_persistent(monkeypatch, rag_repo) as client:
        resp = client.post(
            "/api/rag/sandboxes",
            json={
                "name": "hdr-wins",
                "links": ["https://y.example.com/"],
                "client_action_id": "body-action",
            },
            headers={"Idempotency-Key": "header-action"},
        )
        assert resp.status_code == 202
        body = resp.json()
        # Header beat the body's client_action_id.
        assert body["operation_id"] == "header-action"
        assert body["status_url"].endswith(
            "/api/rag/sandboxes/operations/header-action"
        )

        # Confirm the canonical id round-trips through ops_shim.
        assert ("header-action" in [
            op for (_u, op) in ops_shim.rows.keys()
        ])
