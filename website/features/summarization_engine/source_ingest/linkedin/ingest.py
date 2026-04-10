"""Best-effort LinkedIn public post ingestor."""
from __future__ import annotations

from typing import Any

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.source_ingest.base import BaseIngestor
from website.features.summarization_engine.source_ingest.utils import extract_html_text, fetch_text, json_ld_objects, utc_now


class LinkedInIngestor(BaseIngestor):
    source_type = SourceType.LINKEDIN

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        headers = {"User-Agent": "Googlebot/2.1 (+http://www.google.com/bot.html)"}
        html, final_url = await fetch_text(url, headers=headers)
        text, metadata = extract_html_text(html)
        metadata["json_ld"] = json_ld_objects(html)
        login_keywords = config.get("login_wall_keywords", ["authwall", "Join now to see", "Sign in"])
        is_login_wall = any(keyword.lower() in html.lower() for keyword in login_keywords)
        return IngestResult(
            source_type=self.source_type,
            url=final_url,
            original_url=url,
            raw_text=text,
            sections={"Post": text},
            metadata=metadata,
            extraction_confidence="low" if is_login_wall else "medium",
            confidence_reason="LinkedIn login wall detected" if is_login_wall else "public HTML extracted",
            fetched_at=utc_now(),
        )
