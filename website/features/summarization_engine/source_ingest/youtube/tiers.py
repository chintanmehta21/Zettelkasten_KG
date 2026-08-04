"""YouTube transcript fallback chain scaffold."""
from __future__ import annotations

import asyncio
import functools
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from website.features.summarization_engine.source_ingest.youtube import tier_health

logger = logging.getLogger(__name__)


class TierName(str, Enum):
    YTDLP_PLAYER_ROTATION = "ytdlp_player_rotation"
    GEMINI_FILEDATA = "gemini_filedata"
    TRANSCRIPT_API_DIRECT = "transcript_api_direct"
    # PIPED_POOL + INVIDIOUS_POOL retired 2026-05-25 (PR #91): public pools
    # were mass-blocked by YouTube on 2024-12-19; only 6 Invidious instances
    # officially listed (down from ~40 in 2023) and most have broken
    # subtitles. Maintenance cost exceeded value contributed — see
    # docs/claude_audits/yt_chain_research_2026-05-25.md §C.
    GEMINI_AUDIO = "gemini_audio"
    METADATA_ONLY = "metadata_only"


@dataclass
class TierResult:
    tier: TierName
    transcript: str
    success: bool
    confidence: str = "low"
    latency_ms: int = 0
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


TierFn = Callable[[str, dict], Awaitable[TierResult]]


@dataclass(frozen=True)
class TierSpec:
    """A single tier with its own per-tier hard cap.

    The cap is the upper bound on this tier's wall-clock; at run-time it
    is bounded by ``min(remaining_budget, cap_ms)`` so a single hung
    tier can never exceed its own cap AND can never exceed the parent
    budget. This is the **double-bound pattern** (Envoy ``per_try_timeout``
    + route ``timeout``; gRPC deadline propagation; Polly v8; Resilience4j) —
    industry-unanimous per
    ``docs/claude_audits/yt_chain_research_2026-05-25.md`` §B.
    """
    fn: TierFn
    name: str
    cap_ms: int


@dataclass(frozen=True)
class RaceStage:
    """A concurrent race over N tier specs; first success wins.

    Implementation contract:
      * Each spec runs as an asyncio task with its own per-spec timeout.
      * ``asyncio.wait(FIRST_COMPLETED, timeout=cap_ms/1000)`` — the
        canonical "race N, take first" primitive in Python 3.12. Not
        ``TaskGroup`` (which only cancels siblings on *exception* not
        success), not ``gather`` (which never cancels siblings).
      * On winner found: cancel pending tasks, THEN
        ``await asyncio.gather(*pending, return_exceptions=True)``.
        **This drain is REQUIRED** to flush sockets back to the httpx
        pool. Without it, ``CancelledError`` (a ``BaseException`` since
        3.8) escapes any ``except Exception`` cleanup and the socket is
        leaked. See httpcore#149, httpx#1461 (multi-year open bugs) and
        ``docs/claude_audits/yt_chain_research_2026-05-25.md`` §A.
    """
    specs: tuple[TierSpec, ...]
    cap_ms: int


# A chain stage is either a sequential ``TierSpec`` or a concurrent
# ``RaceStage``. The chain runner iterates stages in declaration order.
Stage = TierSpec | RaceStage


