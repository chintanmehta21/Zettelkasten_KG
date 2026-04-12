"""Generic web page ingestor."""
from __future__ import annotations

from typing import Any

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.source_ingest.base import BaseIngestor
from website.features.summarization_engine.source_ingest.utils import extract_html_text, fetch_text, utc_now


class WebIngestor(BaseIngestor):
    source_type = SourceType.WEB

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; zettelkasten-engine/2.0)"}
        html, final_url = await fetch_text(url, headers=headers)
        text, metadata = extract_html_text(html)
        min_len = int(config.get("min_text_length", 300))
        confidence = "high" if len(text) >= min_len else "low"
        return IngestResult(
            source_type=self.source_type,
            url=final_url,
            original_url=url,
            raw_text=text,
            sections={"Article": text},
            metadata=metadata,
            extraction_confidence=confidence,
            confidence_reason="HTML article text extracted" if confidence == "high" else "extracted text below threshold",
            fetched_at=utc_now(),
        )

