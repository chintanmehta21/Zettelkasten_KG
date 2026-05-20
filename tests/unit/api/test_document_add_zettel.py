"""Document Add Zettel v2 facade tests."""

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
    from website.api import auth as auth_mod

    auth_mod._jwks_client = None
    # Phase 5 (async-ops redesign): _IN_FLIGHT was deleted along with the
    # per-worker in-memory async mirror; the document path uses only
    # _IDEMPOTENCY_CACHE + _OPERATIONS (synchronous-only result cache).
    zettels_routes._IDEMPOTENCY_CACHE.clear()
    zettels_routes._OPERATIONS.clear()
    zettels_routes._RATE_STORE.clear()

    from website.app import create_app

    return TestClient(create_app()), zettels_routes


def test_document_add_zettel_posts_multipart_to_v2_facade(document_client, monkeypatch):
    client, zettels_routes = document_client
    seen: dict[str, object] = {}

    async def fake_run_add_document_pipeline(**kwargs):
        seen.update(kwargs)
        return {
            "status": "succeeded",
            "operation_id": kwargs["client_action_id"],
            "summary": {
                "title": "Uploaded Research Brief",
                "summary": "## Key Ideas\n\n- It works.",
                "brief_summary": "It works.",
                "detailed_summary": "## Key Ideas\n\n- It works.",
                "tags": ["type/document", "topic/retrieval"],
                "source_type": "document",
                "source_url": "file-upload://research.md",
                "one_line_summary": "It works.",
                "tokens_used": 9,
                "latency_ms": 12,
                "metadata": {"raw_metadata": {"filename": "research.md"}},
            },
            "persistence": {
                "requested": True,
                "persisted": True,
                "file_store": False,
                "supabase": True,
                "duplicate": False,
            },
            "quality": {
                "confidence": "high",
                "confidence_reason": None,
                "quality_signals": {"input_chars": 120, "source_tier": ""},
            },
            "node_id": "doc-uploaded-research-brief",
            "workspace_zettel_id": "00000000-0000-0000-0000-000000000333",
            "status_url": None,
        }

    monkeypatch.setattr(
        zettels_routes,
        "run_add_document_pipeline",
        fake_run_add_document_pipeline,
    )

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

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["summary"]["source_type"] == "document"
    assert body["persistence"]["supabase"] is True
    assert seen["filename"] == "research.md"
    assert seen["content_type"] == "text/markdown"
    assert seen["client_action_id"] == "doc-1"
    assert seen["effective_user_id"] == ZORO_AUTH_ID
    assert seen["persist"] is True


def test_document_add_zettel_idempotency_reuses_response(document_client, monkeypatch):
    client, zettels_routes = document_client
    calls: list[bytes] = []

    async def fake_run_add_document_pipeline(**kwargs):
        calls.append(kwargs["content"])
        return {
            "status": "succeeded",
            "operation_id": kwargs["client_action_id"],
            "summary": {
                "title": "Doc",
                "summary": "Summary",
                "brief_summary": "Summary",
                "detailed_summary": "Summary",
                "tags": ["type/document"],
                "source_type": "document",
                "source_url": "file-upload://doc.txt",
                "one_line_summary": "Summary",
                "tokens_used": 1,
                "latency_ms": 1,
                "metadata": {},
            },
            "persistence": {
                "requested": True,
                "persisted": False,
                "file_store": False,
                "supabase": False,
                "duplicate": False,
            },
            "quality": {"confidence": "high", "confidence_reason": None, "quality_signals": {}},
            "node_id": None,
            "workspace_zettel_id": None,
            "status_url": None,
        }

    monkeypatch.setattr(zettels_routes, "run_add_document_pipeline", fake_run_add_document_pipeline)
    form = {"client_action_id": "same-doc", "persist": "true", "surface": "landing"}
    upload = {"file": ("doc.txt", b"same content with enough characters", "text/plain")}

    first = client.post("/api/zettels/add/document", data=form, files=upload)
    second = client.post("/api/zettels/add/document", data=form, files=upload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    assert len(calls) == 1


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