class TranscriptChain:
    """Bounded, double-budgeted tier chain with optional concurrent races.

    Total-budget cap (``budget_ms``) is the parent deadline; the chain
    NEVER runs past it. Per-tier caps (``TierSpec.cap_ms``) are the local
    hop deadline; a single tier NEVER hangs longer than its own cap.
    When a per-tier cap fires, the chain moves to the **next** stage;
    only the total-budget cap fails the whole chain. Mirrors gRPC's
    deadline-propagation semantics.
    """

    def __init__(self, stages: list[Stage], budget_ms: int = 90000) -> None:
        self._stages = list(stages)
        self._budget_ms = budget_ms

    async def run(self, *, video_id: str, config: dict) -> TierResult:
        start = time.monotonic()
        last_result: TierResult | None = None
        attempts: list[dict[str, Any]] = []

        for stage in self._stages:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            remaining_ms = self._budget_ms - elapsed_ms
            if remaining_ms <= 0:
                attempts.append({
                    "tier": "budget_exhausted",
                    "status": "skipped",
                    "reason": f"budget {self._budget_ms}ms exceeded",
                    "latency_ms": elapsed_ms,
                })
                break

            if isinstance(stage, RaceStage):
                result = await self._run_race(
                    stage, remaining_ms, video_id, config, attempts
                )
            else:  # TierSpec — sequential single tier
                result = await self._run_single(
                    stage, remaining_ms, video_id, config, attempts
                )

            if result is None:
                # tier(s) timed out or all racers failed; try next stage
                continue
            last_result = result
            if result.success:
                last_result.extra.setdefault("all_tier_results", attempts)
                return last_result

        final = last_result or TierResult(
            tier=TierName.METADATA_ONLY,
            transcript="",
            success=False,
        )
        final.extra.setdefault("all_tier_results", attempts)
        return final

    async def _run_single(
        self,
        spec: TierSpec,
        remaining_ms: int,
        video_id: str,
        config: dict,
        attempts: list[dict[str, Any]],
    ) -> TierResult | None:
        """Sequential single tier, double-bound timeout."""
        cap_ms = min(remaining_ms, spec.cap_ms)
        tier_start = time.monotonic()
        try:
            async with asyncio.timeout(cap_ms / 1000):
                result = await spec.fn(video_id, config)
        except (asyncio.TimeoutError, TimeoutError):
            elapsed_ms = int((time.monotonic() - tier_start) * 1000)
            attempts.append({
                "tier": "tier_timeout",
                "status": "timeout",
                "reason": f"tier {spec.name} exceeded cap {cap_ms}ms",
                "latency_ms": elapsed_ms,
            })
            tier_health.record_failure(spec.name, f"tier_timeout cap={cap_ms}ms")
            return None
        attempts.append({
            "tier": result.tier.value,
            "status": "success" if result.success else "failed",
            "reason": (result.error or "")[:200] if not result.success else "",
            "latency_ms": result.latency_ms,
        })
        if result.success:
            tier_health.record_success(spec.name, result.latency_ms)
        else:
            tier_health.record_failure(spec.name, result.error or "tier_returned_failure")
        return result

    async def _run_race(
        self,
        stage: RaceStage,
        remaining_ms: int,
        video_id: str,
        config: dict,
        attempts: list[dict[str, Any]],
    ) -> TierResult | None:
        """N-way concurrent race; first **successful** completion wins.

        Key contract: a fast-failing tier (exception OR ``result.success=False``)
        does NOT end the race — the loop keeps waiting on the remaining tasks
        until either a successful task wins, all tasks have completed without
        success, or the race window closes. This matches the hedged-request
        literature (Tail-at-Scale §3.2) and is the only sane behaviour when one
        provider is faulty and the other is healthy.

        Losers (still running when a winner is found OR race window closes)
        are cancelled and the pending set is drained via
        ``await asyncio.gather(*pending, return_exceptions=True)`` so httpx
        returns sockets to its pool. See httpcore #149 / httpx #1461.
        """
        race_cap_ms = min(remaining_ms, stage.cap_ms)
        race_start = time.monotonic()

        async def _bounded_call(spec: TierSpec) -> TierResult:
            spec_cap_ms = min(race_cap_ms, spec.cap_ms)
            async with asyncio.timeout(spec_cap_ms / 1000):
                return await spec.fn(video_id, config)

        tasks_by_spec: dict[asyncio.Task[TierResult], TierSpec] = {
            asyncio.create_task(_bounded_call(spec), name=f"race:{spec.name}"): spec
            for spec in stage.specs
        }
        remaining: set[asyncio.Task[TierResult]] = set(tasks_by_spec.keys())
        # task → ("result", TierResult) | ("timeout", exc) | ("error", exc)
        outcomes: dict[asyncio.Task[TierResult], tuple[str, Any]] = {}
        winner: TierResult | None = None

        # Loop with FIRST_COMPLETED so fast-failing tiers don't kill the race.
        while remaining and winner is None:
            elapsed_ms = (time.monotonic() - race_start) * 1000
            window_left_s = max(0.0, (race_cap_ms - elapsed_ms) / 1000.0)
            if window_left_s <= 0:
                break
            done, pending = await asyncio.wait(
                remaining,
                return_when=asyncio.FIRST_COMPLETED,
                timeout=window_left_s,
            )
            if not done:
                break  # race window closed without any completion
            for task in done:
                try:
                    result = task.result()
                    outcomes[task] = ("result", result)
                    if result.success and winner is None:
                        winner = result
                except (asyncio.TimeoutError, TimeoutError) as exc:
                    outcomes[task] = ("timeout", exc)
                except Exception as exc:  # noqa: BLE001 — recorded, not swallowed
                    outcomes[task] = ("error", exc)
            remaining = pending

        # Cancel the still-running pending tasks then drain. Gather-after-cancel
        # is REQUIRED — see class docstring + httpcore#149 / httpx#1461.
        still_running = remaining - set(outcomes.keys())
        for t in still_running:
            t.cancel()
        if still_running:
            await asyncio.gather(*still_running, return_exceptions=True)

        # Record every spec's outcome for forensics. Per-tier health
        # (``tier_health``) is also updated here: a race **loser** is NOT a
        # tier failure — it just lost the race — so cancellations are NOT
        # recorded as failures. Only true failures (timeout / exception /
        # ``result.success=False``) bump the error counters.
        for task, spec in tasks_by_spec.items():
            tier_id = f"race:{spec.name}"
            if task in outcomes:
                kind, payload = outcomes[task]
                if kind == "result":
                    result = payload
                    if result is winner:
                        attempts.append({
                            "tier": tier_id,
                            "status": "success",
                            "reason": "",
                            "latency_ms": result.latency_ms,
                        })
                        tier_health.record_success(spec.name, result.latency_ms)
                    else:
                        attempts.append({
                            "tier": tier_id,
                            "status": "failed" if not result.success else "loser_late_success",
                            "reason": (result.error or "")[:200] if not result.success else "",
                            "latency_ms": result.latency_ms,
                        })
                        if not result.success:
                            tier_health.record_failure(
                                spec.name, result.error or "tier_returned_failure"
                            )
                elif kind == "timeout":
                    attempts.append({
                        "tier": tier_id,
                        "status": "timeout",
                        "reason": "per-spec cap exceeded",
                        "latency_ms": int((time.monotonic() - race_start) * 1000),
                    })
                    tier_health.record_failure(spec.name, "per-spec cap exceeded")
                else:  # "error"
                    attempts.append({
                        "tier": tier_id,
                        "status": "failed",
                        "reason": str(payload)[:200],
                        "latency_ms": int((time.monotonic() - race_start) * 1000),
                    })
                    tier_health.record_failure(spec.name, str(payload)[:200])
            else:
                # Task was still running when race ended → cancelled.
                # Cancellations do NOT bump tier_health.error_count: a tier
                # that was healthy but lost the race to a faster sibling
                # should not look unhealthy on /api/health.
                attempts.append({
                    "tier": tier_id,
                    "status": "cancelled",
                    "reason": "race lost" if winner is not None else "race window closed",
                    "latency_ms": int((time.monotonic() - race_start) * 1000),
                })
        return winner


