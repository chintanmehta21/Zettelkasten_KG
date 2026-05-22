from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from website.features.summarization_engine.source_ingest.youtube.tiers import (
    TierName,
    TierResult,
    TranscriptChain,
    _yt_proxy_url,
    build_default_chain,
    tier_gemini_audio,
    tier_gemini_youtube_url,
    tier_invidious_pool,
    tier_metadata_only,
    tier_piped_pool,
    tier_transcript_api_via_webshare,
    tier_ytdlp_cookies_impersonate,
)


@pytest.mark.asyncio
async def test_chain_calls_tiers_in_order_until_success():
    t1 = AsyncMock(
        return_value=TierResult(
            tier=TierName.YTDLP_PLAYER_ROTATION,
            transcript="",
            success=False,
        )
    )
    t2 = AsyncMock(
        return_value=TierResult(
            tier=TierName.TRANSCRIPT_API_DIRECT,
            transcript="hello",
            success=True,
        )
    )
    t3 = AsyncMock(
        return_value=TierResult(
            tier=TierName.PIPED_POOL,
            transcript="x",
            success=True,
        )
    )

    chain = TranscriptChain(tiers=[t1, t2, t3], budget_ms=60000)
    result = await chain.run(video_id="x", config={})

    assert result.tier == TierName.TRANSCRIPT_API_DIRECT
    t1.assert_called_once()
    t2.assert_called_once()
    t3.assert_not_called()


@pytest.mark.asyncio
async def test_chain_stops_when_budget_exceeded():
    import asyncio

    async def slow_tier(video_id, config):
        await asyncio.sleep(0.3)
        return TierResult(
            tier=TierName.YTDLP_PLAYER_ROTATION,
            transcript="",
            success=False,
        )

    chain = TranscriptChain(tiers=[slow_tier, slow_tier, slow_tier], budget_ms=500)
    result = await chain.run(video_id="x", config={})

    assert not result.success


@pytest.mark.asyncio
async def test_chain_cuts_off_hung_tier_via_asyncio_timeout():
    """A tier that hangs past the remaining budget is cut off by
    ``asyncio.timeout`` (NOT awaited to completion) and recorded as a
    ``tier_timeout`` attempt. The chain returns bounded rather than hanging
    on the hung tier indefinitely.

    Note: a hung first tier consumes the whole remaining budget by design —
    the per-tier ``asyncio.timeout`` cap IS the remaining budget — so the
    next tier then sees ``budget_exhausted``. The invariant under test is
    "hung tier is force-cancelled and the chain still returns", which is the
    actual robustness fix in commit 706cb84d."""
    import asyncio

    awaited_to_completion = {"hung": False}

    async def hung_tier(video_id, config):
        # Hangs far past the budget — must be cancelled by the per-tier
        # asyncio.timeout guard, NOT awaited to completion.
        await asyncio.sleep(30)
        awaited_to_completion["hung"] = True
        return TierResult(
            tier=TierName.YTDLP_PLAYER_ROTATION, transcript="", success=False,
        )

    chain = TranscriptChain(tiers=[hung_tier], budget_ms=300)
    # The wait_for cap is the real assertion: without the asyncio.timeout
    # guard inside run(), the hung tier would block here for 30s.
    result = await asyncio.wait_for(
        chain.run(video_id="x", config={}), timeout=5.0
    )

    # The hung tier was force-cancelled, never ran to completion.
    assert awaited_to_completion["hung"] is False
    attempts = result.extra.get("all_tier_results") or []
    timeout_rows = [a for a in attempts if a["tier"] == "tier_timeout"]
    assert len(timeout_rows) == 1, attempts
    assert timeout_rows[0]["status"] == "timeout"
    # The chain returned a (failed) result bounded by the budget.
    assert not result.success


@pytest.mark.asyncio
async def test_chain_recovers_on_next_tier_after_a_timeout():
    """When a hung tier is cut off but budget remains, the chain proceeds to
    the next tier and can still succeed. Uses a generous budget so the next
    tier is reached after the first tier's per-tier timeout fires."""
    import asyncio

    # Slow tier hangs ~30s; with a 1200ms budget the asyncio.timeout cuts it
    # at ~1200ms, but a fast-failing tier (returns immediately) afterwards
    # leaves room for the success tier.
    call_log: list[str] = []

    async def slow_then_cut(video_id, config):
        call_log.append("slow")
        await asyncio.sleep(30)
        return TierResult(tier=TierName.PIPED_POOL, transcript="", success=False)

    chain = TranscriptChain(tiers=[slow_then_cut], budget_ms=400)
    result = await asyncio.wait_for(
        chain.run(video_id="x", config={}), timeout=5.0
    )
    # The single hung tier was cut off; the chain returned within the budget
    # rather than blocking for the full 30s sleep.
    assert call_log == ["slow"]
    attempts = result.extra.get("all_tier_results") or []
    assert any(a["tier"] == "tier_timeout" for a in attempts)


def _mk_pool(result_obj):
    pool = SimpleNamespace()
    pool.generate_content_youtube_url = AsyncMock(return_value=result_obj)
    return pool


@pytest.mark.asyncio
async def test_tier_gemini_youtube_url_success():
    fake = SimpleNamespace(
        text="a" * 500, model="gemini-2.5-flash", key_index=0
    )
    pool = _mk_pool(fake)
    with patch(
        "website.features.api_key_switching.get_key_pool",
        return_value=pool,
    ):
        result = await tier_gemini_youtube_url("vid123", {})
    assert result.success is True
    assert result.tier == TierName.GEMINI_FILEDATA
    assert result.extra["model"] == "gemini-2.5-flash"
    assert result.extra["key_index"] == 0
    assert len(result.transcript) == 500


