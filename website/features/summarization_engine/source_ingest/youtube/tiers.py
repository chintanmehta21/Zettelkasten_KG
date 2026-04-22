"""YouTube transcript fallback chain scaffold."""
from __future__ import annotations

import logging
import re
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


class TierName(str, Enum):
    YTDLP_PLAYER_ROTATION = "ytdlp_player_rotation"
    TRANSCRIPT_API_DIRECT = "transcript_api_direct"
    PIPED_POOL = "piped_pool"
    INVIDIOUS_POOL = "invidious_pool"
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


class TranscriptChain:
    def __init__(self, tiers: list[TierFn], budget_ms: int = 90000) -> None:
        self._tiers = tiers
        self._budget_ms = budget_ms

    async def run(self, *, video_id: str, config: dict) -> TierResult:
        start = time.monotonic()
        last_result: TierResult | None = None

        for tier in self._tiers:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            if elapsed_ms >= self._budget_ms:
                break
            last_result = await tier(video_id, config)
            if last_result.success:
                return last_result

        return last_result or TierResult(
            tier=TierName.METADATA_ONLY,
            transcript="",
            success=False,
        )


async def tier_ytdlp_player_rotation(video_id: str, config: dict) -> TierResult:
    """Tier 1: yt-dlp with player-client rotation."""
    from yt_dlp import YoutubeDL

    clients = config.get(
        "ytdlp_player_clients",
        ["android_embedded", "ios", "tv_embedded", "mweb", "web"],
    )
    url = f"https://www.youtube.com/watch?v={video_id}"
    start = time.monotonic()

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
                "extractor_args": {"youtube": {"player_client": [client]}},
            }
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
                            "[yt-tier1] player=%s success len=%d", client, len(transcript)
                        )
                        return TierResult(
                            tier=TierName.YTDLP_PLAYER_ROTATION,
                            transcript=transcript,
                            success=True,
                            confidence="high",
                            latency_ms=latency,
                            extra={"player_client": client, "title": info.get("title", "")},
                        )
            except Exception as exc:
                logger.warning("[yt-tier1] player=%s failed: %s", client, exc)
                continue

    return TierResult(
        tier=TierName.YTDLP_PLAYER_ROTATION,
        transcript="",
        success=False,
        latency_ms=int((time.monotonic() - start) * 1000),
        error="all player clients failed",
    )


def _vtt_to_plaintext(vtt: str) -> str:
    """Strip WEBVTT headers, timestamps, and cue metadata; return plain text."""
    lines: list[str] = []
    for raw in vtt.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == "WEBVTT" or line.startswith(("NOTE", "STYLE")):
            continue
        if re.match(r"\d{1,2}:\d{2}:\d{2}\.\d{3}\s*-->", line):
            continue
        if re.match(r"^\d+$", line):
            continue
        line = re.sub(r"<[^>]+>", "", line)
        lines.append(line)

    deduped: list[str] = []
    for line in lines:
        if not deduped or deduped[-1] != line:
            deduped.append(line)
    return " ".join(deduped)


async def tier_transcript_api_direct(video_id: str, config: dict) -> TierResult:
    """Tier 2: youtube-transcript-api direct fetch."""
    start = time.monotonic()
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        api = YouTubeTranscriptApi()
        entries = api.fetch(
            video_id,
            languages=config.get("transcript_languages", ["en"]),
        )
        text = " ".join(item.text for item in entries)
        if len(text) > 100:
            return TierResult(
                tier=TierName.TRANSCRIPT_API_DIRECT,
                transcript=text,
                success=True,
                confidence="high",
                latency_ms=int((time.monotonic() - start) * 1000),
            )
    except Exception as exc:
        return TierResult(
            tier=TierName.TRANSCRIPT_API_DIRECT,
            transcript="",
            success=False,
            error=str(exc),
            latency_ms=int((time.monotonic() - start) * 1000),
        )

    return TierResult(
        tier=TierName.TRANSCRIPT_API_DIRECT,
        transcript="",
        success=False,
        latency_ms=int((time.monotonic() - start) * 1000),
    )