def _yt_proxy_url() -> str:
    """Resolve the HTTP proxy URL for the yt-dlp tiers.

    Config-driven so the Webshare free -> paid (rotating residential) switch
    is an environment change only, never a code change. Resolution order:

    1. ``YT_PROXY_URL`` — explicit full URL ``http://user:pass@host:port``.
    2. Derived from the Webshare transcript-proxy credentials
       (``YT_TRANSCRIPT_PROXY_USER`` / ``YT_TRANSCRIPT_PROXY_PASS``) against
       the Webshare rotating backbone ``p.webshare.io:80`` — the same host
       for the free datacenter pool and paid residential plans. This lets a
       single set of env vars route every YouTube-bound tier (transcript API
       *and* yt-dlp) through the one proxy.

    Returns ``""`` when no proxy is configured (direct connection).
    """
    explicit = os.environ.get("YT_PROXY_URL", "").strip()
    if explicit:
        return explicit
    user = os.environ.get("YT_TRANSCRIPT_PROXY_USER", "").strip()
    pwd = os.environ.get("YT_TRANSCRIPT_PROXY_PASS", "").strip()
    if user and pwd:
        host = os.environ.get("YT_PROXY_BACKBONE", "p.webshare.io:80").strip()
        # Webshare's rotating backbone endpoint authenticates with a
        # "<username>-rotate" suffix (each request then exits via a
        # different proxy from the pool); the bare username 407s.
        rotate_user = user if user.endswith("-rotate") else f"{user}-rotate"
        return f"http://{rotate_user}:{pwd}@{host}"
    return ""


@functools.lru_cache(maxsize=1)
def impersonate_target_available(target: str = "chrome") -> bool:
    """Whether yt-dlp can actually impersonate ``target`` in this image.

    2026-08-02: `ops/requirements.in` pinned `yt-dlp[default]`, which omits the
    curl-cffi backend, so tier 3 failed all 5 player clients per request with
    'Impersonate target "chrome" is not available' — silently, for months.
    Probed once per process and reported as a single tier error instead.
    """
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.networking.impersonate import ImpersonateTarget

        with YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            return bool(
                ydl._impersonate_target_available(ImpersonateTarget.from_str(target))
            )
    except Exception:  # noqa: BLE001 — probe must never break ingestion
        return False


