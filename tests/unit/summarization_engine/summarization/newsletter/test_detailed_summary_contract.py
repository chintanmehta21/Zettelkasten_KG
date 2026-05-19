"""DEFECT 3 regression: Newsletter detailed_summary contract.

Live evidence: a Substack URL (adamtooze.substack.com) failed Add-Zettel with
``'tuple' object has no attribute 'heading'``.

ROOT CAUSE: ``NewsletterSummarizer.summarize`` returned
``NewsletterSummaryResult(detailed_summary=payload.detailed_summary)`` where
``payload.detailed_summary`` is a ``NewsletterDetailedPayload`` (a Pydantic
model). Every downstream consumer — ``render_detailed_summary``
(``summarization.summary_dto`` / nexus bulk_import) and
``writers/markdown.py`` — iterates ``result.detailed_summary`` expecting
``DetailedSummarySection`` objects. ``for section in <pydantic model>``
yields ``(field_name, value)`` TUPLES, so ``section.heading`` raised
``AttributeError: 'tuple' object has no attribute 'heading'``.

FIX: ``NewsletterSummaryResult.detailed_summary`` is now
``list[DetailedSummarySection]`` (aligned with Reddit/GitHub/YouTube and the
base ``SummaryResult``); the summarizer converts via
``_coerce_newsletter_detailed`` (== ``_sanitize_composed(
compose_newsletter_detailed(payload))``).

No live network / no LLM.
"""
from __future__ import annotations

import pytest

from website.core.summary_rendering import render_detailed_summary
from website.features.summarization_engine.core.models import (
    DetailedSummarySection,
)
from website.features.summarization_engine.summarization.common.structured import (
    _coerce_newsletter_detailed,
)
from website.features.summarization_engine.summarization.newsletter.schema import (
    NewsletterDetailedPayload,
    NewsletterSection,
    NewsletterStructuredPayload,
    NewsletterSummaryResult,
)
from website.features.summarization_engine.core.models import (
    SourceType,
    SummaryMetadata,
)


def _structured_payload() -> NewsletterStructuredPayload:
    return NewsletterStructuredPayload(
        mini_title="Chartbook 448: the policy turn",
        brief_summary="Adam Tooze unpacks the macro policy turn in detail.",
        tags=[
            "macro",
            "policy",
            "economics",
            "finance",
            "analysis",
            "newsletter",
            "chartbook",
        ],
        detailed_summary=NewsletterDetailedPayload(
            publication_identity="Chartbook",
            issue_thesis="The policy regime is shifting.",
            sections=[
                NewsletterSection(
                    heading="The shift",
                    bullets=["Central banks pivoted.", "Fiscal space narrowed."],
                ),
            ],
            conclusions_or_recommendations=["Watch the bond market."],
            stance="cautionary",
            cta=None,
        ),
    )


def _metadata() -> SummaryMetadata:
    return SummaryMetadata(
        source_type=SourceType.NEWSLETTER,
        url="https://adamtooze.substack.com/p/chartbook-448",
        extraction_confidence="high",
        confidence_reason="ok",
        total_tokens_used=10,
        total_latency_ms=5,
    )


def test_newsletter_summary_result_detailed_summary_is_section_list():
    """The model now enforces ``list[DetailedSummarySection]`` — passing the
    rich payload model (the old bug) must be rejected at validation."""
    sections = _coerce_newsletter_detailed(_structured_payload())
    assert sections and all(
        isinstance(s, DetailedSummarySection) for s in sections
    )
    result = NewsletterSummaryResult(
        mini_title="t",
        brief_summary="b",
        tags=["a", "b", "c", "d", "e", "f", "g"],
        detailed_summary=sections,
        metadata=_metadata(),
    )
    assert isinstance(result.detailed_summary, list)
    assert all(
        isinstance(s, DetailedSummarySection) for s in result.detailed_summary
    )


def test_passing_rich_payload_model_is_rejected():
    """Regression guard: the exact old-bug shape (NewsletterDetailedPayload as
    detailed_summary) must no longer validate into NewsletterSummaryResult."""
    payload = _structured_payload()
    with pytest.raises(Exception):
        NewsletterSummaryResult(
            mini_title="t",
            brief_summary="b",
            tags=["a", "b", "c", "d", "e", "f", "g"],
            detailed_summary=payload.detailed_summary,  # the old bug
            metadata=_metadata(),
        )


def test_render_detailed_summary_no_tuple_attribute_error():
    """The end-to-end repro: render_detailed_summary over the converted
    sections must NOT raise ``'tuple' object has no attribute 'heading'``
    and must emit the section heading + bullets."""
    sections = _coerce_newsletter_detailed(_structured_payload())
    rendered = render_detailed_summary(sections)
    assert "The shift" in rendered
    assert "Central banks pivoted." in rendered


def test_render_over_old_buggy_shape_reproduces_crash():
    """Proves the diagnosed mechanism: iterating the Pydantic payload model
    (the pre-fix value) yields tuples and crashes exactly as observed live."""
    payload = _structured_payload()
    with pytest.raises(AttributeError, match="'tuple' object has no attribute"):
        # This is precisely what render_detailed_summary did pre-fix when the
        # summarizer passed payload.detailed_summary straight through.
        render_detailed_summary(payload.detailed_summary)
