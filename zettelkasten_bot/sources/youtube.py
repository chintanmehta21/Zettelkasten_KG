"""YouTube content extractor using youtube-transcript-api and yt-dlp.

Fetches video transcript (auto-generated or manual) and metadata (title,
channel, duration, description, publish date) without downloading the video.

All blocking I/O is offloaded to a thread pool via ``asyncio.to_thread``
so the Telegram event loop stays responsive.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from zettelkasten_bot.models.capture import ExtractedContent, SourceType
from zettelkasten_bot.sources.base import SourceExtractor

logger = logging.getLogger(__name__)

# Timeouts (seconds) — generous enough for slow connections, tight enough
# to avoid blocking the bot on Render.com's free tier.
_YTDLP_TIMEOUT = 30
_TRANSCRIPT_TIMEOUT = 15


def _extract_video_id(url: str) -> str | None:
    """Extract video ID from various YouTube URL formats.

    Handles: /watch?v=, youtu.be/, /embed/, /shorts/, /live/, /v/, /e/,
    and the youtube-nocookie.com privacy variant.

    Uses ``urllib.parse`` for /watch URLs so ``v=`` is found regardless
    of its position in the query string (critical after normalize_url
    sorts query parameters).
    """
    import urllib.parse

    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""

    # /watch?v= — extract from query string (position-independent)
    if ("youtube.com" in host or "youtube-nocookie.com" in host) and "/watch" in parsed.path:
        qs = urllib.parse.parse_qs(parsed.query)
        v_values = qs.get("v", [])
        if v_values and re.fullmatch(r'[a-zA-Z0-9_-]{11}', v_values[0]):
            return v_values[0]

    # youtu.be/<id>
    if host.endswith("youtu.be"):
        vid = parsed.path.lstrip("/")[:11]
        if re.fullmatch(r'[a-zA-Z0-9_-]{11}', vid):
            return vid

    # Path-based patterns: /embed/<id>, /shorts/<id>, /live/<id>, /v/<id>, /e/<id>
    match = re.search(r'/(?:embed|shorts|live|v|e)/([a-zA-Z0-9_-]{11})', parsed.path)
    if match:
        return match.group(1)

    return None


def _fetch_metadata_sync(url: str) -> dict[str, Any] | None:
    """Fetch video metadata via yt-dlp (runs in thread pool)."""
    import yt_dlp

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "no_check_certificates": True,
        "socket_timeout": 15,
        "format": "worst",
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


def _fetch_transcript_sync(video_id: str) -> str | None:
    """Fetch transcript via youtube-transcript-api (runs in thread pool)."""
    from youtube_transcript_api import YouTubeTranscriptApi

    ytt_api = YouTubeTranscriptApi()
    transcript = ytt_api.fetch(video_id)
    return " ".join(snippet.text for snippet in transcript)


def _fetch_subtitles_via_ytdlp_sync(url: str) -> str | None:
    """Fallback: extract auto-generated subtitles via yt-dlp."""
    import yt_dlp

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "no_check_certificates": True,
        "socket_timeout": 15,
        "writeautomaticsub": True,
        "writesubtitles": True,
        "subtitleslangs": ["en", "en-orig"],
        "format": "worst",
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if not info:
            return None

        # Try requested_subtitles first (populated when writesubtitles is set)
        req_subs = info.get("requested_subtitles") or {}
        for lang in ("en", "en-orig", "en-US"):
            if lang in req_subs and req_subs[lang].get("data"):
                return _parse_vtt_text(req_subs[lang]["data"])

    return None


def _parse_vtt_text(vtt_data: str) -> str:
    """Extract plain text from VTT subtitle data."""
    lines = []
    for line in vtt_data.split("\n"):
        line = line.strip()
        # Skip VTT headers, timestamps, and empty lines
        if (
            not line
            or "-->" in line
            or line.startswith("WEBVTT")
            or line.startswith("Kind:")
            or line.startswith("Language:")
        ):
            continue
        if line.isdigit():
            continue
        clean = re.sub(r"<[^>]+>", "", line)
        if clean and clean not in lines:
            lines.append(clean)
    return " ".join(lines)


class YouTubeExtractor(SourceExtractor):
    """Extract transcript and metadata from YouTube videos."""

    source_type = SourceType.YOUTUBE

    async def extract(self, url: str) -> ExtractedContent:
        """Extract YouTube video transcript and metadata.

        Metadata (yt-dlp) and transcript are fetched in parallel to cut
        total wall-clock time roughly in half.
        """
        video_id = _extract_video_id(url)
        if not video_id:
            raise ValueError(f"Cannot extract video ID from URL: {url}")

        parts: list[str] = []
        metadata: dict[str, Any] = {"video_id": video_id}
        title = ""

        # ── Fetch metadata + transcript in parallel ──────────────────────
        async def _get_metadata() -> dict[str, Any] | None:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(_fetch_metadata_sync, url),
                    timeout=_YTDLP_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning("yt-dlp metadata timed out after %ds for %s", _YTDLP_TIMEOUT, url)
            except Exception as exc:
                logger.warning("yt-dlp metadata extraction failed for %s: %s", url, exc)
            return None

        async def _get_transcript() -> str | None:
            # 1. Primary: youtube-transcript-api (fastest)
            try:
                text = await asyncio.wait_for(
                    asyncio.to_thread(_fetch_transcript_sync, video_id),
                    timeout=_TRANSCRIPT_TIMEOUT,
                )
                if text:
                    return text
            except asyncio.TimeoutError:
                logger.warning("Transcript API timed out after %ds for %s", _TRANSCRIPT_TIMEOUT, url)
            except Exception as exc:
                logger.warning("Transcript API failed for %s: %s", url, exc)

            # 2. Fallback: yt-dlp subtitle extraction
            try:
                text = await asyncio.wait_for(
                    asyncio.to_thread(_fetch_subtitles_via_ytdlp_sync, url),
                    timeout=_YTDLP_TIMEOUT,
                )
                if text:
                    logger.info("Got transcript via yt-dlp subtitles for %s", url)
                    return text
            except asyncio.TimeoutError:
                logger.warning("yt-dlp subtitle extraction timed out for %s", url)
            except Exception as exc:
                logger.warning("yt-dlp subtitle extraction failed for %s: %s", url, exc)
            return None

        info, transcript_text = await asyncio.gather(
            _get_metadata(), _get_transcript()
        )

        # ── Process metadata ─────────────────────────────────────────────
        if info:
            metadata["channel"] = info.get("channel") or info.get("uploader", "")
            metadata["duration_seconds"] = info.get("duration", 0)
            metadata["view_count"] = info.get("view_count", 0)
            metadata["upload_date"] = info.get("upload_date", "")
            metadata["description"] = (info.get("description") or "")[:500]
            metadata["like_count"] = info.get("like_count", 0)
            title = info.get("title", "")

        # ── Build body from transcript or fallback ───────────────────────
        if transcript_text:
            parts.append(f"## Transcript\n\n{transcript_text}")
            metadata["has_transcript"] = True
        elif metadata.get("description"):
            parts.append(
                f"## Video Description\n\n{metadata['description']}\n\n"
                f"(Transcript not available — summarizing from description)"
            )
            metadata["has_transcript"] = False
        else:
            metadata["has_transcript"] = False
            parts.append("## Transcript\n\n(Transcript not available for this video)")

        if not title:
            title = f"YouTube Video {video_id}"

        body = "\n\n".join(parts) if parts else "(No content extracted)"

        return ExtractedContent(
            url=url,
            source_type=SourceType.YOUTUBE,
            title=title,
            body=body,
            metadata=metadata,
        )