async def tier_ytdlp_cookies_impersonate(video_id: str, config: dict) -> TierResult:
    """Tier 3: yt-dlp with --cookies-from-burner-account + --impersonate chrome
    (curl_cffi) + PO-token from bgutil sidecar. Unlocks age-restricted +
    members-only + bot-gate. Operator must configure YT_COOKIES_PATH,
    YT_USER_AGENT, YTDLP_POT_PROVIDER_URL. See docs/runbooks/yt-fallback-stack.md.
    Reuses TierName.YTDLP_PLAYER_ROTATION to avoid enum churn."""
    from yt_dlp import YoutubeDL

    start = time.monotonic()
    cookies_path = os.environ.get("YT_COOKIES_PATH", "")
    user_agent = os.environ.get("YT_USER_AGENT", "")
    pot_provider_url = os.environ.get("YTDLP_POT_PROVIDER_URL", "")

    if not cookies_path or not os.path.exists(cookies_path):
        return TierResult(
            tier=TierName.YTDLP_PLAYER_ROTATION,
            transcript="",
            success=False,
            latency_ms=0,
            error="YT_COOKIES_PATH not set or missing — see docs/runbooks/yt-fallback-stack.md",
        )

    # Fail once, loudly, instead of once per player client. Surfaces on
    # /api/health under yt_tier_health via the chain runner's record_failure.
    if not impersonate_target_available():
        logger.error(
            "[yt-tier3] curl-cffi impersonation unavailable — tier 3 is dead. "
            "Image must install yt-dlp[default,curl-cffi]."
        )
        return TierResult(
            tier=TierName.YTDLP_PLAYER_ROTATION,
            transcript="",
            success=False,
            latency_ms=0,
            error="impersonate backend missing (install yt-dlp[default,curl-cffi])",
        )

    clients = config.get(
        "ytdlp_player_clients",
        ["tv_simply", "android_sdkless", "ios", "web_safari", "web"],
    )
    url = f"https://www.youtube.com/watch?v={video_id}"

    for client in clients:
        with tempfile.TemporaryDirectory() as tmp:
            opts = {
                "quiet": True,
                "skip_download": True,
                "no_warnings": True,
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": config.get("transcript_languages", ["en"]),
                "subtitlesformat": "vtt",
                "outtmpl": str(Path(tmp) / "%(id)s.%(ext)s"),
                "cookiefile": cookies_path,
                "extractor_args": {
                    "youtube": {
                        "player_client": [client],
                        **(
                            {"pot_provider_url": [pot_provider_url]}
                            if pot_provider_url
                            else {}
                        ),
                    }
                },
                # curl_cffi impersonation via yt-dlp's impersonate option
                "impersonate": "chrome",
                # Route through the Webshare proxy when configured; None ->
                # yt-dlp default (direct). Datacenter IPs are bot-walled, so
                # in production this is what gets past "confirm you're not a bot".
                "proxy": _yt_proxy_url() or None,
            }
            if user_agent:
                opts["user_agent"] = user_agent
            try:
                with YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True) or {}
                vtts = list(Path(tmp).glob("*.vtt"))
                if vtts:
                    transcript = _vtt_to_plaintext(
                        vtts[0].read_text(encoding="utf-8")
                    )
                    if len(transcript) > 100:
                        latency = int((time.monotonic() - start) * 1000)
                        logger.info(
                            "[yt-tier3] client=%s success len=%d",
                            client,
                            len(transcript),
                        )
                        return TierResult(
                            tier=TierName.YTDLP_PLAYER_ROTATION,
                            transcript=transcript,
                            success=True,
                            confidence="high",
                            latency_ms=latency,
                            extra={
                                "player_client": client,
                                "impersonate": "chrome",
                                "pot_provider_url_configured": bool(pot_provider_url),
                                "title": info.get("title", ""),
                            },
                        )
            except Exception as exc:
                logger.warning(
                    "[yt-tier3] client=%s failed: %s", client, str(exc)[:200]
                )
                continue

    return TierResult(
        tier=TierName.YTDLP_PLAYER_ROTATION,
        transcript="",
        success=False,
        latency_ms=int((time.monotonic() - start) * 1000),
        error="all player clients failed even with cookies+impersonate+PO-token",
    )


