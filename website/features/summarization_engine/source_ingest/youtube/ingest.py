"""YouTube ingestor - free 5-tier fallback chain plus metadata-only last resort."""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.source_ingest.base import BaseIngestor
from website.features.summarization_engine.source_ingest.utils import (
    join_sections,
    query_param,
    utc_now,
)
from website.features.summarization_engine.source_ingest.youtube.tiers import (
    TierName,
    build_default_chain,
)

logger = logging.getLogger(__name__)


class YouTubeIngestor(BaseIngestor):
    source_type = SourceType.YOUTUBE
    version = "2.0.0"

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        video_id = _video_id(url)
        canonical_url = f"https://www.youtube.com/watch?v={video_id}"

        chain = build_default_chain(config)
        tier_result = await chain.run(video_id=video_id, config=config)

        transcript = tier_result.transcript
        metadata: dict[str, Any] = {
            "video_id": video_id,
            "tier_used": tier_result.tier.value,
            "tier_latency_ms": tier_result.latency_ms,
            **tier_result.extra,
        }

        sections = {
            "Video": metadata.get("title") or "",
            "Channel": metadata.get("channel") or "",
            "Transcript": transcript,
        }
        raw_text = join_sections(sections)

        if tier_result.tier == TierName.METADATA_ONLY:
            confidence = "low"
            reason = "All transcript tiers failed; metadata-only fallback (composite capped at 75)"
        elif tier_result.success:
            confidence = tier_result.confidence
            reason = f"transcript via tier={tier_result.tier.value} len={len(transcript)}"
        else:
            confidence = "low"
            reason = f"All tiers failed; last error: {tier_result.error}"

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
            ingestor_version=self.version,
        )


def _video_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname and "youtu.be" in parsed.hostname:
        return parsed.path.strip("/")
    if value := query_param(url, "v"):
        return value
    match = re.search(r"/(?:shorts|embed)/([^/?#]+)", parsed.path)
    return match.group(1) if match else parsed.path.strip("/")
