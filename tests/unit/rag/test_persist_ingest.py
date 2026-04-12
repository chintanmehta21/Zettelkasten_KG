from datetime import date
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_persist_supabase_node_ingests_chunks_when_flag_enabled(monkeypatch) -> None:
    from website.experimental_features.nexus.service import persist

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
    ingest_calls = {}

    monkeypatch.setattr(persist, "_generate_node_embedding", lambda payload: None)
    monkeypatch.setattr(persist, "_build_supabase_node_payload", lambda **kwargs: type("Node", (), {"id": "web-article"})())
    monkeypatch.setattr(persist, "_create_semantic_links", lambda **kwargs: None)
    monkeypatch.setattr(persist, "_schedule_entity_extraction", lambda **kwargs: None)
    monkeypatch.setattr(persist, "get_settings", lambda: type("Settings", (), {"rag_chunks_enabled": True})())

    async def fake_ingest(*, payload, user_uuid, node_id):
        ingest_calls["payload"] = payload
        ingest_calls["user_uuid"] = user_uuid
        ingest_calls["node_id"] = node_id
        return 3

    monkeypatch.setattr(persist, "_maybe_ingest_rag_chunks", fake_ingest)

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
async def test_maybe_ingest_rag_chunks_noops_when_flag_disabled(monkeypatch) -> None:
    from website.experimental_features.nexus.service import persist

    monkeypatch.setattr(persist, "get_settings", lambda: type("Settings", (), {"rag_chunks_enabled": False})())

    count = await persist._maybe_ingest_rag_chunks(
        payload={"raw_text": "hello", "source_type": "web", "title": "Title"},
        user_uuid=uuid4(),
        node_id="node-1",
    )

    assert count == 0
