from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from website.features.summarization_engine.source_ingest.youtube.tiers import (
    TierName,
    TierResult,
    _yt_proxy_url,
    tier_gemini_youtube_url,
    tier_transcript_api_via_webshare,
    tier_ytdlp_cookies_impersonate,
)


# Chain-runner tests previously in this file
# (test_chain_calls_tiers_in_order_until_success,
#  test_chain_stops_when_budget_exceeded,
#  test_chain_cuts_off_hung_tier_via_asyncio_timeout,
#  test_chain_recovers_on_next_tier_after_a_timeout,
#  test_build_default_chain_places_gemini_filedata_first,
#  test_build_default_chain_has_seven_tiers_in_h3_order,
#  test_invidious_instances_refreshed_to_four)
# were retired 2026-05-25 (PR #91). They relied on the legacy
# ``TranscriptChain(tiers=[...])`` API (now ``stages=[Stage, ...]``) and on
# the dropped Invidious/Piped pool tiers. Equivalent and stronger coverage
# now lives in
# ``website/features/summarization_engine/tests/unit/test_yt_chain_race.py``.
# This file retains the per-tier unit tests (Gemini-URL behaviour, proxy URL
# resolver, env-driven failure modes) that are unaffected by the chain shape.


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


# build_default_chain shape tests retired 2026-05-25 (PR #91) —
# the legacy 7-tier flat list became a Stage-based chain with race + caps.
# New shape assertions live in test_yt_chain_race.py
# (test_default_chain_has_race_first_then_sequential,
#  test_default_chain_per_tier_caps_match_research,
#  test_default_chain_total_budget_under_90s).


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


# test_invidious_instances_refreshed_to_four retired 2026-05-25 (PR #91)
# alongside tier_invidious_pool. Per docs/claude_audits/yt_chain_research_2026-05-25.md §C.


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
    shared by the transcript-API tier and the yt-dlp tiers. The rotating
    backbone needs the '-rotate' username suffix (bare username 407s)."""
    monkeypatch.delenv("YT_PROXY_URL", raising=False)
    monkeypatch.delenv("YT_PROXY_BACKBONE", raising=False)
    monkeypatch.setenv("YT_TRANSCRIPT_PROXY_USER", "wsuser")
    monkeypatch.setenv("YT_TRANSCRIPT_PROXY_PASS", "wspass")
    assert _yt_proxy_url() == "http://wsuser-rotate:wspass@p.webshare.io:80"


def test_yt_proxy_url_rotate_suffix_not_doubled(monkeypatch):
    monkeypatch.delenv("YT_PROXY_URL", raising=False)
    monkeypatch.delenv("YT_PROXY_BACKBONE", raising=False)
    monkeypatch.setenv("YT_TRANSCRIPT_PROXY_USER", "wsuser-rotate")
    monkeypatch.setenv("YT_TRANSCRIPT_PROXY_PASS", "wspass")
    assert _yt_proxy_url() == "http://wsuser-rotate:wspass@p.webshare.io:80"
