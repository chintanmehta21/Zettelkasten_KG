"""D7/D8 — thin-extraction QUARANTINE-FIRST gate.

The old single ``_MIN_CONTENT_CHARS = 50`` gate HARD-REJECTED any near-
empty extraction (raised ExtractionConfidenceError, zettel never saved).
That has a large false-positive blast radius (legit short posts).

New 2-signal gate (quarantine-first):
  * if ``extraction_confidence == "low"`` AND stripped-content length is
    below a per-source-type floor (youtube/reddit ~280; generic/arxiv/
    newsletter ~500) -> QUARANTINE: do NOT raise; summarize + persist but
    tag ``ingest_result.metadata["quality_flag"] = "thin"`` so the read
    side can exclude it from retrieval / KG.
  * ``extraction_confidence in {medium, high}`` is NEVER gated regardless
    of length (protects legit short posts).
  * the hard-reject tier still EXISTS but is behind an env flag
    (``RAG_THIN_EXTRACTION_REJECT_ENABLED``) defaulting OFF.

All ingestor/summarizer access mocked; no live network.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from website.features.summarization_engine.core.errors import (
    ExtractionConfidenceError,
)
from website.features.summarization_engine.core.models import (
    DetailedSummarySection,
    IngestResult,
    SourceType,
    SummaryMetadata,
    SummaryResult,
)


def _summary(stype: SourceType) -> SummaryResult:
    meta = SummaryMetadata(
        source_type=stype,
        url="https://x/y",
        extraction_confidence="low",
        confidence_reason="thin",
        total_tokens_used=1,
        gemini_pro_tokens=1,
        gemini_flash_tokens=0,
        total_latency_ms=1,
        cod_iterations_used=1,
        self_check_missing_count=0,
        patch_applied=False,
    )
    return SummaryResult(
        mini_title="t",
        brief_summary="brief",
        tags=["a", "b", "c", "d", "e"],
        detailed_summary=[DetailedSummarySection(heading="H", bullets=["x"])],
        metadata=meta,
    )


def _ingest(stype, url, raw_text, confidence):
    return IngestResult(
        source_type=stype,
        url=url,
        original_url=url,
        raw_text=raw_text,
        extraction_confidence=confidence,
        confidence_reason="reason",
        fetched_at=datetime.now(timezone.utc),
    )


async def _run_bundle(ingest, summary, url):
    from website.features.summarization_engine.core.orchestrator import (
        summarize_url_bundle,
    )

    mock_ingestor = AsyncMock()
    mock_ingestor.ingest.return_value = ingest
    mock_summarizer = AsyncMock()
    mock_summarizer.summarize.return_value = summary

    with patch(
        "website.features.summarization_engine.core.orchestrator.get_ingestor"
    ) as gi, patch(
        "website.features.summarization_engine.core.orchestrator.get_summarizer"
    ) as gs:
        gi.return_value = lambda: mock_ingestor
        gs.return_value = lambda client, config: mock_summarizer
        return await summarize_url_bundle(
            url,
            user_id=UUID("00000000-0000-0000-0000-000000000001"),
            gemini_client=AsyncMock(),
        )


@pytest.mark.asyncio
async def test_low_conf_thin_youtube_is_quarantined_not_rejected(monkeypatch):
    monkeypatch.delenv("RAG_THIN_EXTRACTION_REJECT_ENABLED", raising=False)
    url = "https://www.youtube.com/watch?v=thin123"
    ingest = _ingest(
        SourceType.YOUTUBE, url, "## Video\nSome Title\n## Transcript\n", "low"
    )
    bundle = await _run_bundle(ingest, _summary(SourceType.YOUTUBE), url)
    # NOT raised; persisted bundle carries the thin quality_flag.
    assert bundle.ingest_result.metadata.get("quality_flag") == "thin"


@pytest.mark.asyncio
async def test_medium_confidence_short_body_is_never_gated(monkeypatch):
    """A legit short post with medium confidence must NOT be quarantined
    or rejected even though it is below the byte floor."""
    monkeypatch.delenv("RAG_THIN_EXTRACTION_REJECT_ENABLED", raising=False)
    url = "https://www.reddit.com/r/x/comments/abc/short"
    ingest = _ingest(SourceType.REDDIT, url, "Short but genuine post.", "medium")
    bundle = await _run_bundle(ingest, _summary(SourceType.REDDIT), url)
    assert bundle.ingest_result.metadata.get("quality_flag") != "thin"


@pytest.mark.asyncio
async def test_high_confidence_short_body_is_never_gated(monkeypatch):
    monkeypatch.delenv("RAG_THIN_EXTRACTION_REJECT_ENABLED", raising=False)
    url = "https://example.com/short"
    ingest = _ingest(SourceType.WEB, url, "Tiny but real.", "high")
    bundle = await _run_bundle(ingest, _summary(SourceType.WEB), url)
    assert bundle.ingest_result.metadata.get("quality_flag") != "thin"


@pytest.mark.asyncio
async def test_low_conf_but_above_floor_is_not_quarantined(monkeypatch):
    """Low confidence but the body clears the per-source floor -> still a
    normal summary (only thin AND low triggers quarantine)."""
    monkeypatch.delenv("RAG_THIN_EXTRACTION_REJECT_ENABLED", raising=False)
    url = "https://example.com/article"
    body = "Real article content. " * 60  # ~1300 chars, clears 500 floor
    ingest = _ingest(SourceType.WEB, url, body, "low")
    bundle = await _run_bundle(ingest, _summary(SourceType.WEB), url)
    assert bundle.ingest_result.metadata.get("quality_flag") != "thin"


@pytest.mark.asyncio
async def test_reject_tier_env_flag_on_restores_hard_reject(monkeypatch):
    """The hard-reject tier still exists, gated OFF by default; turning the
    env flag on restores the old ExtractionConfidenceError behavior."""
    monkeypatch.setenv("RAG_THIN_EXTRACTION_REJECT_ENABLED", "true")
    url = "https://www.youtube.com/watch?v=thin999"
    ingest = _ingest(
        SourceType.YOUTUBE, url, "## Video\nX\n## Transcript\n", "low"
    )
    with pytest.raises(ExtractionConfidenceError):
        await _run_bundle(ingest, _summary(SourceType.YOUTUBE), url)


@pytest.mark.asyncio
async def test_reject_tier_default_off_does_not_raise(monkeypatch):
    monkeypatch.delenv("RAG_THIN_EXTRACTION_REJECT_ENABLED", raising=False)
    url = "https://www.youtube.com/watch?v=thin000"
    ingest = _ingest(
        SourceType.YOUTUBE, url, "## Video\nX\n## Transcript\n", "low"
    )
    # default OFF -> quarantine path, no raise
    bundle = await _run_bundle(ingest, _summary(SourceType.YOUTUBE), url)
    assert bundle.ingest_result.metadata.get("quality_flag") == "thin"
