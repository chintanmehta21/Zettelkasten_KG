"""Tests for the canonical RAG chunk ingest hook."""

from __future__ import annotations

from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_ingest_node_chunks_returns_zero_for_empty_raw_text() -> None:
    from website.features.rag_pipeline.ingest.hook import ingest_node_chunks

    count = await ingest_node_chunks(
        payload={"raw_text": "", "summary": "", "title": "Empty"},
        user_uuid=uuid4(),
        node_id="node-empty",
    )

    assert count == 0


@pytest.mark.asyncio
async def test_ingest_node_chunks_calls_upsert_with_produced_chunks(monkeypatch) -> None:
    from website.features.rag_pipeline.ingest import hook

    produced_chunks = [object(), object(), object()]
    captured_chunk_kwargs: dict = {}

    class _Chunker:
        def __init__(self, *args, **kwargs):
            pass

        def chunk(self, **kwargs):
            captured_chunk_kwargs.update(kwargs)
            return produced_chunks

    class _Embeddings:
        def __init__(self, *args, **kwargs):
            pass

    class _Embedder:
        def __init__(self, *args, **kwargs):
            pass

    captured: dict = {}

    async def _fake_upsert(*, user_id, node_id, chunks, embedder):
        captured["user_id"] = user_id
        captured["node_id"] = node_id
        captured["chunks"] = chunks
        return len(chunks)

    monkeypatch.setattr(
        "website.features.rag_pipeline.adapters.gemini_chonkie.GeminiChonkieEmbeddings",
        _Embeddings,
    )
    monkeypatch.setattr(
        "website.features.rag_pipeline.adapters.pool_factory.get_embedding_pool",
        lambda: object(),
    )
    monkeypatch.setattr(
        "website.features.rag_pipeline.ingest.chunker.ZettelChunker",
        _Chunker,
    )
    monkeypatch.setattr(
        "website.features.rag_pipeline.ingest.embedder.ChunkEmbedder",
        _Embedder,
    )
    monkeypatch.setattr(
        "website.features.rag_pipeline.ingest.upsert.upsert_chunks",
        _fake_upsert,
    )

    user_uuid = uuid4()
    count = await hook.ingest_node_chunks(
        payload={
            "raw_text": "full article body",
            "title": "Title",
            "source_type": "web",
            "tags": ["topic/ai"],
            "raw_metadata": {"author": "Ada"},
        },
        user_uuid=user_uuid,
        node_id="node-web-1",
    )

    assert count == 3
    assert captured["user_id"] == user_uuid
    assert captured["node_id"] == "node-web-1"
    assert captured["chunks"] is produced_chunks
    assert captured_chunk_kwargs["raw_text"] == "full article body"


@pytest.mark.asyncio
async def test_ingest_node_chunks_prefers_summary_over_stub_youtube_body(monkeypatch) -> None:
    from website.features.rag_pipeline.ingest import hook

    captured_chunk_kwargs: dict = {}

    class _Chunker:
        def __init__(self, *args, **kwargs):
            pass

        def chunk(self, **kwargs):
            captured_chunk_kwargs.update(kwargs)
            return [object()]

    monkeypatch.setattr(
        "website.features.rag_pipeline.adapters.gemini_chonkie.GeminiChonkieEmbeddings",
        lambda *a, **kw: object(),
    )
    monkeypatch.setattr(
        "website.features.rag_pipeline.adapters.pool_factory.get_embedding_pool",
        lambda: object(),
    )
    monkeypatch.setattr(
        "website.features.rag_pipeline.ingest.chunker.ZettelChunker",
        _Chunker,
    )
    monkeypatch.setattr(
        "website.features.rag_pipeline.ingest.embedder.ChunkEmbedder",
        lambda *a, **kw: object(),
    )
    
    async def _fake_upsert(**kwargs):
        return 1

    monkeypatch.setattr(
        "website.features.rag_pipeline.ingest.upsert.upsert_chunks",
        _fake_upsert,
    )

    count = await hook.ingest_node_chunks(
        payload={
            "raw_text": "## Transcript\n\n(Transcript not available for this video)",
            "summary": "Transformer attention replaces recurrence with self-attention and scales better on long-range dependencies.",
            "title": "Attention Is All You Need",
            "source_type": "youtube",
        },
        user_uuid=uuid4(),
        node_id="yt-attention",
    )

    assert count == 1
    assert captured_chunk_kwargs["raw_text"] == (
        "Transformer attention replaces recurrence with self-attention and scales better on long-range dependencies."
    )


@pytest.mark.asyncio
async def test_ingest_node_chunks_swallows_upsert_failures(monkeypatch) -> None:
    from website.features.rag_pipeline.ingest import hook

    class _Chunker:
        def __init__(self, *args, **kwargs):
            pass

        def chunk(self, **kwargs):
            return [object()]

    async def _boom(**_kwargs):
        raise RuntimeError("pgvector connection lost")

    monkeypatch.setattr(
        "website.features.rag_pipeline.adapters.gemini_chonkie.GeminiChonkieEmbeddings",
        lambda *a, **kw: object(),
    )
    monkeypatch.setattr(
        "website.features.rag_pipeline.adapters.pool_factory.get_embedding_pool",
        lambda: object(),
    )
    monkeypatch.setattr(
        "website.features.rag_pipeline.ingest.chunker.ZettelChunker",
        _Chunker,
    )
    monkeypatch.setattr(
        "website.features.rag_pipeline.ingest.embedder.ChunkEmbedder",
        lambda *a, **kw: object(),
    )
    monkeypatch.setattr(
        "website.features.rag_pipeline.ingest.upsert.upsert_chunks",
        _boom,
    )

    count = await hook.ingest_node_chunks(
        payload={"raw_text": "body", "title": "T", "source_type": "web"},
        user_uuid=uuid4(),
        node_id="node-web-2",
    )

    assert count == 0