def _vtt_to_plaintext(vtt: str) -> str:
    """Convert WEBVTT into de-duplicated text with coarse grounding timestamps."""

    cue_entries: list[str] = []
    current_timestamp: str | None = None
    current_lines: list[str] = []
    skip_block = False
    last_text: str | None = None

    def flush_current() -> None:
        nonlocal current_lines, current_timestamp, last_text
        if not current_lines:
            current_timestamp = None
            return
        text = " ".join(current_lines).strip()
        current_lines = []
        if not text or text == last_text:
            current_timestamp = None
            return
        last_text = text
        if current_timestamp:
            cue_entries.append(f"[{current_timestamp}] {text}")
        else:
            cue_entries.append(text)
        current_timestamp = None

    for raw in vtt.splitlines():
        line = raw.strip()

        if skip_block:
            if not line:
                skip_block = False
            continue

        if not line:
            flush_current()
            continue
        if line == "WEBVTT":
            continue
        if line.startswith(("NOTE", "STYLE")):
            flush_current()
            skip_block = True
            continue
        if re.match(r"^\d+$", line) and not current_lines and current_timestamp is None:
            continue

        timing_match = re.match(
            r"(?P<start>\d{1,2}:\d{2}:\d{2}\.\d{3})\s*-->",
            line,
        )
        if timing_match:
            flush_current()
            current_timestamp = _format_vtt_timestamp(timing_match.group("start"))
            continue

        cleaned = re.sub(r"<[^>]+>", "", line).strip()
        if cleaned:
            current_lines.append(cleaned)

    flush_current()
    return " ".join(cue_entries)


def _format_vtt_timestamp(timestamp: str) -> str:
    hours, minutes, remainder = timestamp.split(":")
    seconds = remainder.split(".", 1)[0]
    if hours == "00":
        return f"{minutes}:{seconds}"
    return f"{int(hours)}:{minutes}:{seconds}"


async def tier_transcript_api_via_webshare(video_id: str, config: dict) -> TierResult:
    """Tier 2: youtube-transcript-api routed through Webshare free-tier residential
    proxies. Handles cases where Gemini's US-edge fetcher can't reach the video
    (region-lock visible from US but accessible from rotating residential IPs).
    DO NOT call this tier from a datacenter IP without a proxy — it will fail
    with `IpBlocked`. Reuses TierName.TRANSCRIPT_API_DIRECT to avoid enum churn."""
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api.proxies import WebshareProxyConfig

    start = time.monotonic()
    cfg = config.get("transcript_api", {}) if isinstance(config, dict) else {}
    proxy_url = os.environ.get("YT_TRANSCRIPT_PROXY_URL", "")
    languages = cfg.get(
        "languages", config.get("transcript_languages", ["en", "en-US", "en-GB"])
    )

    if not proxy_url:
        return TierResult(
            tier=TierName.TRANSCRIPT_API_DIRECT,
            transcript="",
            success=False,
            latency_ms=0,
            error="YT_TRANSCRIPT_PROXY_URL not configured — see docs/runbooks/yt-fallback-stack.md",
        )

    try:
        # WebshareProxyConfig expects username + password — operator sets them
        # via YT_TRANSCRIPT_PROXY_USER / YT_TRANSCRIPT_PROXY_PASS or via combined
        # YT_TRANSCRIPT_PROXY_URL=http://user:pass@proxy.webshare.io:port format.
        user = os.environ.get("YT_TRANSCRIPT_PROXY_USER", "")
        password = os.environ.get("YT_TRANSCRIPT_PROXY_PASS", "")
        api = YouTubeTranscriptApi(
            proxy_config=(
                WebshareProxyConfig(proxy_username=user, proxy_password=password)
                if user and password
                else None
            ),
        )
        result = await asyncio.to_thread(api.fetch, video_id, languages=languages)
        text = "\n".join(
            snippet.text for snippet in result.snippets if snippet.text
        ).strip()
        if len(text) < 100:
            return TierResult(
                tier=TierName.TRANSCRIPT_API_DIRECT,
                transcript="",
                success=False,
                error=f"too-short: len={len(text)}",
                latency_ms=int((time.monotonic() - start) * 1000),
            )
        return TierResult(
            tier=TierName.TRANSCRIPT_API_DIRECT,
            transcript=text,
            success=True,
            confidence="high",
            latency_ms=int((time.monotonic() - start) * 1000),
            extra={"path": "transcript_api_webshare", "language": result.language},
        )
    except Exception as exc:
        return TierResult(
            tier=TierName.TRANSCRIPT_API_DIRECT,
            transcript="",
            success=False,
            error=str(exc)[:200],
            latency_ms=int((time.monotonic() - start) * 1000),
        )


