"""H2/C4 route-level integration — content confidence gate on /api/v2/summarize.

ADR-3 (2026-05-22) CONTRACT CHANGE: ``POST /api/v2/summarize`` is now async-ops.
It returns ``202 Accepted`` + ``status_url`` and delegates to the shared
``_accept_and_spawn`` worker; the client polls ``GET /api/operations/{id}``.

The confidence gate still fires inside the runner via ``grade_confidence``.
Under the async-ops contract a soft "insufficient" grade does NOT raise — the
runner finalizes a ``succeeded`` operation whose body carries
``quality.confidence == "insufficient"``. (Only hard exceptions —
``UnsupportedVideoError`` / ``ExtractionConfidenceError`` raised mid-pipeline —
finalize as ``failed``.) The frontend keys the refusal UI off
``quality.confidence`` in the polled body.

These tests intercept the background ``operations_repo.finalize`` write to
assert the grading contract on the canonical operations row — the body the
GET endpoint subsequently returns:

  * raw_text_len < 500 AND tier_used == "metadata_only" -> finalize(succeeded)
    with ``quality.confidence == "insufficient"``.
  * raw_text_len >= 1500 AND non-metadata tier -> finalize(succeeded) with
    ``quality.confidence == "high"``.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from website.features.summarization_engine.api.routes import router
from website.features.summarization_engine.core.models import (
    IngestResult,
    SourceType,
    SummaryMetadata,
)


def _summary_result():
    metadata = SummaryMetadata(
        source_type=SourceType.YOUTUBE,
        url="https://youtube.com/watch?v=abc",
        extraction_confidence="high",
        confidence_reason="ok",
        total_tokens_used=100,
        total_latency_ms=200,
    )
    from website.features.summarization_engine.core.models import (
        DetailedSummarySection,
        SummaryResult,
    )
    return SummaryResult(
        metadata=metadata,
        mini_title="T",
        brief_summary="B.",
        detailed_summary=[
            DetailedSummarySection(heading="Why", bullets=["bullet"])
        ],
        tags=["t1"],
    )


def _ingest(raw_text: str, tier_used: str) -> IngestResult:
    return IngestResult(
        source_type=SourceType.YOUTUBE,
        url="https://youtube.com/watch?v=abc",
        original_url="https://youtube.com/watch?v=abc",
        raw_text=raw_text,
        sections={},
        metadata={"tier_used": tier_used},
        extraction_confidence="high",
        confidence_reason="ok",
        fetched_at=datetime.now(timezone.utc),
    )


@pytest.fixture(autouse=True)
def _stub_entitlement_gate(monkeypatch):
    """/api/v2/summarize delegates to the shared add-zettel runner so the one
    dedup gate governs it. Entitlement + engine live in the runner module;
    patch there. No Supabase env -> v2 scope is None so the fresh path runs.
    """
    async def _allow(*_args, **_kwargs):
        return None
    monkeypatch.setattr(
        "website.api.module_runners.summarization.require_entitlement",
        _allow,
    )
    monkeypatch.setattr(
        "website.core.persist.get_supabase_v2_scope",
        lambda *_a, **_k: None,
    )


def _client_and_captured(monkeypatch) -> tuple[TestClient, dict]:
    """Build a v2-router-only app + stub the ops state machine so the
    background ``_run`` worker finalizes deterministically. Returns the
    TestClient and the ``captured`` dict recording the finalize call."""
    from website.api import zettels_routes

    captured: dict = {}

    def _finalize(**kw):
        captured["called"] = True
        captured.update(kw)
        return True

    monkeypatch.setattr(zettels_routes.operations_repo, "accept",
                        lambda **kw: (kw["operation_id"], True))
    monkeypatch.setattr(zettels_routes.operations_repo, "start",
                        lambda **kw: True)
    monkeypatch.setattr(zettels_routes.operations_repo, "finalize", _finalize)

    # Network-side helpers — without these the pipeline does a real HTTP HEAD
    # to the test URL, hanging the bg task into a `cancelled` finalize via
    # TestClient teardown.
    from website.api.module_runners import summarization as runner
    monkeypatch.setattr(runner, "resolve_redirects",
                        AsyncMock(side_effect=lambda url: url))
    monkeypatch.setattr(runner, "normalize_url", lambda url: url)

    app = FastAPI()
    app.include_router(router)
    return TestClient(app), captured


def _drive_bg_to_finalize(url: str, persist: bool, captured: dict, *, settle_s=2.5):
    """Mirror of the URL-path helper: poll for the auto-driven bg task, else
    run the v2-summarize pipeline through ``_run`` once in the test thread."""
    import time
    from website.api import zettels_routes as zr

    deadline = time.time() + settle_s
    while time.time() < deadline:
        if captured.get("called"):
            return
        time.sleep(0.025)

    operation_id = f"v2-summarize-{url}"
    user_id = zr._effective_user_id(None)
    body = zr.AddZettelRequest(
        url=url, client_action_id=operation_id, persist=persist, surface="landing",
    )
    asyncio.run(
        zr._run(
            user_id=user_id,
            operation_id=operation_id,
            pipeline=lambda: zr._run_add_zettel(
                body, user={"sub": str(user_id)}, effective_user_id=user_id
            ),
            persist_requested=persist,
        )
    )


@patch("website.api.module_runners.summarization.default_gemini_client")
@patch("website.api.module_runners.summarization.summarize_url_bundle")
def test_insufficient_context_finalizes_with_insufficient_confidence(
    mock_bundle, mock_client, monkeypatch
):
    bundle = SimpleNamespace(
        ingest_result=_ingest("x" * 300, "metadata_only"),
        summary_result=_summary_result(),
    )

    async def _ret(*a, **kw):
        return bundle
    mock_bundle.side_effect = _ret
    mock_client.return_value = object()

    client, captured = _client_and_captured(monkeypatch)
    resp = client.post(
        "/api/v2/summarize", json={"url": "https://youtube.com/watch?v=abc"}
    )
    # ADR-3: route accepts the operation and 202s immediately.
    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "accepted"

    _drive_bg_to_finalize("https://youtube.com/watch?v=abc", False, captured)

    # The soft insufficient-context grade does NOT raise — the operation
    # finalizes `succeeded` but the body carries quality.confidence=insufficient.
    assert captured.get("target") == "succeeded"
    response_body = captured.get("response") or {}
    quality = response_body.get("quality") or {}
    assert quality.get("confidence") == "insufficient"
    signals = quality.get("quality_signals") or {}
    assert signals.get("input_chars") == 300
    assert signals.get("source_tier") == "metadata_only"


@patch("website.api.module_runners.summarization.default_gemini_client")
@patch("website.api.module_runners.summarization.summarize_url_bundle")
def test_high_confidence_finalizes_succeeded(mock_bundle, mock_client, monkeypatch):
    bundle = SimpleNamespace(
        ingest_result=_ingest("x" * 2000, "transcript_api_direct"),
        summary_result=_summary_result(),
    )

    async def _ret(*a, **kw):
        return bundle
    mock_bundle.side_effect = _ret
    mock_client.return_value = object()

    client, captured = _client_and_captured(monkeypatch)
    resp = client.post(
        "/api/v2/summarize", json={"url": "https://youtube.com/watch?v=abc"}
    )
    assert resp.status_code == 202, resp.text

    _drive_bg_to_finalize("https://youtube.com/watch?v=abc", False, captured)

    assert captured.get("target") == "succeeded"
    response_body = captured.get("response") or {}
    assert response_body.get("status") == "succeeded"
    assert (response_body.get("quality") or {}).get("confidence") == "high"
