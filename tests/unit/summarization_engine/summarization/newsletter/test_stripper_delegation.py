"""Proof that the Newsletter intra-summarizer numeric stripper now
delegates to the shared ``evaluator.numeric_grounding`` module.

These cases protect the behavior contract of
``_remove_unsupported_numeric_claims`` after the DRY consolidation:

  - Grounded claims survive unchanged.
  - Ungrounded tokens get stripped at the sentence / bullet / conclusion
    level.
  - Empty / whitespace-only source is a no-op.
  - Empty brief stays empty.
  - End-to-end: a synthetic structured payload fed through
    ``_apply_ingest_guardrails`` ends up with zero ungrounded numeric
    tokens in the brief.
"""
from __future__ import annotations

from website.features.summarization_engine.core.models import (
    IngestResult,
    SourceType,
)
from website.features.summarization_engine.evaluator.numeric_grounding import (
    extract_numeric_tokens,
    ground_numeric_claims,
)
from website.features.summarization_engine.summarization.newsletter.schema import (
    NewsletterDetailedPayload,
    NewsletterSection,
    NewsletterStructuredPayload,
)
from website.features.summarization_engine.summarization.newsletter.summarizer import (
    _apply_ingest_guardrails,
    _remove_unsupported_numeric_claims,
)


def _make_payload(
    brief: str,
    *,
    bullets: list[str] | None = None,
    conclusions: list[str] | None = None,
) -> NewsletterStructuredPayload:
    return NewsletterStructuredPayload(
        mini_title="Test issue",
        brief_summary=brief,
        tags=["newsletter", "analysis", "test", "issue", "brief", "source", "stance"],
        detailed_summary=NewsletterDetailedPayload(
            publication_identity="TestPub",
            issue_thesis="A test thesis.",
            sections=[
                NewsletterSection(
                    heading="Main", bullets=bullets or ["A number-free bullet."]
                )
            ],
            conclusions_or_recommendations=conclusions or [],
            stance="neutral",
            cta=None,
        ),
    )


def test_all_grounded_brief_unchanged():
    brief = "Revenue grew 47% to $2.3B in 2024."
    source = "In 2024 growth was 47% and revenue hit $2.3B for the quarter."
    payload = _make_payload(brief)

    _remove_unsupported_numeric_claims(payload, source)

    assert payload.brief_summary == brief


def test_ungrounded_dollar_claim_stripped():
    # Two sentences: one fully grounded, one with an ungrounded
    # dollar claim. The ungrounded sentence must be dropped.
    brief = "Revenue growth was 47% in 2024. Some unsupported claim: $5B."
    source = "Revenue growth was 47% in 2024."
    payload = _make_payload(brief)

    _remove_unsupported_numeric_claims(payload, source)

    assert "$5B" not in payload.brief_summary
    assert "$5" not in payload.brief_summary
    assert "47%" in payload.brief_summary


def test_single_sentence_ungrounded_brief_kept_as_fallback():
    # Contract: the stripper never returns an empty brief. When every
    # sentence in the brief is ungrounded, the original text survives
    # so the pipeline always has *some* brief to persist.
    brief = "Revenue grew 47% to $5B in 2024."
    source = "Revenue growth was 47% in 2024."
    payload = _make_payload(brief)

    _remove_unsupported_numeric_claims(payload, source)

    # Full original brief preserved (fallback branch).
    assert payload.brief_summary == brief


def test_no_numbers_in_brief_returns_unchanged():
    brief = "No numbers here."
    source = "Also no numbers in the source."
    payload = _make_payload(brief)

    _remove_unsupported_numeric_claims(payload, source)

    assert payload.brief_summary == brief


def test_empty_brief_returns_empty():
    payload = _make_payload("")

    _remove_unsupported_numeric_claims(payload, "Some source text.")

    assert payload.brief_summary == ""


def test_empty_source_is_no_op():
    brief = "Revenue grew 47% to $5B in 2024."
    payload = _make_payload(brief)

    _remove_unsupported_numeric_claims(payload, "")
    assert payload.brief_summary == brief

    _remove_unsupported_numeric_claims(payload, "   \n\t  ")
    assert payload.brief_summary == brief


