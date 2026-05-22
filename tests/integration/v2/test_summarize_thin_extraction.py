"""SE-03: pre-Gemini hard-fail modes MUST raise BEFORE the LLM call.

CONTRACT CHANGE (D7/D8 quarantine-first, 2026-05-18): the old gate
``_MIN_CONTENT_CHARS = 50`` unconditionally raised ``ExtractionConfidenceError``
for ANY near-empty extraction regardless of confidence. That had a large
false-positive blast radius (legit short posts), so it was replaced by a
2-signal gate: trigger ONLY when ``extraction_confidence == "low"`` AND the
stripped content is below a per-source floor; confidence in {medium, high}
is NEVER gated. On trigger the DEFAULT is QUARANTINE (summarize + persist,
tag ``quality_flag="thin"`` — covered by the unit suite
``test_orchestrator_quarantine.py``). The hard-REJECT tier (raise before
Gemini, zettel never saved) still exists but is operator-gated behind
``RAG_THIN_EXTRACTION_REJECT_ENABLED`` (default OFF).

This integration module's unique value is the anti-pattern guard that the
``gemini_client`` is NEVER touched on a pre-Gemini *raise* path. That now
applies to:

  * ``ExtractionConfidenceError`` — low-confidence + below-floor extraction
    WITH the operator reject tier enabled. Gemini is never called.
  * ``NewsletterURLUnreachable`` — newsletter preflight probe failed
    (unchanged; independent of the thin gate). Re-raised for callers.

We use an exploding stub that raises on any attribute access to prove it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from website.features.summarization_engine.core.errors import (
    ExtractionConfidenceError,
    NewsletterURLUnreachable,
)
from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.core.orchestrator import (
    summarize_url_bundle,
)


_USER = uuid.UUID("00000000-0000-0000-0000-000000000001")


class _ExplodingClient:
    """Any attribute access fails, proving Gemini is not invoked."""

    def __getattr__(self, name):  # noqa: D401
        raise AssertionError(
            f"Gemini was called for a pre-Gemini failure case (attr={name!r})"
        )


class _StubIngestor:
    """Registry-resolved ingestor replacement for pre-cooked results/errors."""

    version = "test-1.0.0"

    def __init__(
        self,
        *,
        raw_text: str = "",
        raise_exc: Exception | None = None,
        extraction_confidence: str = "medium",
        tier_used: str | None = None,
    ):
        self._raw_text = raw_text
        self._raise = raise_exc
        self._conf = extraction_confidence
        self._tier_used = tier_used

    async def ingest(self, url, *, config):
        if self._raise is not None:
            raise self._raise
        metadata: dict = {"title": "stub"}
        if self._tier_used is not None:
            metadata["tier_used"] = self._tier_used
        return IngestResult(
            source_type=SourceType.WEB,
            url=url,
            original_url=url,
            raw_text=self._raw_text,
            sections={"Article": self._raw_text},
            metadata=metadata,
            extraction_confidence=self._conf,
            confidence_reason="stub",
            fetched_at=datetime.now(timezone.utc),
            ingestor_version="test-1.0.0",
        )


@pytest.fixture
def patched_orchestrator(monkeypatch):
    """Patch the ingestor registry and disable the filesystem ingest cache."""

    state = {"ingestor": None}

    from website.features.summarization_engine.core import orchestrator as orch_mod

    def fake_get_ingestor(_st):
        return lambda: state["ingestor"]

    monkeypatch.setattr(orch_mod, "get_ingestor", fake_get_ingestor)
    monkeypatch.setattr(orch_mod._INGEST_CACHE, "get", lambda *_a, **_kw: None)
    monkeypatch.setattr(orch_mod._INGEST_CACHE, "put", lambda *_a, **_kw: None)

    def _set(stub):
        state["ingestor"] = stub
        return stub

    return _set


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_text",
    [
        "",
        "tiny",
        "## Video\n## Transcript\n## Description\nChannel:",
        "x" * 49,
    ],
)
async def test_low_conf_thin_reject_tier_raises_before_gemini(
    patched_orchestrator, raw_text, monkeypatch
) -> None:
    """D7/D8 reject tier (operator-gated, RAG_THIN_EXTRACTION_REJECT_ENABLED
    =true): low-confidence extraction below the per-source floor MUST raise
    ``ExtractionConfidenceError`` BEFORE Gemini. The stub is forced to
    ``extraction_confidence="low"`` because the new gate triggers ONLY on
    low confidence (medium/high are never gated — see the medium test
    below). Gemini is never called (exploding client proves it)."""
    monkeypatch.setenv("RAG_THIN_EXTRACTION_REJECT_ENABLED", "true")
    patched_orchestrator(
        _StubIngestor(raw_text=raw_text, extraction_confidence="low")
    )
    with pytest.raises(ExtractionConfidenceError) as ei:
        await summarize_url_bundle(
            "https://example.com/thin",
            user_id=_USER,
            gemini_client=_ExplodingClient(),
            source_type=SourceType.WEB,
        )
    assert ei.value.url == "https://example.com/thin"


@pytest.mark.asyncio
@pytest.mark.parametrize("raw_text", ["tiny", "x" * 49])
async def test_medium_conf_thin_is_not_gated_reaches_gemini(
    patched_orchestrator, raw_text, monkeypatch
) -> None:
    """D7/D8 false-positive fix: medium-confidence content below the floor
    must NOT raise the pre-Gemini reject (the old <50-char hard gate did,
    killing legit short posts). It is never gated, so the orchestrator
    proceeds to the summarizer — proven here by the exploding client being
    reached (``AssertionError`` from Gemini access, NOT
    ``ExtractionConfidenceError``). Reject tier explicitly ON to show even
    then medium is exempt."""
    monkeypatch.setenv("RAG_THIN_EXTRACTION_REJECT_ENABLED", "true")
    patched_orchestrator(
        _StubIngestor(raw_text=raw_text, extraction_confidence="medium")
    )
    with pytest.raises(AssertionError) as ei:
        await summarize_url_bundle(
            "https://example.com/short",
            user_id=_USER,
            gemini_client=_ExplodingClient(),
            source_type=SourceType.WEB,
        )
    assert "Gemini was called" in str(ei.value) or "attr=" in str(ei.value)


@pytest.mark.asyncio
async def test_thin_extraction_above_threshold_does_call_gemini(
    patched_orchestrator,
) -> None:
    body = "real article body " * 10
    patched_orchestrator(_StubIngestor(raw_text=body))

    with pytest.raises(AssertionError) as ei:
        await summarize_url_bundle(
            "https://example.com/real",
            user_id=_USER,
            gemini_client=_ExplodingClient(),
            source_type=SourceType.WEB,
        )
    assert "Gemini was called" in str(ei.value) or "attr=" in str(ei.value)


@pytest.mark.asyncio
async def test_metadata_only_thin_refuses_without_reject_flag(
    patched_orchestrator, monkeypatch
) -> None:
    """2026-05-22 incident fix: a metadata-only tier + below-floor extraction
    is refused UNCONDITIONALLY — RAG_THIN_EXTRACTION_REJECT_ENABLED is left
    unset (default OFF). No transcript means the LLM would summarize a bare
    title/description; refuse before Gemini."""
    monkeypatch.delenv("RAG_THIN_EXTRACTION_REJECT_ENABLED", raising=False)
    patched_orchestrator(
        _StubIngestor(
            raw_text="short metadata blurb " * 6,  # ~126 chars, < 500 floor
            extraction_confidence="low",
            tier_used="metadata_only",
        )
    )
    with pytest.raises(ExtractionConfidenceError) as ei:
        await summarize_url_bundle(
            "https://example.com/meta-only",
            user_id=_USER,
            gemini_client=_ExplodingClient(),
            source_type=SourceType.WEB,
        )
    assert ei.value.url == "https://example.com/meta-only"


@pytest.mark.asyncio
async def test_metadata_only_above_floor_still_summarizes(
    patched_orchestrator, monkeypatch
) -> None:
    """Blast-radius bound: a metadata-only tier whose description clears the
    floor is NOT refused — it still reaches the summarizer (low confidence,
    but enough text to summarize faithfully)."""
    monkeypatch.delenv("RAG_THIN_EXTRACTION_REJECT_ENABLED", raising=False)
    patched_orchestrator(
        _StubIngestor(
            raw_text="rich video description sentence. " * 30,  # > 500 chars
            extraction_confidence="low",
            tier_used="metadata_only",
        )
    )
    with pytest.raises(AssertionError) as ei:
        await summarize_url_bundle(
            "https://example.com/meta-rich",
            user_id=_USER,
            gemini_client=_ExplodingClient(),
            source_type=SourceType.WEB,
        )
    assert "Gemini was called" in str(ei.value) or "attr=" in str(ei.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw_text", ["", "tiny", "x" * 49])
async def test_near_empty_low_conf_refuses_without_reject_flag(
    patched_orchestrator, raw_text, monkeypatch
) -> None:
    """Near-empty (<50 chars) low-confidence extraction is refused
    unconditionally regardless of tier — "never summarize empty input"."""
    monkeypatch.delenv("RAG_THIN_EXTRACTION_REJECT_ENABLED", raising=False)
    patched_orchestrator(
        _StubIngestor(raw_text=raw_text, extraction_confidence="low")
    )
    with pytest.raises(ExtractionConfidenceError):
        await summarize_url_bundle(
            "https://example.com/empty",
            user_id=_USER,
            gemini_client=_ExplodingClient(),
            source_type=SourceType.WEB,
        )


@pytest.mark.asyncio
async def test_newsletter_unreachable_raises_before_gemini(
    patched_orchestrator,
) -> None:
    patched_orchestrator(
        _StubIngestor(
            raise_exc=NewsletterURLUnreachable(
                url="https://dead.substack.com/p/post",
                status=404,
                reason="not_found",
            )
        )
    )
    with pytest.raises(NewsletterURLUnreachable) as ei:
        await summarize_url_bundle(
            "https://dead.substack.com/p/post",
            user_id=_USER,
            gemini_client=_ExplodingClient(),
            source_type=SourceType.NEWSLETTER,
        )
    assert ei.value.status == 404
    assert ei.value.url == "https://dead.substack.com/p/post"