# Public pool tiers (`tier_piped_pool`, `tier_invidious_pool`) and their
# shared helpers (`_try_pool`, `_load_health`, `_save_health`, `_is_healthy`,
# `_mark_unhealthy`, `_extract_caption_url_from_pool_response`,
# `_caption_text_to_plaintext`) were removed 2026-05-25 (PR #91). YouTube's
# mass-blocking event on 2024-12-19 left only 6 Invidious instances
# officially listed (down from ~40 in 2023) and Piped's status page itself
# was 502 in April 2025. Maintenance cost > value contributed.
# See `docs/claude_audits/yt_chain_research_2026-05-25.md` §C.
# git log can resurrect the code if YouTube's posture shifts.


async def tier_gemini_audio(video_id: str, config: dict) -> TierResult:
    """Tier 5: download audio locally, then upload bytes to Gemini File API."""
    if not config.get("enable_gemini_audio_fallback", True):
        return TierResult(
            tier=TierName.GEMINI_AUDIO,
            transcript="",
            success=False,
            error="disabled",
        )

    start = time.monotonic()
    max_size_mb = config.get("gemini_audio_max_filesize_mb", 50)
    max_duration_min = config.get("gemini_audio_max_duration_min", 60)
    url = f"https://www.youtube.com/watch?v={video_id}"

    try:
        from yt_dlp import YoutubeDL

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / f"{video_id}.m4a"
            opts = {
                "quiet": True,
                "no_warnings": True,
                "proxy": _yt_proxy_url() or None,
                "format": "bestaudio[ext=m4a]/bestaudio",
                "outtmpl": str(out_path),
                "max_filesize": max_size_mb * 1024 * 1024,
                "match_filter": (
                    lambda info: None
                    if (info.get("duration") or 0) <= max_duration_min * 60
                    else "video too long"
                ),
            }
            with YoutubeDL(opts) as ydl:
                ydl.download([url])

            if not out_path.exists():
                return TierResult(
                    tier=TierName.GEMINI_AUDIO,
                    transcript="",
                    success=False,
                    error="yt-dlp audio download did not produce file",
                    latency_ms=int((time.monotonic() - start) * 1000),
                )

            import google.generativeai as genai

            api_key = _first_available_key()
            if not api_key:
                return TierResult(
                    tier=TierName.GEMINI_AUDIO,
                    transcript="",
                    success=False,
                    error="no gemini key available",
                )

            genai.configure(api_key=api_key)
            uploaded = genai.upload_file(path=str(out_path), mime_type="audio/mp4")
            model = genai.GenerativeModel("gemini-2.5-flash")
            resp = model.generate_content(
                [
                    uploaded,
                    (
                        "Transcribe this audio into plain text with rough timestamps "
                        "every ~60 seconds. Return only the transcription, no preamble."
                    ),
                ]
            )
            text = (resp.text or "").strip()
            if len(text) > 200:
                return TierResult(
                    tier=TierName.GEMINI_AUDIO,
                    transcript=text,
                    success=True,
                    confidence="high",
                    latency_ms=int((time.monotonic() - start) * 1000),
                    extra={"audio_bytes_uploaded": out_path.stat().st_size},
                )
    except Exception as exc:
        return TierResult(
            tier=TierName.GEMINI_AUDIO,
            transcript="",
            success=False,
            error=str(exc),
            latency_ms=int((time.monotonic() - start) * 1000),
        )

    return TierResult(
        tier=TierName.GEMINI_AUDIO,
        transcript="",
        success=False,
        latency_ms=int((time.monotonic() - start) * 1000),
    )


def _first_available_key() -> str | None:
    import os
    from website.features.api_key_switching.key_pool import (
        _load_keys_from_file,
        candidate_api_env_paths,
    )

    for name in ("GEMINI_API_KEY", "GEMINI_API_KEY_1", "GEMINI_API_KEY_2"):
        if os.environ.get(name):
            return os.environ[name]
    if os.environ.get("GEMINI_API_KEYS"):
        for key in os.environ["GEMINI_API_KEYS"].split(","):
            stripped = key.strip()
            if stripped:
                return stripped
    for path in candidate_api_env_paths():
        loaded = _load_keys_from_file(str(path))
        if not loaded:
            continue
        first = loaded[0]
        return first[0] if isinstance(first, tuple) else first
    return None