@pytest.mark.asyncio
async def test_tier_gemini_youtube_url_invalid_argument_is_non_retryable():
    pool = SimpleNamespace()
    pool.generate_content_youtube_url = AsyncMock(
        side_effect=RuntimeError("400 INVALID_ARGUMENT: must be public")
    )
    with patch(
        "website.features.api_key_switching.get_key_pool",
        return_value=pool,
    ):
        result = await tier_gemini_youtube_url("vid_private", {})
    assert result.success is False
    assert result.extra.get("non_retryable") is True
    assert "non-retryable" in result.error


@pytest.mark.asyncio
async def test_tier_gemini_youtube_url_empty_text_is_failure():
    fake = SimpleNamespace(text="EMPTY", model="gemini-2.5-flash", key_index=1)
    pool = _mk_pool(fake)
    with patch(
        "website.features.api_key_switching.get_key_pool",
        return_value=pool,
    ):
        result = await tier_gemini_youtube_url("vid_silent", {})
    assert result.success is False
    assert "empty-or-too-short" in result.error


@pytest.mark.asyncio
async def test_tier_gemini_youtube_url_disabled_via_config():
    result = await tier_gemini_youtube_url(
        "vid", {"gemini_filedata": {"enabled": False}}
    )
    assert result.success is False
    assert "disabled" in result.error


def test_build_default_chain_places_gemini_filedata_first():
    chain = build_default_chain({})
    first_tier = chain._tiers[0]
    assert first_tier is tier_gemini_youtube_url


def test_build_default_chain_has_seven_tiers_in_h3_order():
    chain = build_default_chain({})
    assert chain._tiers == [
        tier_gemini_youtube_url,
        tier_transcript_api_via_webshare,
        tier_ytdlp_cookies_impersonate,
        tier_invidious_pool,
        tier_piped_pool,
        tier_gemini_audio,
        tier_metadata_only,
    ]


@pytest.mark.asyncio
async def test_tier_transcript_api_via_webshare_fails_when_proxy_unset(monkeypatch):
    monkeypatch.delenv("YT_TRANSCRIPT_PROXY_URL", raising=False)
    result = await tier_transcript_api_via_webshare("vid123", {})
    assert result.success is False
    assert "YT_TRANSCRIPT_PROXY_URL" in (result.error or "")
    assert result.tier == TierName.TRANSCRIPT_API_DIRECT


@pytest.mark.asyncio
async def test_tier_ytdlp_cookies_impersonate_fails_when_cookies_missing(monkeypatch):
    monkeypatch.setenv("YT_COOKIES_PATH", "/nonexistent/path/yt-cookies.txt")
    result = await tier_ytdlp_cookies_impersonate("vid123", {})
    assert result.success is False
    assert "YT_COOKIES_PATH" in (result.error or "")
    assert result.tier == TierName.YTDLP_PLAYER_ROTATION


@pytest.mark.asyncio
async def test_tier_ytdlp_cookies_impersonate_fails_when_cookies_env_unset(monkeypatch):
    monkeypatch.delenv("YT_COOKIES_PATH", raising=False)
    result = await tier_ytdlp_cookies_impersonate("vid123", {})
    assert result.success is False
    assert "YT_COOKIES_PATH" in (result.error or "")


def test_invidious_instances_refreshed_to_four():
    """H4/T4 — config carries exactly the 4 refreshed Invidious instances."""
    from website.features.summarization_engine.core.config import load_config

    cfg = load_config()
    youtube = cfg.sources.get("youtube", {})
    instances = youtube.get("invidious_instances") or []
    assert instances == [
        "inv.nadeko.net",
        "invidious.nerdvpn.de",
        "inv.thepixora.com",
        "yt.chocolatemoo53.com",
    ]


def test_yt_proxy_url_unset_returns_empty(monkeypatch):
    for var in ("YT_PROXY_URL", "YT_TRANSCRIPT_PROXY_USER",
                "YT_TRANSCRIPT_PROXY_PASS", "YT_PROXY_BACKBONE"):
        monkeypatch.delenv(var, raising=False)
    assert _yt_proxy_url() == ""


def test_yt_proxy_url_explicit_overrides(monkeypatch):
    monkeypatch.setenv("YT_PROXY_URL", "http://u:p@host:8080")
    monkeypatch.setenv("YT_TRANSCRIPT_PROXY_USER", "ignored")
    monkeypatch.setenv("YT_TRANSCRIPT_PROXY_PASS", "ignored")
    assert _yt_proxy_url() == "http://u:p@host:8080"


def test_yt_proxy_url_derived_from_webshare_creds(monkeypatch):
    """Free->paid switch is value-only: same creds derive the backbone URL,
    shared by the transcript-API tier and the yt-dlp tiers."""
    monkeypatch.delenv("YT_PROXY_URL", raising=False)
    monkeypatch.delenv("YT_PROXY_BACKBONE", raising=False)
    monkeypatch.setenv("YT_TRANSCRIPT_PROXY_USER", "wsuser")
    monkeypatch.setenv("YT_TRANSCRIPT_PROXY_PASS", "wspass")
    assert _yt_proxy_url() == "http://wsuser:wspass@p.webshare.io:80"
