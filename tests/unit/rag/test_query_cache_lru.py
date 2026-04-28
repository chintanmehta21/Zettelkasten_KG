"""Iter-03 mem-bounded §2.6: ChunkEmbedder._query_cache must be a bounded
LRU. Default cap 256 entries × ~6 KB = ~1.5 MB. Env override
RAG_QUERY_CACHE_MAX honored at construction time.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from cachetools import LRUCache

from website.features.rag_pipeline.ingest.embedder import ChunkEmbedder


def _new_embedder(**kwargs) -> ChunkEmbedder:
    pool = AsyncMock()
    return ChunkEmbedder(pool=pool, **kwargs)


def test_query_cache_is_lru_with_default_256(monkeypatch):
    monkeypatch.delenv("RAG_QUERY_CACHE_MAX", raising=False)
    e = _new_embedder()
    assert isinstance(e._query_cache, LRUCache)
    assert e._query_cache.maxsize == 256


def test_query_cache_honors_env_override(monkeypatch):
    monkeypatch.setenv("RAG_QUERY_CACHE_MAX", "32")
    e = _new_embedder()
    assert e._query_cache.maxsize == 32


def test_query_cache_evicts_oldest_when_full(monkeypatch):
    monkeypatch.setenv("RAG_QUERY_CACHE_MAX", "3")
    e = _new_embedder()
    # Pretend three queries already cached
    e._query_cache["a"] = [0.1]
    e._query_cache["b"] = [0.2]
    e._query_cache["c"] = [0.3]
    # Inserting a 4th must evict the LRU entry (a)
    e._query_cache["d"] = [0.4]
    assert "a" not in e._query_cache
    assert "d" in e._query_cache
    assert len(e._query_cache) == 3
