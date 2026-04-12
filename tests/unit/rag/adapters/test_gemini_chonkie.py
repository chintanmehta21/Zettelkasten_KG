from unittest.mock import MagicMock

import numpy as np

from website.features.rag_pipeline.adapters import pool_factory


def test_embed_returns_768d_vectors(monkeypatch) -> None:
    fake_pool = MagicMock()
    fake_response = MagicMock()
    fake_response.embeddings = [
        MagicMock(values=[0.1] * 768),
        MagicMock(values=[0.2] * 768),
    ]
    fake_pool.embed_content.return_value = fake_response

    pool_factory.get_gemini_pool.cache_clear()
    monkeypatch.setattr(pool_factory, "get_key_pool", lambda: fake_pool)

    from website.features.rag_pipeline.adapters.gemini_chonkie import GeminiChonkieEmbeddings

    embeddings = GeminiChonkieEmbeddings()
    vectors = embeddings.embed(["hello", "world"])

    assert len(vectors) == 2
    assert all(isinstance(vector, np.ndarray) for vector in vectors)
    assert all(vector.shape == (768,) for vector in vectors)


def test_dimension_property_returns_768(monkeypatch) -> None:
    pool_factory.get_gemini_pool.cache_clear()
    monkeypatch.setattr(pool_factory, "get_key_pool", lambda: MagicMock())

    from website.features.rag_pipeline.adapters.gemini_chonkie import GeminiChonkieEmbeddings

    assert GeminiChonkieEmbeddings().dimension == 768


def test_single_text_embed_returns_numpy_array(monkeypatch) -> None:
    fake_pool = MagicMock()
    fake_response = MagicMock()
    fake_response.embeddings = [MagicMock(values=[0.3] * 768)]
    fake_pool.embed_content.return_value = fake_response

    pool_factory.get_gemini_pool.cache_clear()
    monkeypatch.setattr(pool_factory, "get_key_pool", lambda: fake_pool)

    from website.features.rag_pipeline.adapters.gemini_chonkie import GeminiChonkieEmbeddings

    vector = GeminiChonkieEmbeddings().embed("hello")
    assert isinstance(vector, np.ndarray)
    assert vector.shape == (768,)

