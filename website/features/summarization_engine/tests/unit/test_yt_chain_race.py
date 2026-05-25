"""Race + per-tier cap behaviour for TranscriptChain (PR #91).

Covers the contracts from ``docs/claude_audits/yt_chain_research_2026-05-25.md``:
- Per-tier cap fires → next stage (gRPC deadline-propagation; Envoy
  ``per_try_timeout``; Polly v8; Resilience4j).
- Race: first success wins; losers cancelled then drained via
  ``gather(*pending, return_exceptions=True)`` so httpx returns sockets
  to the pool (httpcore #149, httpx #1461).
- Race: all timeout / all fail → no winner, falls through to next stage.
- Static guards: ``tier_invidious_pool`` + ``tier_piped_pool`` + their
  enum members + their pool helpers are gone; ``build_default_chain``
  returns the new race-first shape.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from website.features.summarization_engine.source_ingest.youtube.tiers import (
    RaceStage,
    TierName,
    TierResult,
    TierSpec,
    TranscriptChain,
    build_default_chain,
)


# ---------- shared helpers ----------


def _ok(name: str, latency_ms: int = 50) -> TierResult:
    return TierResult(
        tier=TierName.METADATA_ONLY,
        transcript=f"transcript-from-{name}",
        success=True,
        latency_ms=latency_ms,
    )


def _fail(name: str, latency_ms: int = 30) -> TierResult:
    return TierResult(
        tier=TierName.METADATA_ONLY,
        transcript="",
        success=False,
        error=f"{name}-failed",
        latency_ms=latency_ms,
    )


# ---------- per-tier cap (sequential) ----------


@pytest.mark.asyncio
async def test_sequential_per_tier_cap_fires_then_next_stage_wins():
    """A hung sequential tier hits its per-tier cap; chain moves to next stage."""

    async def slow(video_id, config):
        await asyncio.sleep(5)
        return _ok("never")

    async def quick(video_id, config):
        return _ok("quick")

    chain = TranscriptChain(
        stages=[
            TierSpec(fn=slow, name="slow", cap_ms=100),
            TierSpec(fn=quick, name="quick", cap_ms=5_000),
        ],
        budget_ms=10_000,
    )

    t0 = time.monotonic()
    result = await chain.run(video_id="x", config={})
    elapsed = time.monotonic() - t0

    assert result.success
    assert "transcript-from-quick" in result.transcript
    # ~100 ms (slow cap) + quick's near-zero work; ceiling 1.5 s for CI slack.
    assert elapsed < 1.5, f"chain ran longer than expected: {elapsed:.3f}s"

    attempts = result.extra["all_tier_results"]
    assert any(
        a.get("status") == "timeout" and "slow" in a.get("reason", "")
        for a in attempts
    ), f"timeout for 'slow' not recorded: {attempts}"
    assert any(a.get("status") == "success" for a in attempts)


# ---------- race ----------


@pytest.mark.asyncio
async def test_race_first_success_wins_loser_cancelled_and_drained():
    """T1 returns; T2 hangs; T1 wins; T2 receives CancelledError; pending drained."""
    t2_cancelled = asyncio.Event()

    async def t1(video_id, config):
        await asyncio.sleep(0.01)
        return _ok("t1")

    async def t2_hang(video_id, config):
        try:
            await asyncio.sleep(10)
            return _ok("never")
        except asyncio.CancelledError:
            t2_cancelled.set()
            raise

    chain = TranscriptChain(
        stages=[
            RaceStage(
                specs=(
                    TierSpec(fn=t1, name="t1", cap_ms=5_000),
                    TierSpec(fn=t2_hang, name="t2", cap_ms=5_000),
                ),
                cap_ms=5_000,
            ),
        ],
        budget_ms=10_000,
    )

    result = await chain.run(video_id="x", config={})

    assert result.success
    assert "transcript-from-t1" in result.transcript
    # gather-after-cancel must have flushed t2 before chain.run() returned;
    # this assertion validates the drain contract (httpcore #149 fix).
    assert t2_cancelled.is_set(), "race loser must receive CancelledError"

    attempts = result.extra["all_tier_results"]
    assert any(a.get("tier") == "race:t1" and a.get("status") == "success" for a in attempts)
    assert any(a.get("tier") == "race:t2" and a.get("status") == "cancelled" for a in attempts)


@pytest.mark.asyncio
async def test_race_T2_wins_when_T1_hangs():
    """Symmetric to the previous test: T2 returns first; T1 hangs."""

    async def t1_hang(video_id, config):
        await asyncio.sleep(10)
        return _ok("never")

    async def t2(video_id, config):
        await asyncio.sleep(0.01)
        return _ok("t2")

    chain = TranscriptChain(
        stages=[
            RaceStage(
                specs=(
                    TierSpec(fn=t1_hang, name="t1", cap_ms=5_000),
                    TierSpec(fn=t2, name="t2", cap_ms=5_000),
                ),
                cap_ms=5_000,
            ),
        ],
        budget_ms=10_000,
    )

    result = await chain.run(video_id="x", config={})
    assert result.success
    assert "transcript-from-t2" in result.transcript


@pytest.mark.asyncio
async def test_race_both_timeout_no_winner_falls_to_next_stage():
    async def hang_a(video_id, config):
        await asyncio.sleep(5)
        return _ok("never")

    async def hang_b(video_id, config):
        await asyncio.sleep(5)
        return _ok("never")

    async def rescue(video_id, config):
        return _ok("rescue")

    chain = TranscriptChain(
        stages=[
            RaceStage(
                specs=(
                    TierSpec(fn=hang_a, name="a", cap_ms=100),
                    TierSpec(fn=hang_b, name="b", cap_ms=100),
                ),
                cap_ms=200,
            ),
            TierSpec(fn=rescue, name="rescue", cap_ms=5_000),
        ],
        budget_ms=10_000,
    )

    result = await chain.run(video_id="x", config={})
    assert result.success
    assert "transcript-from-rescue" in result.transcript


@pytest.mark.asyncio
async def test_race_both_fail_no_winner_falls_to_next_stage():
    async def fail_a(video_id, config):
        return _fail("a")

    async def fail_b(video_id, config):
        return _fail("b")

    async def rescue(video_id, config):
        return _ok("rescue")

    chain = TranscriptChain(
        stages=[
            RaceStage(
                specs=(
                    TierSpec(fn=fail_a, name="a", cap_ms=5_000),
                    TierSpec(fn=fail_b, name="b", cap_ms=5_000),
                ),
                cap_ms=5_000,
            ),
            TierSpec(fn=rescue, name="rescue", cap_ms=5_000),
        ],
        budget_ms=10_000,
    )

    result = await chain.run(video_id="x", config={})
    assert result.success
    assert "transcript-from-rescue" in result.transcript


@pytest.mark.asyncio
async def test_race_exception_in_one_tier_other_can_still_win():
    """A tier raising a non-timeout exception is recorded as failed; the other can win."""

    async def boom(video_id, config):
        raise RuntimeError("boom")

    async def fast(video_id, config):
        await asyncio.sleep(0.01)
        return _ok("fast")

    chain = TranscriptChain(
        stages=[
            RaceStage(
                specs=(
                    TierSpec(fn=boom, name="boom", cap_ms=5_000),
                    TierSpec(fn=fast, name="fast", cap_ms=5_000),
                ),
                cap_ms=5_000,
            ),
        ],
        budget_ms=10_000,
    )

    result = await chain.run(video_id="x", config={})
    assert result.success
    assert "transcript-from-fast" in result.transcript


# ---------- chain-level integration ----------


@pytest.mark.asyncio
async def test_chain_race_fails_then_third_tier_succeeds():
    """End-to-end: race times out → next sequential tier wins. Mirrors prod shape."""

    async def race_a_hang(video_id, config):
        await asyncio.sleep(5)
        return _ok("never")

    async def race_b_hang(video_id, config):
        await asyncio.sleep(5)
        return _ok("never")

    async def t3_succeed(video_id, config):
        return _ok("t3")

    chain = TranscriptChain(
        stages=[
            RaceStage(
                specs=(
                    TierSpec(fn=race_a_hang, name="a", cap_ms=100),
                    TierSpec(fn=race_b_hang, name="b", cap_ms=100),
                ),
                cap_ms=200,
            ),
            TierSpec(fn=t3_succeed, name="t3", cap_ms=5_000),
        ],
        budget_ms=10_000,
    )

    result = await chain.run(video_id="x", config={})
    assert result.success
    assert "transcript-from-t3" in result.transcript


@pytest.mark.asyncio
async def test_chain_all_stages_fail_returns_failed_last_result():
    async def fail_a(video_id, config):
        return _fail("a")

    chain = TranscriptChain(
        stages=[TierSpec(fn=fail_a, name="a", cap_ms=5_000)],
        budget_ms=10_000,
    )

    result = await chain.run(video_id="x", config={})
    assert not result.success
    attempts = result.extra["all_tier_results"]
    assert any(a.get("status") == "failed" for a in attempts)


@pytest.mark.asyncio
async def test_chain_total_budget_cap_skips_remaining_stages():
    """Parent budget fires → remaining stages emit ``budget_exhausted``."""

    async def slow_a(video_id, config):
        await asyncio.sleep(5)
        return _ok("never")

    async def should_not_run(video_id, config):
        raise AssertionError("budget should have skipped this stage")

    chain = TranscriptChain(
        stages=[
            TierSpec(fn=slow_a, name="slow", cap_ms=500),
            TierSpec(fn=should_not_run, name="never", cap_ms=5_000),
        ],
        budget_ms=400,  # tighter than slow's 500ms cap; budget fires inside slow
    )

    result = await chain.run(video_id="x", config={})
    assert not result.success
    attempts = result.extra["all_tier_results"]
    assert any(a.get("tier") == "budget_exhausted" for a in attempts), (
        f"budget_exhausted not recorded: {attempts}"
    )


# ---------- static guards: dropped tiers + chain shape ----------


def test_dropped_tier_functions_no_longer_importable():
    """``tier_piped_pool`` + ``tier_invidious_pool`` + their helpers were removed."""
    import importlib

    mod = importlib.import_module(
        "website.features.summarization_engine.source_ingest.youtube.tiers"
    )
    for retired in (
        "tier_piped_pool",
        "tier_invidious_pool",
        "_try_pool",
        "_load_health",
        "_save_health",
        "_is_healthy",
        "_mark_unhealthy",
        "_extract_caption_url_from_pool_response",
        "_caption_text_to_plaintext",
    ):
        assert not hasattr(mod, retired), (
            f"{retired} should have been removed in PR #91"
        )


def test_dropped_enum_members():
    names = {m.name for m in TierName}
    assert "PIPED_POOL" not in names
    assert "INVIDIOUS_POOL" not in names


def test_default_chain_has_race_first_then_sequential():
    """Race(Webshare, yt-dlp) → gemini-url → gemini-audio → metadata."""
    chain = build_default_chain({})
    stages = chain._stages  # noqa: SLF001 -- contract test against private field
    assert len(stages) == 4
    assert isinstance(stages[0], RaceStage)
    race_names = {s.name for s in stages[0].specs}
    assert race_names == {"transcript_api_webshare", "ytdlp_cookies_impersonate"}
    assert isinstance(stages[1], TierSpec) and stages[1].name == "gemini_youtube_url"
    assert isinstance(stages[2], TierSpec) and stages[2].name == "gemini_audio"
    assert isinstance(stages[3], TierSpec) and stages[3].name == "metadata_only"


def test_default_chain_per_tier_caps_match_research():
    """Caps grounded in ``docs/claude_audits/yt_chain_research_2026-05-25.md`` §B
    + operator's T3 override (20 s tight cap on gemini-url)."""
    chain = build_default_chain({})
    stages = chain._stages  # noqa: SLF001
    # Race: 15 s window, each racer 15 s
    assert stages[0].cap_ms == 15_000
    for spec in stages[0].specs:
        assert spec.cap_ms == 15_000
    # Sequential: gemini-url tight 20 s; gemini-audio 30 s; metadata-only 5 s.
    assert stages[1].cap_ms == 20_000
    assert stages[2].cap_ms == 30_000
    assert stages[3].cap_ms == 5_000


def test_default_chain_total_budget_under_90s():
    """Sum of per-tier caps must fit under parent budget with headroom."""
    chain = build_default_chain({})
    stages = chain._stages  # noqa: SLF001
    # RaceStage's worst-case is the race window itself, not sum(specs).
    worst_case_ms = stages[0].cap_ms + sum(s.cap_ms for s in stages[1:])
    assert worst_case_ms <= 90_000
    assert worst_case_ms <= chain._budget_ms  # noqa: SLF001
