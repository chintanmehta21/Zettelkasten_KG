"""Twitter/X ingestor using oEmbed and Nitter fallback."""
from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.source_ingest.base import BaseIngestor
from website.features.summarization_engine.source_ingest.utils import compact_text, fetch_json, fetch_text, join_sections, utc_now


class TwitterIngestor(BaseIngestor):
    source_type = SourceType.TWITTER

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        metadata: dict[str, Any] = {}
        text = ""
        if config.get("use_oembed", True):
            try:
                payload, _ = await fetch_json(f"https://publish.twitter.com/oembed?url={url}")
                metadata["author_name"] = payload.get("author_name")
                html = payload.get("html") or ""
                text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
            except Exception:
                text = ""
        if not text and config.get("use_nitter_fallback", True):
            for instance in config.get("nitter_instances", []):
                try:
                    html, _ = await fetch_text(_to_nitter(url, instance))
                    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
                    if text:
                        metadata["nitter_instance"] = instance
                        break
                except Exception:
                    continue
        sections = {"Tweet": compact_text(text)}
        return IngestResult(
            source_type=self.source_type,
            url=url,
            original_url=url,
            raw_text=join_sections(sections),
            sections=sections,
            metadata=metadata,
            extraction_confidence="medium" if text else "low",
            confidence_reason="tweet text extracted" if text else "tweet text unavailable",
            fetched_at=utc_now(),
        )


def _to_nitter(url: str, instance: str) -> str:
    return url.replace("https://twitter.com", instance).replace("https://x.com", instance)

