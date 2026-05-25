"""Add Zettel facade contract tests.

These tests pin the website-facing Add Zettel path to the summarization engine
entry point plus canonical persistence.

PR #39 / Wave-1 A1 (2026-05-20) CONTRACT CHANGE: the route is now always-async
(HTTP 202 + polling). Tests that previously asserted on inline 200/500 now
assert on the BACKGROUND finalize write captured via the operations_repo mock.
GET /api/operations/{id} surfaces the same body to the client.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

ZORO_AUTH_ID = UUID("a57e1f2f-7d89-4cd7-ae39-72c440ed4b4e")


def _drive_bg_to_finalize(
    post_json: dict, captured: dict, user_dict: dict | None = None,
    *, settle_s: float = 2.5,
) -> None:
    """PR #40 hotfix (2026-05-21) — refined 2026-05-23: deterministic finalize.

    PRIOR DESIGN (poll-then-fallback) had a Linux CI race: the route's bg
    task could partially execute (call summarize) before TestClient tore the
    per-request loop down without reaching finalize. The helper's poll then
    timed out + ran the pipeline AGAIN via asyncio.run → summarize called
    twice → ``assert seen == [user_id]`` flake.

    REFINED DESIGN: ``_install_async_mocks`` monkeypatches ``zettels_routes._run``
    to a no-op so the route's auto-spawned bg task never invokes the pipeline.
    This helper is the SOLE driver, calling the saved original ``_run`` once
    via ``asyncio.run``. Pipeline runs exactly once on EVERY platform.

    ``settle_s`` is retained for back-compat with the old helper signature
    but is no longer used (we drive immediately)."""
    del settle_s  # unused (kept for signature back-compat)
    import asyncio
    from website.api import zettels_routes as zr

    real_run = captured.get("_real_run", zr._run)
    body = zr.AddZettelRequest(**post_json)
    user_id = zr._effective_user_id(user_dict)
    asyncio.run(
        real_run(
            user_id=user_id,
            operation_id=post_json["client_action_id"],
            pipeline=lambda: zr._run_add_zettel(
                body, user=user_dict, effective_user_id=user_id
            ),
            persist_requested=body.persist,
            url=body.url,
        )
    )


def _install_async_mocks(monkeypatch, zettels_routes) -> dict:
    """Stub the ops state machine + backpressure + network-side helpers
    (resolve_redirects, dedup scope) so the route's background _run task
    finalizes deterministically without hitting real Supabase / DNS.

    Also monkeypatches ``zettels_routes._run`` to a no-op so the route's
    auto-spawned ``asyncio.create_task(_run(...))`` does nothing — the
    ``_drive_bg_to_finalize`` helper drives the saved-real ``_run`` exactly
    once via ``asyncio.run``. Eliminates the Linux CI race where TestClient
    tore the per-request loop down mid-pipeline (summarize ran once via the
    orphaned bg task, then again via the helper's manual fallback).

    Returns a `captured` dict that tests inspect after `_drive_bg_to_finalize`.
    The ``_real_run`` slot holds the saved original ``_run`` for the helper.
    """
    from website.api.module_runners import summarization as runner
    from website.core import persist as persist_mod

    captured: dict = {}

    def _finalize(**kw):
        captured["called"] = True
        captured.update(kw)
        return True

    # Preserve the real _run for _drive_bg_to_finalize to invoke exactly
    # once via asyncio.run. The monkeypatched no-op below replaces the
    # symbol the route resolves at create_task time.
    captured["_real_run"] = zettels_routes._run

    async def _noop_run(
        *, user_id, operation_id, pipeline, persist_requested, url=None,
    ):
        # PR #89 commit 4 added `url=` kwarg to _run; mirror the signature
        # here so the route's auto-spawned task doesn't TypeError on the new
        # kwarg the route now passes. The no-op semantics are unchanged.
        del user_id, operation_id, pipeline, persist_requested, url
        return None

    monkeypatch.setattr(zettels_routes, "_run", _noop_run)
    monkeypatch.setattr(zettels_routes.operations_repo, "accept",
                        lambda **kw: (kw["operation_id"], True))
    monkeypatch.setattr(zettels_routes.operations_repo, "start",
                        lambda **kw: True)
    monkeypatch.setattr(zettels_routes.operations_repo, "finalize", _finalize)
    monkeypatch.setattr(zettels_routes, "check_async_backpressure",
                        AsyncMock(return_value=None))
    # Network-side helpers — without these the pipeline does a real HTTP HEAD
    # request to the test URL, hanging the bg task and producing `cancelled`
    # via TestClient teardown.
    monkeypatch.setattr(
        runner, "resolve_redirects",
        AsyncMock(side_effect=lambda url: url),
    )
    monkeypatch.setattr(runner, "normalize_url", lambda url: url)
    # Disable URL dedup gate so the pipeline runs the mocked summarize_url_bundle.
    monkeypatch.setattr(persist_mod, "get_supabase_v2_scope", lambda *_a, **_k: None)
    return captured


def _make_bundle(url: str):
    from website.features.summarization_engine.core.models import (
        DetailedSummarySection,
        IngestResult,
        SourceType,
        SummaryMetadata,
        SummaryResult,
    )

    metadata = SummaryMetadata(
        source_type=SourceType.WEB,
        url=url,
        extraction_confidence="high",
        confidence_reason="primary content extracted",
        total_tokens_used=42,
        total_latency_ms=123,
    )
    summary = SummaryResult(
        mini_title="Typed Facade",
        brief_summary="Brief facade summary.",
        detailed_summary=[
            DetailedSummarySection(heading="Why it matters", bullets=["One API path."])
        ],
        tags=["architecture/api"],
        metadata=metadata,
    )
    ingest = IngestResult(
        source_type=SourceType.WEB,
        url=url,
        original_url=url,
        raw_text="Enough extracted text for the summarizer to trust. " * 40,
        metadata={"tier_used": "primary"},
        extraction_confidence="high",
        confidence_reason="primary content extracted",
        fetched_at=datetime.now(timezone.utc),
    )
    return SimpleNamespace(summary_result=summary, ingest_result=ingest)


@pytest.fixture
def facade_client(monkeypatch):
    monkeypatch.setenv("DB_SCHEMA_VERSION", "v2")
    monkeypatch.setenv("GEMINI_API_KEYS", "stub-key-for-add-zettel-tests")

    import website.api.zettels_routes as zettels_routes
    import website.api.module_runners.summarization as runner
    from website.api import auth as auth_mod
    from website.core import persist as persist_mod

    auth_mod._jwks_client = None
    persist_mod._v2_core_repo = None
    persist_mod._v2_content_repo = None
    # ADR-3 (2026-05-22): the in-memory idempotency caches were removed; the
    # DB-backed core.operations row is the cross-worker truth for both the
    # URL and document paths.
    zettels_routes._RATE_STORE.clear()

    async def fake_require(*_args, **_kwargs):
        return None

    async def fake_consume(*_args, **_kwargs):
        return None

    monkeypatch.setattr(runner, "require_entitlement", fake_require)
    monkeypatch.setattr(runner, "consume_entitlement", fake_consume)
    monkeypatch.setattr(zettels_routes, "_gemini_client", lambda: object())

    from website.app import create_app

    app = create_app()
    return TestClient(app), zettels_routes, runner


def test_add_zettel_contract_summarizes_then_persists(facade_client, monkeypatch):
    client, _zettels_routes, runner = facade_client
    calls: list[str] = []
    seen_user_ids: list[UUID] = []

    async def fake_summarize(url, *, user_id, gemini_client, source_type=None):
        calls.append("summarize")
        seen_user_ids.append(user_id)
        return _make_bundle(url)

    async def fake_persist(result, *, user_sub=None, captured_on=None):
        calls.append("persist")
        assert user_sub == str(ZORO_AUTH_ID)
        return SimpleNamespace(
            result={**result, "captured_at": "2026-05-14"},
            file_node_id="web-typed-facade",
            supabase_node_id="00000000-0000-0000-0000-000000000222",
            file_saved=True,
            supabase_saved=True,
            supabase_duplicate=False,
            kg_user_id=str(ZORO_AUTH_ID),
        )

    monkeypatch.setattr(runner, "summarize_url_bundle", fake_summarize)
    monkeypatch.setattr(runner, "persist_summarized_result", fake_persist)
    # Disable URL dedup gate so the pipeline actually runs the mocked summarize.
    from website.core import persist as persist_mod
    monkeypatch.setattr(persist_mod, "get_supabase_v2_scope", lambda *_a, **_k: None)
    captured = _install_async_mocks(monkeypatch, _zettels_routes)

    post_json = {
        "url": "https://example.com/post",
        "client_action_id": "landing-1",
        "persist": True,
        "surface": "landing",
    }
    resp = client.post("/api/zettels/add", json=post_json)

    # PR #39 A1: route always 202s; the succeeded body lands on the
    # operations row via finalize, then GET /api/operations/{id} surfaces it.
    assert resp.status_code == 202
    _drive_bg_to_finalize(post_json, captured)
    assert calls == ["summarize", "persist"]
    assert seen_user_ids == [ZORO_AUTH_ID]
    assert captured.get("target") == "succeeded"
    body = captured.get("response") or {}
    assert body["status"] == "succeeded"
    assert body["operation_id"] == "landing-1"
    assert body["summary"]["title"] == "Typed Facade"
    assert body["summary"]["source_url"] == "https://example.com/post"
    assert body["persistence"] == {
        "requested": True,
        "persisted": True,
        "file_store": True,
        "supabase": True,
        "duplicate": False,
    }
    assert body["node_id"] == "web-typed-facade"
    assert body["workspace_zettel_id"] == "00000000-0000-0000-0000-000000000222"
    assert body["quality"]["confidence"] == "high"


def test_add_zettel_uses_authenticated_uuid_and_can_skip_persistence(
    facade_client, monkeypatch
):
    client, _zettels_routes, runner = facade_client
    user_id = uuid4()
    seen: list[UUID] = []
    persisted: list[bool] = []

    async def fake_user():
        return {"sub": str(user_id), "email": "person@example.test"}

    async def fake_summarize(url, *, user_id, gemini_client, source_type=None):
        seen.append(user_id)
        return _make_bundle(url)

    async def fake_persist(*_args, **_kwargs):
        persisted.append(True)
        raise AssertionError("persist should not run when persist=false")

    from website.api.auth import get_optional_user

    client.app.dependency_overrides[get_optional_user] = fake_user
    monkeypatch.setattr(runner, "summarize_url_bundle", fake_summarize)
    monkeypatch.setattr(runner, "persist_summarized_result", fake_persist)
    from website.core import persist as persist_mod
    monkeypatch.setattr(persist_mod, "get_supabase_v2_scope", lambda *_a, **_k: None)
    captured = _install_async_mocks(monkeypatch, _zettels_routes)

    post_json = {
        "url": "https://example.com/no-write",
        "client_action_id": "home-1",
        "persist": False,
        "surface": "home",
    }
    resp = client.post(
        "/api/zettels/add",
        json=post_json,
        headers={"Authorization": "Bearer test"},
    )

    assert resp.status_code == 202
    _drive_bg_to_finalize(post_json, captured, user_dict={"sub": str(user_id)})
    assert seen == [user_id]
    assert persisted == []
    body = captured.get("response") or {}
    assert body["persistence"]["requested"] is False
    assert body["persistence"]["persisted"] is False
    assert body["node_id"] is None


# Phase 5 (async-ops redesign): two idempotency tests deleted here.
# - test_add_zettel_idempotency_reuses_original_response: pinned the legacy
#   _IN_FLIGHT per-worker dedup contract. Replacement coverage lives at
#   tests/integration/v2/test_ops_state_machine.py::test_accept_idempotent_returns_existing_when_active
#   (DB-level) and tests/unit/website/test_async_operations_transport.py::
#   test_accept_returns_existing_op_id_when_not_new (route level).
# - test_add_zettel_idempotency_rejects_same_key_different_request: pinned the
#   legacy 409 same-key/different-body rejection. The new ops.accept contract
#   returns the canonical op id (200/202) instead of 409; covered by
#   test_async_operations_transport.py::test_accept_honors_idempotency_key_header
#   and the cross-user/state-machine isolation tests in test_ops_state_machine.py.


def test_add_zettel_always_async_returns_202_then_succeeded(facade_client, monkeypatch):
    """PR #39 A1 + A2: `mode` was retired. The route is universally async —
    always 202 with the summary landing on the operations row via finalize.
    This test replaces ``test_add_zettel_auto_mode_runs_sync_when_async_not_durable``
    which pinned the deprecated `mode:auto` branch."""
    client, zettels_routes, runner = facade_client
    calls: list[str] = []

    async def fake_summarize(url, *, user_id, gemini_client, source_type=None):
        calls.append("summarize")
        return _make_bundle(url)

    async def fake_persist(result, *, user_sub=None, captured_on=None):
        calls.append("persist")
        return SimpleNamespace(
            result=result,
            file_node_id="web-sync-auto",
            supabase_node_id="00000000-0000-0000-0000-000000000222",
            file_saved=True,
            supabase_saved=True,
            supabase_duplicate=False,
            kg_user_id=user_sub,
        )

    monkeypatch.setattr(runner, "summarize_url_bundle", fake_summarize)
    monkeypatch.setattr(runner, "persist_summarized_result", fake_persist)
    from website.core import persist as persist_mod
    monkeypatch.setattr(persist_mod, "get_supabase_v2_scope", lambda *_a, **_k: None)
    captured = _install_async_mocks(monkeypatch, zettels_routes)

    post_json = {
        "url": "https://example.com/auto-sync",
        "client_action_id": "auto-sync-1",
        "persist": True,
        "surface": "home",
    }
    resp = client.post("/api/zettels/add", json=post_json)

    assert resp.status_code == 202
    _drive_bg_to_finalize(post_json, captured)
    body = captured.get("response") or {}
    assert body["status"] == "succeeded"
    assert calls == ["summarize", "persist"]


def test_add_zettel_problem_detail_failure_lands_on_operations_row(
    facade_client, monkeypatch
):
    """PR #39 A1: a synchronous RuntimeError in the pipeline used to surface
    as an inline 500 + RFC 9457 problem+json. Now the route 202s and the
    failure body lands on the operations row's `response`/`error` column via
    ``_run -> finalize(target='failed')``. GET /api/operations/{id} returns
    that body to the client. The structured shape is preserved.

    PR #89 commit C (2026-05-25): the previous "generic exception → error is
    None" contract is RETIRED. Any unmapped exception now lands a structured
    RFC 9457 ``internal_error`` body (closes the ``code=null`` cohort that the
    2026-05-25 Naruto live repro hit with ``FileNotFoundError``). OWASP
    API8:2023: the wire-side ``error.detail`` MUST NOT carry the exception
    class or message — those reach Slack via ``maybe_fire_app_error``, not the
    client. Engineer-facing exception text remains on the inner
    ``quality.confidence_reason`` field for support triage."""
    client, zettels_routes, runner = facade_client

    async def fake_summarize(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(runner, "summarize_url_bundle", fake_summarize)
    from website.core import persist as persist_mod
    monkeypatch.setattr(persist_mod, "get_supabase_v2_scope", lambda *_a, **_k: None)
    captured = _install_async_mocks(monkeypatch, zettels_routes)

    post_json = {
        "url": "https://example.com/fail",
        "client_action_id": "fail-1",
        "persist": True,
        "surface": "landing",
    }
    resp = client.post("/api/zettels/add", json=post_json)

    assert resp.status_code == 202
    _drive_bg_to_finalize(post_json, captured)

    assert captured.get("target") == "failed"
    response_body = captured.get("response") or {}
    # The response body itself carries the failed AddZettelResponse shape.
    assert response_body.get("status") == "failed"
    quality = response_body.get("quality") or {}
    assert quality.get("confidence") == "failed"
    # Engineer-debug field: confidence_reason still carries the raw exception
    # message — that's the support-triage field and lives off the wire path.
    assert "boom" in str(quality.get("confidence_reason") or "")
    # PR #89 commit C: the operations row's ``error`` column is now ALWAYS a
    # structured RFC 9457 problem body for any unmapped exception. The
    # ``code=null`` cohort (4/8 in the 24h before the fix) is closed.
    error = captured.get("error")
    assert error is not None, "error must be structured, not None (PR #89 commit C)"
    assert error.get("code") == "internal_error"
    assert error.get("status") == 500
    assert error.get("operation_id") == "fail-1"
    # OWASP API8:2023: wire body MUST NOT leak exception class or message.
    import json as _json
    body_text = _json.dumps(error)
    assert "boom" not in body_text
    assert "RuntimeError" not in body_text
    # The original URL is persisted for forensics (PR #89 commit 4).
    assert error.get("url") == "https://example.com/fail"


def test_add_zettel_validation_failure_is_problem_json(facade_client):
    client, _zettels_routes, _runner = facade_client

    resp = client.post(
        "/api/zettels/add",
        json={
            "url": "not-a-url",
            "client_action_id": "invalid-1",
            "persist": True,
            "surface": "landing",
            "mode": "sync",
        },
    )

    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["type"].endswith("/errors/invalid-add-zettel-request")
    assert body["status"] == 422
    assert body["instance"] == "/api/zettels/add"
