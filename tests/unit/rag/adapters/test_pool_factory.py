from website.features.rag_pipeline.adapters import pool_factory


def test_get_gemini_pool_returns_singleton(monkeypatch) -> None:
    sentinel = object()
    pool_factory.get_gemini_pool.cache_clear()
    monkeypatch.setattr(pool_factory, "get_key_pool", lambda: sentinel)

    assert pool_factory.get_gemini_pool() is sentinel
    assert pool_factory.get_gemini_pool() is sentinel

