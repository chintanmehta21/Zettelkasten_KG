"""Podcast show-notes ingestor without audio transcription."""
from __future__ import annotations

from typing import Any

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.source_ingest.base import BaseIngestor
from website.features.summarization_engine.source_ingest.utils import extract_html_text, fetch_text, utc_now


class PodcastIngestor(BaseIngestor):
    source_type = SourceType.PODCAST

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        html, final_url = await fetch_text(url, headers={"User-Agent": "zettelkasten-engine/2.0"})
        text, metadata = extract_html_text(html)
        metadata["audio_transcription"] = bool(config.get("audio_transcription", False))
        return IngestResult(
            source_type=self.source_type,
            url=final_url,
            original_url=url,
            raw_text=text,
            sections={"Show Notes": text},
            metadata=metadata,
            extraction_confidence="medium" if text else "low",
            confidence_reason="podcast page show notes extracted",
            fetched_at=utc_now(),
        )
