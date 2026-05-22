"""Document Add Zettel v2 facade tests.

ADR-3 (2026-05-22) CONTRACT CHANGE: ``POST /api/zettels/add/document`` is now
async-ops — it returns ``202 Accepted`` + ``status_url`` and spawns a
background ``_run`` worker; the client polls ``GET /api/operations/{id}``.
The per-process in-memory ``_IDEMPOTENCY_CACHE`` / ``_OPERATIONS`` dicts were
removed (they could not coalesce duplicate uploads across gunicorn workers);
idempotency now lives in the durable ``core.operations`` row.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

ZORO_AUTH_ID = UUID("a57e1f2f-7d89-4cd7-ae39-72c440ed4b4e")


@pytest.fixture
def document_client(monkeypatch):
    monkeypatch.setenv("DB_SCHEMA_VERSION", "v2")
    monkeypatch.setenv("GEMINI_API_KEYS", "stub-key-for-document-tests")

    import website.api.zettels_routes as zettels_routes
    from unittest.mock import AsyncMock
    from website.api import auth as auth_mod

    auth_mod._jwks_client = None
    zettels_routes._RATE_STORE.clear()
    # ADR-3: stub the ops state machine + backpressure so the route's accept
    # path 202s deterministically without hitting real Supabase.
    monkeypatch.setattr(
        zettels_routes.operations_repo, "accept",
        lambda **kw: (kw["operation_id"], True),
    )
    monkeypatch.setattr(
        zettels_routes.operations_repo, "start", lambda **kw: True,
    )
    monkeypatch.setattr(
        zettels_routes.operations_repo, "finalize", lambda **kw: True,
    )
    monkeypatch.setattr(
        zettels_routes, "check_async_backpressure", AsyncMock(return_value=None),
    )

    from website.app import create_app

    return TestClient(create_app()), zettels_routes


def test_document_add_zettel_posts_multipart_returns_202(document_client, monkeypatch):
    """ADR-3: the document route 202s + emits a poll ``status_url``. The
    summary lands on the operations row via the background ``_run`` finalize."""
    client, zettels_routes = document_client

    response = client.post(
        "/api/zettels/add/document",
        data={
            "client_action_id": "doc-1",
            "persist": "true",
            "surface": "landing",
        },
        files={
            "file": (
                "research.md",
                b"# Research\n\nEnough document text to process through the facade.",
                "text/markdown",
            )
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "accepted"
    assert body["operation_id"] == "doc-1"
    assert body["status_url"] == "/api/operations/doc-1"
    assert response.headers["Location"] == "/api/operations/doc-1"
    assert response.headers["Retry-After"] == "2"


def test_document_add_zettel_idempotency_key_canonicalizes_op(document_client):
    """ADR-3: a duplicate POST whose ``accept`` returns ``is_new=False``
    resolves to the existing canonical operation_id rather than spawning a
    second worker. The 202 body + Location header agree on the canonical id."""
    client, zettels_routes = document_client

    seen_is_new: list[bool] = []

    def _accept(**kw):
        is_new = not seen_is_new
        seen_is_new.append(is_new)
        return (kw["operation_id"], is_new)

    import pytest as _pytest  # noqa: F401 — keep import local
    zettels_routes.operations_repo.accept = _accept

    form = {"client_action_id": "same-doc", "persist": "true", "surface": "landing"}
    upload = {"file": ("doc.txt", b"same content with enough characters", "text/plain")}

    first = client.post("/api/zettels/add/document", data=form, files=upload)
    second = client.post("/api/zettels/add/document", data=form, files=upload)

    assert first.status_code == 202
    assert second.status_code == 202
    # Both resolve to the same canonical operation_id.
    assert first.json()["operation_id"] == "same-doc"
    assert second.json()["operation_id"] == "same-doc"
    assert second.json()["status_url"] == "/api/operations/same-doc"
    assert seen_is_new == [True, False]


def test_document_add_zettel_store_unavailable_returns_503(document_client):
    """ADR-2 fail-closed: when ``operations_repo.accept`` returns ``None`` the
    document route returns a retriable 503 instead of spawning untrackable
    work."""
    client, zettels_routes = document_client
    zettels_routes.operations_repo.accept = lambda **kw: None

    response = client.post(
        "/api/zettels/add/document",
        data={"client_action_id": "doc-503", "persist": "true", "surface": "landing"},
        files={"file": ("doc.txt", b"enough document text here", "text/plain")},
    )

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"].endswith("/errors/operation-store-unavailable")
    assert body["retryable"] is True


def test_document_add_zettel_rejects_large_upload(document_client):
    client, _zettels_routes = document_client

    response = client.post(
        "/api/zettels/add/document",
        data={"client_action_id": "large-doc", "persist": "true", "surface": "landing"},
        files={"file": ("large.txt", b"x" * (10 * 1024 * 1024 + 1), "text/plain")},
    )

    assert response.status_code == 413
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"].endswith("/errors/document-too-large")


@pytest.mark.asyncio
async def test_document_runner_persists_v2_document_payload(monkeypatch):
    import website.api.module_runners.summarization as runner
    import website.features.summarization_engine.summarization as summarization_registry
    from website.features.summarization_engine.core.models import (
        DetailedSummarySection,
        SourceType,
        SummaryMetadata,
        SummaryResult,
    )

    class FakeSummarizer:
        def __init__(self, *_args, **_kwargs):
            pass

        async def summarize(self, ingest):
            return SummaryResult(
                mini_title="Document Runner",
                brief_summary="A document enters the v2 Add Zettel path.",
                tags=["type/document", "topic/upload"],
                detailed_summary=[
                    DetailedSummarySection(
                        heading="Document flow",
                        bullets=["Multipart bytes become a canonical zettel."],
                    )
                ],
                metadata=SummaryMetadata(
                    source_type=SourceType.DOCUMENT,
                    url=ingest.url,
                    extraction_confidence="high",
                    confidence_reason="document_upload_text_extracted",
                    total_tokens_used=17,
                    total_latency_ms=23,
                ),
            )

    captured: dict[str, object] = {}

    async def fake_require(*_args, **_kwargs):
        return None

    async def fake_persist(payload, *, user_sub=None, captured_on=None):
        captured["payload"] = payload
        captured["user_sub"] = user_sub
        return SimpleNamespace(
            result=payload,
            file_node_id="doc-document-runner",
            supabase_node_id="00000000-0000-0000-0000-000000000444",
            file_saved=False,
            supabase_saved=True,
            supabase_duplicate=False,
            kg_user_id=user_sub,
        )

    monkeypatch.setattr(runner, "require_entitlement", fake_require)
    monkeypatch.setattr(runner, "persist_summarized_result", fake_persist)
    monkeypatch.setattr(summarization_registry, "get_summarizer", lambda _source: FakeSummarizer)

    result = await runner.run_add_document_pipeline(
        filename="runner.md",
        content=(
            b"# Runner\n\nDocument upload text that is long enough for extraction "
            b"and should be preserved as raw_text for v2 chunking."
        ),
        content_type="text/markdown",
        client_action_id="runner-doc-1",
        persist=True,
        user=None,
        effective_user_id=ZORO_AUTH_ID,
        gemini_client_factory=lambda: object(),
    )

    payload = captured["payload"]
    assert captured["user_sub"] == str(ZORO_AUTH_ID)
    assert payload["source_type"] == "document"
    assert payload["source_url"] == "file-upload://runner.md"
    assert payload["tags"] == ["type/document", "topic/upload"]
    assert "raw_text" in payload
    assert "Runner" in payload["raw_text"]
    assert result["persistence"]["supabase"] is True
    assert result["workspace_zettel_id"] == "00000000-0000-0000-0000-000000000444"
