from unittest.mock import MagicMock

import pytest

from website.features.rag_pipeline.ingest.embedder import ChunkEmbedder


@pytest.mark.asyncio
async def test_embed_returns_768d_vectors() -> None:
    fake_pool = MagicMock()
    fake_response = MagicMock()
    fake_response.embeddings = [MagicMock(values=[0.0] * 768) for _ in range(3)]
    fake_pool.embed_content.return_value = fake_response

    embedder = ChunkEmbedder(pool=fake_pool)
    vectors = await embedder.embed(["one", "two", "three"])

    assert len(vectors) == 3
    assert len(vectors[0]) == 768


@pytest.mark.asyncio
async def test_embed_batches_into_chunks_of_32() -> None:
    fake_pool = MagicMock()
    calls = []

    def _capture(*, contents, config):
        calls.append(len(contents))
        response = MagicMock()
        response.embeddings = [MagicMock(values=[0.0] * 768) for _ in contents]
        return response

    fake_pool.embed_content.side_effect = _capture

    embedder = ChunkEmbedder(pool=fake_pool, batch_size=32)
    await embedder.embed(["x"] * 75)

    assert calls == [32, 32, 11]


@pytest.mark.asyncio
async def test_embed_uses_retrieval_query_task_type_for_queries() -> None:
    fake_pool = MagicMock()
    captured_task_types = []

    def _capture(*, contents, config):
        task_type = config.task_type if hasattr(config, "task_type") else config["task_type"]
        captured_task_types.append(task_type)
        response = MagicMock()
        response.embeddings = [MagicMock(values=[0.0] * 768) for _ in contents]
        return response

    fake_pool.embed_content.side_effect = _capture

    embedder = ChunkEmbedder(pool=fake_pool)
    await embedder.embed_query_with_cache("What is RRF?")

    assert captured_task_types == ["RETRIEVAL_QUERY"]


def test_content_hash_is_32_bytes() -> None:
    assert len(ChunkEmbedder.content_hash("hello")) == 32

