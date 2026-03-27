"""YouTube content extractor using youtube-transcript-api and yt-dlp.

Fetches video transcript (auto-generated or manual) and metadata (title,
channel, duration, description, publish date) without downloading the video.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from zettelkasten_bot.models.capture import ExtractedContent, SourceType
from zettelkasten_bot.sources.base import SourceExtractor

logger = logging.getLogger(__name__)


def _extract_video_id(url: str) -> str | None:
    """Extract video ID from various YouTube URL formats."""
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


class YouTubeExtractor(SourceExtractor):
    """Extract transcript and metadata from YouTube videos."""

    source_type = SourceType.YOUTUBE

    async def extract(self, url: str) -> ExtractedContent:
        """Extract YouTube video transcript and metadata."""
        video_id = _extract_video_id(url)
        if not video_id:
            raise ValueError(f"Cannot extract video ID from URL: {url}")

        parts: list[str] = []
        metadata: dict[str, Any] = {"video_id": video_id}

        # ── Metadata via yt-dlp (no download) ────────────────────────────
        try:
            import yt_dlp

            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "no_check_certificates": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    metadata["channel"] = info.get("channel") or info.get("uploader", "")
                    metadata["duration_seconds"] = info.get("duration", 0)
                    metadata["view_count"] = info.get("view_count", 0)
                    metadata["upload_date"] = info.get("upload_date", "")
                    metadata["description"] = (info.get("description") or "")[:500]
                    metadata["like_count"] = info.get("like_count", 0)
                    title = info.get("title", "")
        except Exception as exc:
            logger.warning("yt-dlp metadata extraction failed for %s: %s", url, exc)
            title = ""

        # ── Transcript via youtube-transcript-api ─────────────────────────
        try:
            from youtube_transcript_api import YouTubeTranscriptApi

            ytt_api = YouTubeTranscriptApi()
            transcript = ytt_api.fetch(video_id)
            transcript_text = " ".join(
                snippet.text for snippet in transcript
            )
            parts.append(f"## Transcript\n\n{transcript_text}")
            metadata["has_transcript"] = True
        except Exception as exc:
            logger.warning("Transcript unavailable for %s: %s", url, exc)
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