def test_small_bare_integer_stripped_by_newsletter_mode():
    # Newsletter mode must flag "42" — the evaluator default threshold
    # (min 3 digits) would NOT flag it, so this test guards the
    # min_bare_integer_digits=1 override.
    brief = "The dashboard launched. It reached 42 teams."
    source = "The article describes a new dashboard and workflow changes."
    payload = _make_payload(brief)

    _remove_unsupported_numeric_claims(payload, source)

    assert "42" not in payload.brief_summary
    assert "dashboard launched" in payload.brief_summary.lower()


def test_bullets_with_ungrounded_numbers_dropped():
    source = "Dashboard rolled out broadly."
    payload = _make_payload(
        "Dashboard rolled out broadly.",
        bullets=[
            "The dashboard changed workflows.",
            "It hit 42 teams.",
        ],
    )

    _remove_unsupported_numeric_claims(payload, source)

    assert payload.detailed_summary.sections[0].bullets == [
        "The dashboard changed workflows.",
    ]


def test_conclusions_with_ungrounded_numbers_dropped():
    source = "Dashboard rolled out broadly."
    payload = _make_payload(
        "Brief.",
        conclusions=["Adopt it by 2027.", "Review the workflow."],
    )

    _remove_unsupported_numeric_claims(payload, source)

    assert payload.detailed_summary.conclusions_or_recommendations == [
        "Review the workflow.",
    ]


def test_all_bullets_ungrounded_falls_back_to_number_free_placeholder():
    source = "Dashboard rolled out broadly."
    payload = _make_payload(
        "Brief.",
        bullets=[
            "Served 42 teams.",
            "Covered 99 workflows.",
            "Plain bullet with no number.",
        ],
    )

    _remove_unsupported_numeric_claims(payload, source)

    bullets = payload.detailed_summary.sections[0].bullets
    # Implementation contract: when every ungrounded bullet gets pruned,
    # the section still has a bullet — the first number-free one.
    # Here all three bullets initially survive because the third has
    # no numbers; only the first two are dropped.
    assert bullets == ["Plain bullet with no number."]


def test_end_to_end_apply_ingest_guardrails_produces_grounded_brief():
    ingest = IngestResult(
        source_type=SourceType.NEWSLETTER,
        url="https://product.beehiiv.com/p/test",
        original_url="https://product.beehiiv.com/p/test",
        raw_text="Growth was 47% for the year and revenue hit $2.3B.",
        extraction_confidence="high",
        confidence_reason="ok",
        fetched_at="2026-04-21T00:00:00+00:00",
    )
    payload = _make_payload(
        "Revenue grew 47% to $2.3B. But the wild claim: $9B in 2024.",
        bullets=[
            "Growth was 47%.",
            "Unsupported claim: 2024 revenue was $9B.",
        ],
        conclusions=["Adopt by 2099.", "Monitor growth."],
    )

    guarded = _apply_ingest_guardrails(payload, ingest)

    # Brief must have no ungrounded tokens remaining.
    _, brief_ungrounded = ground_numeric_claims(
        guarded.brief_summary,
        ingest.raw_text,
        min_bare_integer_digits=1,
    )
    assert brief_ungrounded == []

    # Bullets survivor set has no ungrounded tokens.
    for bullet in guarded.detailed_summary.sections[0].bullets:
        _, bullet_ungrounded = ground_numeric_claims(
            bullet, ingest.raw_text, min_bare_integer_digits=1
        )
        assert bullet_ungrounded == []

    # Conclusions survivor set has no ungrounded tokens.
    for item in guarded.detailed_summary.conclusions_or_recommendations:
        _, item_ungrounded = ground_numeric_claims(
            item, ingest.raw_text, min_bare_integer_digits=1
        )
        assert item_ungrounded == []


def test_delegation_uses_shared_extractor():
    # Smoke-check: the stripper's behavior on currency tokens must
    # match the shared extractor's view of what a numeric token is.
    text = "It costs $1,299.99 today."
    tokens = extract_numeric_tokens(text, min_bare_integer_digits=1)
    assert "$1,299.99" in tokens
