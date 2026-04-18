"""Integration between nexus persist and the canonical RAG ingest hook."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_persist_supabase_node_invokes_ingest_when_flag_enabled(monkeypatch) -> None:
    from website.experimental_features.nexus.service import persist
    from website.features.rag_pipeline.ingest import hook as rag_hook

    class _Repo:
        def node_exists(self, *_args, **_kwargs):
            return False

        def add_node(self, *_args, **_kwargs):
            return None

    payload = {
        "title": "Long-form article",
        "source_type": "web",
        "source_url": "https://example.com/article",
        "summary": "Detailed summary",
        "brief_summary": "Brief summary",
        "raw_text": "Original extracted content",
        "raw_metadata": {"author": "Ada"},
        "tags": ["source/web", "topic/ai"],
    }
    user_uuid = uuid4()
    ingest_calls: dict = {}

    monkeypatch.setattr(persist, "_generate_node_embedding", lambda payload: None)
    monkeypatch.setattr(
        persist,
        "_build_supabase_node_payload",
        lambda **kwargs: type("Node", (), {"id": "web-article"})(),
    )
    monkeypatch.setattr(persist, "_create_semantic_links", lambda **kwargs: None)
    monkeypatch.setattr(persist, "_schedule_entity_extraction", lambda **kwargs: None)
    monkeypatch.setattr(
        persist,
        "get_settings",
        lambda: type("Settings", (), {"rag_chunks_enabled": True})(),
    )

    async def fake_ingest(*, payload, user_uuid, node_id):
        ingest_calls["payload"] = payload
        ingest_calls["user_uuid"] = user_uuid
        ingest_calls["node_id"] = node_id
        return 3

    monkeypatch.setattr(rag_hook, "ingest_node_chunks", fake_ingest)

    node_id, saved, duplicate = await persist._persist_supabase_node(
        payload=payload,
        repo=_Repo(),
        kg_user_id=str(user_uuid),
        captured_on=date.today(),
        brief_summary="Brief summary",
        detailed_summary="Detailed summary",
    )

    assert (node_id, saved, duplicate) == ("web-article", True, False)
    assert ingest_calls["node_id"] == "web-article"
    assert ingest_calls["user_uuid"] == user_uuid


@pytest.mark.asyncio
async def test_persist_supabase_node_skips_ingest_when_flag_disabled(monkeypatch) -> None:
    from website.experimental_features.nexus.service import persist
    from website.features.rag_pipeline.ingest import hook as rag_hook

    class _Repo:
        def node_exists(self, *_args, **_kwargs):
            return False

        def add_node(self, *_args, **_kwargs):
            return None

    called = {"count": 0}

    async def should_not_run(**_kwargs):
        called["count"] += 1
        return 0

    monkeypatch.setattr(persist, "_generate_node_embedding", lambda payload: None)
    monkeypatch.setattr(
        persist,
        "_build_supabase_node_payload",
        lambda **kwargs: type("Node", (), {"id": "web-article"})(),
    )
    monkeypatch.setattr(persist, "_create_semantic_links", lambda **kwargs: None)
    monkeypatch.setattr(persist, "_schedule_entity_extraction", lambda **kwargs: None)
    monkeypatch.setattr(
        persist,
        "get_settings",
        lambda: type("Settings", (), {"rag_chunks_enabled": False})(),
    )
    monkeypatch.setattr(rag_hook, "ingest_node_chunks", should_not_run)

    await persist._persist_supabase_node(
        payload={
            "title": "T",
            "source_type": "web",
            "source_url": "https://example.com/x",
            "summary": "s",
            "brief_summary": "b",
            "raw_text": "body",
        },
        repo=_Repo(),
        kg_user_id=str(uuid4()),
        captured_on=date.today(),
        brief_summary="b",
        detailed_summary="s",
    )

    assert called["count"] == 0