async def tier_gemini_youtube_url(video_id: str, config: dict) -> TierResult:
    """Tier 1: Gemini 2.5 fileData(YouTube URL). Google fetches video
    server-side, bypassing client-IP bot detection. Public videos only.

    Non-retryable signals (INVALID_ARGUMENT / FAILED_PRECONDITION / NOT_FOUND /
    PERMISSION_DENIED / empty parts) fall through immediately. RESOURCE_EXHAUSTED
    and transient 5xx are retried by the key-pool layer (key rotation + backoff).
    Counts as 1 LLM call against the 3-call summarization budget.
    """
    start = time.monotonic()
    cfg_gem = (
        config.get("gemini_filedata", {}) if isinstance(config, dict) else {}
    )
    if not cfg_gem.get("enabled", True):
        return TierResult(
            tier=TierName.GEMINI_FILEDATA,
            transcript="",
            success=False,
            latency_ms=0,
            error="gemini-filedata-disabled-via-config",
        )

    try:
        from website.features.api_key_switching import get_key_pool
        from website.features.summarization_engine.core.budget import get_budget
    except Exception as exc:  # noqa: BLE001
        return TierResult(
            tier=TierName.GEMINI_FILEDATA,
            transcript="",
            success=False,
            latency_ms=int((time.monotonic() - start) * 1000),
            error=f"import-failure: {exc}",
        )

    prompt = (
        "Transcribe the spoken content of this video verbatim. "
        "Output plain text only — no timestamps, no speaker labels, no headers. "
        "Do not summarize. If the video has no audible speech, output the "
        "visible on-screen text. If the video is empty or unintelligible, "
        "output the single token EMPTY."
    )

    try:
        pool = get_key_pool()
    except Exception as exc:  # noqa: BLE001
        return TierResult(
            tier=TierName.GEMINI_FILEDATA,
            transcript="",
            success=False,
            latency_ms=int((time.monotonic() - start) * 1000),
            error=f"key-pool-unavailable: {exc}",
        )

    try:
        # Transcript fetch is part of the summarization pipeline by spec —
        # account this Gemini call against the 3-call budget.
        get_budget().consume(role="gemini_filedata")
        result = await pool.generate_content_youtube_url(
            video_id=video_id,
            prompt=prompt,
            model_hint=cfg_gem.get("model", "gemini-2.5-flash"),
            temperature=0.0,
            max_output_tokens=cfg_gem.get("max_output_tokens", 8192),
        )
        text = (result.text or "").strip()
        if text == "EMPTY" or len(text) < 100:
            return TierResult(
                tier=TierName.GEMINI_FILEDATA,
                transcript="",
                success=False,
                latency_ms=int((time.monotonic() - start) * 1000),
                error=f"empty-or-too-short: len={len(text)}",
            )
        return TierResult(
            tier=TierName.GEMINI_FILEDATA,
            transcript=text,
            success=True,
            confidence="high",
            latency_ms=int((time.monotonic() - start) * 1000),
            extra={
                "path": "gemini_filedata",
                "model": result.model,
                "key_index": result.key_index,
            },
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        non_retryable = any(
            sig in msg
            for sig in (
                "INVALID_ARGUMENT",
                "FAILED_PRECONDITION",
                "NOT_FOUND",
                "PERMISSION_DENIED",
                "must be public",
                "contents.parts must not be empty",
            )
        )
        return TierResult(
            tier=TierName.GEMINI_FILEDATA,
            transcript="",
            success=False,
            latency_ms=int((time.monotonic() - start) * 1000),
            error=(
                f"{'non-retryable' if non_retryable else 'retryable'}: {msg[:200]}"
            ),
            extra={"non_retryable": non_retryable},
        )


async def tier_metadata_only(video_id: str, config: dict) -> TierResult:
    """Tier 6: yt-dlp metadata-only fallback, with oEmbed + HTML og-tags safety net.

    yt-dlp is routinely blocked on datacenter IPs even for metadata-only
    extraction. When that happens, fall back to YouTube's public oEmbed
    endpoint (title + author, no auth required) and scrape the watch page
    for ``og:title`` / ``og:description``. At least one of these almost
    always returns enough text for the 50-char ingest floor.
    """
    from yt_dlp import YoutubeDL

    start = time.monotonic()
    url = f"https://www.youtube.com/watch?v={video_id}"
    title = ""
    description = ""
    channel = ""
    duration = 0
    ytdlp_err: str | None = None

    try:
        with YoutubeDL(
            {
                "quiet": True,
                "skip_download": True,
                "no_warnings": True,
                "proxy": _yt_proxy_url() or None,
            }
        ) as ydl:
            info = ydl.extract_info(url, download=False) or {}
        title = info.get("title", "") or ""
        description = info.get("description", "") or ""
        channel = info.get("channel", "") or ""
        duration = info.get("duration", 0) or 0
    except Exception as exc:
        ytdlp_err = str(exc)
        logger.warning("[yt-tier6] yt-dlp failed, trying oEmbed/og: %s", exc)

    if not title or not description:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                oembed = await client.get(
                    "https://www.youtube.com/oembed",
                    params={"url": url, "format": "json"},
                )
                if oembed.status_code == 200:
                    data = oembed.json()
                    title = title or data.get("title", "") or ""
                    channel = channel or data.get("author_name", "") or ""
        except Exception as exc:
            logger.warning("[yt-tier6] oEmbed failed: %s", exc)

    if not description:
        try:
            # Trusted-host bypass: `url` here is the YouTube watch URL the
            # extractor already routed via the YouTube source type, so the
            # host is a youtube.com / youtu.be variant. See SSRF audit
            # 2026-05-26.
            async with httpx.AsyncClient(
                timeout=10.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ZettelkastenBot/1.0)"},
            ) as client:
                page = await client.get(url)
                if page.status_code == 200:
                    og_title = re.search(
                        r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"',
                        page.text,
                    )
                    og_desc = re.search(
                        r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"',
                        page.text,
                    )
                    if og_title and not title:
                        title = og_title.group(1)
                    if og_desc and not description:
                        description = og_desc.group(1)
        except Exception as exc:
            logger.warning("[yt-tier6] og-scrape failed: %s", exc)

    text = "\n\n".join(part for part in (title, description) if part)
    raw_text_len = len(text)
    # H4/T6: emit explicit low-confidence signal so the route-boundary quality
    # gate (api/routes.py) can refuse to summarize near-empty metadata via 422
    # rather than silently letting Gemini hallucinate.
    logger.info(
        "[yt-tier-metadata_only] raw_text_len=%d title=%r channel=%r ytdlp_err=%s",
        raw_text_len, title[:80], channel[:80], (ytdlp_err or "")[:120],
    )
    return TierResult(
        tier=TierName.METADATA_ONLY,
        transcript=text,
        success=bool(title or description),
        confidence="low",
        latency_ms=int((time.monotonic() - start) * 1000),
        error=ytdlp_err if not (title or description) else None,
        extra={
            "title": title,
            "channel": channel,
            "duration": duration,
            "path": "metadata_only",
            "metadata_only": True,
            "raw_text_len": raw_text_len,
        },
    )


