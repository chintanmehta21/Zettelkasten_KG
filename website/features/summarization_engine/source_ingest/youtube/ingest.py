"""YouTube ingestor with transcript and yt-dlp metadata fallback."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.source_ingest.base import BaseIngestor
from website.features.summarization_engine.source_ingest.utils import join_sections, query_param, utc_now


class YouTubeIngestor(BaseIngestor):
    source_type = SourceType.YOUTUBE

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        video_id = _video_id(url)
        metadata: dict[str, Any] = {"video_id": video_id}
        transcript = _fetch_transcript(video_id, config.get("transcript_languages", ["en"]))
        info = {}
        if not transcript and config.get("use_ytdlp_fallback", True):
            info = _fetch_ytdlp_info(url)
            metadata.update({k: info.get(k) for k in ("title", "channel", "duration", "upload_date")})
        sections = {
            "Video": f"{metadata.get('title') or ''}\nChannel: {metadata.get('channel') or ''}",
            "Transcript": transcript,
            "Description": info.get("description", "") if info else "",
        }
        raw_text = join_sections(sections)
        return IngestResult(
            source_type=self.source_type,
            url=f"https://www.youtube.com/watch?v={video_id}",
            original_url=url,
            raw_text=raw_text,
            sections=sections,
            metadata=metadata,
            extraction_confidence="high" if transcript else ("medium" if info else "low"),
            confidence_reason="transcript fetched" if transcript else "metadata fallback used",
            fetched_at=utc_now(),
        )


def _video_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname and "youtu.be" in parsed.hostname:
        return parsed.path.strip("/")
    if value := query_param(url, "v"):
        return value
    match = re.search(r"/(?:shorts|embed)/([^/?#]+)", parsed.path)
    return match.group(1) if match else parsed.path.strip("/")


def _fetch_transcript(video_id: str, languages: list[str]) -> str:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        api = YouTubeTranscriptApi()
        entries = api.fetch(video_id, languages=languages)
        return " ".join(item.text for item in entries)
    except Exception:
        return ""


def _fetch_ytdlp_info(url: str) -> dict[str, Any]:
    try:
        from yt_dlp import YoutubeDL

        with YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
            return ydl.extract_info(url, download=False) or {}
    except Exception:
        return {}
