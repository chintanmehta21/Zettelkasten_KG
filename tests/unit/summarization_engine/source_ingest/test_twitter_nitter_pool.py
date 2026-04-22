"""Unit tests for the Nitter instance pool (health-cache rotation)."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from website.features.summarization_engine.source_ingest.twitter.nitter_pool import (
    NitterPool,
    build_pool_from_config,
)


def test_pool_requires_instances():
    with pytest.raises(ValueError):
        NitterPool(instances=())


def test_pool_dedupes_and_strips_slashes():
    pool = NitterPool(instances=("https://a.test/", "https://a.test", "https://b.test"))
    assert pool.instances == ("https://a.test", "https://b.test")


def test_unknown_instances_surface_first():
    pool = NitterPool(instances=("https://a.test", "https://b.test", "https://c.test"))
    pool.mark_failure("https://a.test", reason="boom")
    # Unknown (b, c) should come before fresh-unhealthy (a).
    order = pool.get_healthy_instances()
    assert order[-1] == "https://a.test"
    assert set(order[:2]) == {"https://b.test", "https://c.test"}


def test_healthy_instances_front_of_queue():
    pool = NitterPool(instances=("https://a.test", "https://b.test"))
    pool.mark_failure("https://a.test")
    pool.mark_success("https://b.test")
    assert pool.get_healthy_instances()[0] == "https://b.test"


def test_stale_entries_treated_as_unknown():
    pool = NitterPool(instances=("https://a.test", "https://b.test"), ttl_seconds=0.01)
    pool.mark_failure("https://a.test")
    time.sleep(0.02)
    # Stale failure should be re-tried before a true fresh-unhealthy peer would be.
    # With both unknown/stale, order just needs to include both.
    assert set(pool.get_healthy_instances()) == {"https://a.test", "https://b.test"}


def test_health_snapshot_reports_age_and_reason():
    pool = NitterPool(instances=("https://a.test",))
    pool.mark_failure("https://a.test", reason="timeout")
    snap = pool.health_snapshot()
    assert snap["https://a.test"]["healthy"] is False
    assert snap["https://a.test"]["reason"] == "timeout"
    assert snap["https://a.test"]["fresh"] is True


def test_build_pool_from_config_honors_disabled():
    assert build_pool_from_config({"use_nitter_fallback": False}) is None


def test_build_pool_from_config_empty_instances():
    assert build_pool_from_config({"use_nitter_fallback": True, "nitter_instances": []}) is None


def test_build_pool_from_config_constructs_with_ttl():
    pool = build_pool_from_config(
        {
            "use_nitter_fallback": True,
            "nitter_instances": ["https://a.test", "https://b.test"],
            "nitter_health_check_timeout_sec": 7,
            "nitter_health_cache_ttl_sec": 120,
        }
    )
    assert pool is not None
    assert pool.probe_timeout_sec == 7.0
    assert pool.ttl_seconds == 120.0


@pytest.mark.asyncio
async def test_probe_marks_success_on_2xx():
    pool = NitterPool(instances=("https://a.test",))
    mock_resp = MagicMock(status_code=200)
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    assert await pool.probe("https://a.test", client=mock_client) is True
    assert pool.health_snapshot()["https://a.test"]["healthy"] is True


@pytest.mark.asyncio
async def test_probe_marks_failure_on_5xx():
    pool = NitterPool(instances=("https://a.test",))
    mock_resp = MagicMock(status_code=503)
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    assert await pool.probe("https://a.test", client=mock_client) is False
    assert pool.health_snapshot()["https://a.test"]["healthy"] is False


@pytest.mark.asyncio
async def test_probe_marks_failure_on_exception():
    pool = NitterPool(instances=("https://a.test",))
    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=RuntimeError("net"))
    assert await pool.probe("https://a.test", client=mock_client) is False
    snap = pool.health_snapshot()
    assert snap["https://a.test"]["healthy"] is False
    assert "RuntimeError" in snap["https://a.test"]["reason"]


@pytest.mark.asyncio
async def test_ingestor_uses_pool_and_records_failure(monkeypatch):
    """End-to-end: ingestor consults pool, records failure, rotates to next instance."""
    from website.features.summarization_engine.source_ingest.twitter import ingest as ingest_mod

    ingest_mod._POOL_CACHE.clear()

    async def fake_oembed(*_args, **_kwargs):
        raise RuntimeError("oembed blocked")

    calls: list[str] = []

    async def fake_fetch_text(url, *_args, **_kwargs):
        calls.append(url)
        if "bad.test" in url:
            raise RuntimeError("connection reset")
        return "<html><body>tweet body</body></html>", {}

    monkeypatch.setattr(ingest_mod, "fetch_json", fake_oembed)
    monkeypatch.setattr(ingest_mod, "fetch_text", fake_fetch_text)

    config = {
        "use_oembed": True,
        "use_nitter_fallback": True,
        "nitter_instances": ["https://bad.test", "https://good.test"],
        "nitter_rotation_on_failure": True,
        "nitter_health_check_timeout_sec": 5,
        "nitter_health_cache_ttl_sec": 300,
    }

    ingestor = ingest_mod.TwitterIngestor()
    result = await ingestor.ingest("https://twitter.com/u/status/1", config=config)

    assert result.metadata["nitter_instance"] == "https://good.test"
    assert "tweet body" in result.raw_text
    assert len(calls) == 2

    pool = ingest_mod._POOL_CACHE[tuple(config["nitter_instances"])]
    snap = pool.health_snapshot()
    assert snap["https://bad.test"]["healthy"] is False
    assert snap["https://good.test"]["healthy"] is True


@pytest.mark.asyncio
async def test_ingestor_skips_rotation_when_flag_off(monkeypatch):
    from website.features.summarization_engine.source_ingest.twitter import ingest as ingest_mod

    ingest_mod._POOL_CACHE.clear()

    async def fake_oembed(*_args, **_kwargs):
        raise RuntimeError("oembed blocked")

    calls: list[str] = []

    async def fake_fetch_text(url, *_args, **_kwargs):
        calls.append(url)
        raise RuntimeError("down")

    monkeypatch.setattr(ingest_mod, "fetch_json", fake_oembed)
    monkeypatch.setattr(ingest_mod, "fetch_text", fake_fetch_text)

    config = {
        "use_oembed": True,
        "use_nitter_fallback": True,
        "nitter_instances": ["https://a.test", "https://b.test"],
        "nitter_rotation_on_failure": False,
    }

    ingestor = ingest_mod.TwitterIngestor()
    result = await ingestor.ingest("https://twitter.com/u/status/1", config=config)

    assert result.extraction_confidence == "low"
    # Without rotation only the first instance is tried.
    assert len(calls) == 1
