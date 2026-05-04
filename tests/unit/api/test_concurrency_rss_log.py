"""iter-10 P8: RSS pre/post-slot logging on acquire_rerank_slot.

Catches OOM-precursor patterns under burst by surfacing per-slot RSS deltas
in the access path; cgroup logs not required.
"""
import logging
import pytest


@pytest.mark.asyncio
async def test_rss_log_emits(caplog, monkeypatch):
    monkeypatch.setenv("RAG_SLOT_RSS_LOG_ENABLED", "true")
    # Reload to pick up env change at module import.
    import importlib
    from website.api import _concurrency
    importlib.reload(_concurrency)
    _concurrency.reset_for_tests()
    with caplog.at_level(logging.INFO, logger="rag.concurrency"):
        async with _concurrency.acquire_rerank_slot():
            pass
    assert any("rss_pre_kb" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_rss_log_disabled_via_env(caplog, monkeypatch):
    monkeypatch.setenv("RAG_SLOT_RSS_LOG_ENABLED", "false")
    import importlib
    from website.api import _concurrency
    importlib.reload(_concurrency)
    _concurrency.reset_for_tests()
    with caplog.at_level(logging.INFO, logger="rag.concurrency"):
        async with _concurrency.acquire_rerank_slot():
            pass
    assert not any("rss_pre_kb" in r.message for r in caplog.records)
    # Restore default for downstream tests.
    monkeypatch.setenv("RAG_SLOT_RSS_LOG_ENABLED", "true")
    importlib.reload(_concurrency)
    _concurrency.reset_for_tests()