def build_default_chain(config: dict) -> TranscriptChain:
    """PR #91 (2026-05-25) chain shape — race-first + sequential fallback.

    Stages within the 90 s parent budget:

        RaceStage  Webshare    (15 s cap)  vs   yt-dlp+cookies  (15 s cap)
                   — race window 15 s; first success wins, loser cancelled.

        TierSpec   tier_gemini_youtube_url  (20 s cap) — demoted from T1
                   (flaky per python-genai #1898 truncation, #1359
                   timestamp drift; "preview" feature still).

        TierSpec   tier_gemini_audio        (30 s cap) — audio fallback.

        TierSpec   tier_metadata_only       (5 s cap)  — H2 gate fires here.

    Total worst case: 15 + 20 + 30 + 5 = 70 s — well under the 90 s parent
    budget. Dropped: ``tier_invidious_pool`` + ``tier_piped_pool`` (public
    pools dead post-2024-12-19; see research §C). See
    ``docs/claude_audits/yt_chain_research_2026-05-25.md``.
    """
    budget_ms = config.get("transcript_budget_ms", 90000)
    return TranscriptChain(
        stages=[
            RaceStage(
                specs=(
                    TierSpec(
                        fn=tier_transcript_api_via_webshare,
                        name="transcript_api_webshare",
                        cap_ms=15_000,
                    ),
                    TierSpec(
                        fn=tier_ytdlp_cookies_impersonate,
                        name="ytdlp_cookies_impersonate",
                        cap_ms=15_000,
                    ),
                ),
                cap_ms=15_000,
            ),
            TierSpec(
                fn=tier_gemini_youtube_url,
                name="gemini_youtube_url",
                cap_ms=20_000,
            ),
            TierSpec(
                fn=tier_gemini_audio,
                name="gemini_audio",
                cap_ms=30_000,
            ),
            TierSpec(
                fn=tier_metadata_only,
                name="metadata_only",
                cap_ms=5_000,
            ),
        ],
        budget_ms=budget_ms,
    )
