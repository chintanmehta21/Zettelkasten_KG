"""YouTube ingestor with transcript, yt-dlp, and oEmbed fallback chain."""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import httpx

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.source_ingest.base import BaseIngestor
from website.features.summarization_engine.source_ingest.utils import join_sections, query_param, utc_now

logger = logging.getLogger(__name__)

_OEMBED_URL = "https://www.youtube.com/oembed"
_HTTP_TIMEOUT = 15.0


class YouTubeIngestor(BaseIngestor):
    source_type = SourceType.YOUTUBE

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        video_id = _video_id(url)
        canonical_url = f"https://www.youtube.com/watch?v={video_id}"
        metadata: dict[str, Any] = {"video_id": video_id}
        transcript = _fetch_transcript(video_id, config.get("transcript_languages", ["en"]))
        info: dict[str, Any] = {}
        fallback_source = ""

        if not transcript:
            # Fallback 1: yt-dlp (rich metadata but can be blocked on datacenter IPs)
            if config.get("use_ytdlp_fallback", True):
                clean_url = _strip_playlist_params(url)
                info = _fetch_ytdlp_info(clean_url, expected_id=video_id)
                if info:
                    fallback_source = "yt-dlp"

            # Fallback 2: oEmbed + page meta (always works, no auth needed)
            if not info:
                info = _fetch_oembed_and_meta(canonical_url, video_id)
                if info:
                    fallback_source = "oembed"

            metadata.update({k: info.get(k) for k in ("title", "channel", "duration", "upload_date") if info.get(k)})

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
            reason = f"metadata fallback used via {fallback_source} (no transcript)"

        return IngestResult(
            source_type=self.source_type,
            url=canonical_url,
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


def _fetch_oembed_and_meta(canonical_url: str, video_id: str) -> dict[str, Any]:
    """Fetch video metadata via oEmbed API + page meta tags.

    This fallback is reliable from datacenter IPs because oEmbed and HTML
    meta tags are standard endpoints that YouTube does not block.
    """
    result: dict[str, Any] = {}
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            # Step 1: oEmbed for title and channel
            oembed_resp = client.get(
                _OEMBED_URL,
                params={"url": canonical_url, "format": "json"},
            )
            if oembed_resp.status_code == 200:
                data = oembed_resp.json()
                result["title"] = data.get("title", "")
                result["channel"] = data.get("author_name", "")

            # Step 2: page meta tags for description
            page_resp = client.get(
                canonical_url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ZettelkastenBot/1.0)"},
            )
            if page_resp.status_code == 200:
                text = page_resp.text
                # Try og:description first (usually longer), then meta description
                og_match = re.search(r'<meta\s+property="og:description"\s+content="([^"]*)"', text)
                meta_match = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', text)
                desc = (og_match or meta_match)
                if desc:
                    result["description"] = desc.group(1)

                # Fallback title from og:title if oEmbed missed it
                if not result.get("title"):
                    og_title = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', text)
                    if og_title:
                        result["title"] = og_title.group(1)

        if result.get("title"):
            logger.info(
                "[yt-ingest] oEmbed+meta fallback for %s: title=%s desc_len=%d",
                video_id, result["title"], len(result.get("description", "")),
            )
        return result
    except Exception as exc:
        logger.warning("[yt-ingest] oEmbed+meta fallback failed for %s: %s", video_id, exc)
        return {}


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
