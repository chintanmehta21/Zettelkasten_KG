"""YouTube ingestor with transcript and yt-dlp metadata fallback."""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.source_ingest.base import BaseIngestor
from website.features.summarization_engine.source_ingest.utils import join_sections, query_param, utc_now

logger = logging.getLogger(__name__)


class YouTubeIngestor(BaseIngestor):
    source_type = SourceType.YOUTUBE

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        video_id = _video_id(url)
        metadata: dict[str, Any] = {"video_id": video_id}
        transcript = _fetch_transcript(video_id, config.get("transcript_languages", ["en"]))
        info: dict[str, Any] = {}

        if not transcript and config.get("use_ytdlp_fallback", True):
            clean_url = _strip_playlist_params(url)
            info = _fetch_ytdlp_info(clean_url, expected_id=video_id)
            metadata.update({k: info.get(k) for k in ("title", "channel", "duration", "upload_date")})

        sections = {
            "Video": f"{metadata.get('title') or ''}\nChannel: {metadata.get('channel') or ''}",
            "Transcript": transcript,
            "Description": info.get("description", "") if info else "",
        }
        raw_text = join_sections(sections)

        # Guard: if content is too thin, mark as low confidence
        content_len = len(transcript) + len(info.get("description", ""))
        if content_len < 50 and not transcript:
            confidence = "low"
            reason = "no transcript and insufficient metadata — summary may be unreliable"
            logger.warning(
                "[yt-ingest] Very low content for video %s (%d chars). "
                "Summary quality will be poor.",
                video_id, content_len,
            )
        elif transcript:
            confidence = "high"
            reason = "transcript fetched"
        else:
            confidence = "medium"
            reason = "metadata fallback used (no transcript)"

        return IngestResult(
            source_type=self.source_type,
            url=f"https://www.youtube.com/watch?v={video_id}",
            original_url=url,
            raw_text=raw_text,
            sections=sections,
            metadata=metadata,
            extraction_confidence=confidence,
            confidence_reason=reason,
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


def _strip_playlist_params(url: str) -> str:
    """Remove playlist/index params that cause yt-dlp to resolve a different video."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    for key in ("list", "index", "pp", "start_radio"):
        params.pop(key, None)
    clean_query = urlencode(params, doseq=True)
    return urlunparse(parsed._replace(query=clean_query))


def _fetch_transcript(video_id: str, languages: list[str]) -> str:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        api = YouTubeTranscriptApi()
        entries = api.fetch(video_id, languages=languages)
        text = " ".join(item.text for item in entries)
        logger.info("[yt-ingest] Fetched transcript for %s (%d chars)", video_id, len(text))
        return text
    except Exception as exc:
        logger.warning("[yt-ingest] Transcript fetch failed for %s: %s", video_id, exc)
        return ""


def _fetch_ytdlp_info(url: str, *, expected_id: str = "") -> dict[str, Any]:
    try:
        from yt_dlp import YoutubeDL

        with YoutubeDL({"quiet": True, "skip_download": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(url, download=False) or {}

        # Validate that yt-dlp resolved the correct video
        resolved_id = info.get("id", "")
        if expected_id and resolved_id and resolved_id != expected_id:
            logger.warning(
                "[yt-ingest] yt-dlp resolved video %s instead of expected %s — discarding",
                resolved_id, expected_id,
            )
            return {}

        logger.info("[yt-ingest] yt-dlp info for %s: title=%s", expected_id, info.get("title", "?"))
        return info
    except Exception as exc:
        logger.warning("[yt-ingest] yt-dlp failed for %s: %s", url, exc)
        return {}
