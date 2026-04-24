"""Dynamic composition of Newsletter DetailedSummarySection hierarchy.

Newsletter payloads carry a ``NewsletterDetailedPayload`` rich object; this
composer projects it onto the shared Overview → section walkthrough →
Conclusions → Closing remarks format so the renderer emits the same
## / ### / bullet markdown as YouTube/Reddit/GitHub summaries.
"""
from __future__ import annotations

import re

from website.features.summarization_engine.core.models import DetailedSummarySection
from website.features.summarization_engine.summarization.newsletter.schema import (
    NewsletterStructuredPayload,
)

_PLACEHOLDER_TOKENS = {"", "n/a", "none", "null"}
_STANCE_BLURBS = {
    "optimistic": "The piece takes an optimistic stance.",
    "skeptical": "The piece takes a skeptical stance.",
    "cautionary": "The piece adopts a cautionary stance.",
    "neutral": "The piece keeps a neutral stance.",
    "mixed": "The piece weighs mixed views.",
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _split_sentences(text: str) -> list[str]:
    cleaned = _clean(text)
    if not cleaned:
        return []
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", cleaned) if s.strip()]


def _ensure_sentence(text: str) -> str:
    cleaned = _clean(text).rstrip(",;:")
    if not cleaned:
        return ""
    if cleaned.endswith((".", "!", "?")):
        return cleaned
    return f"{cleaned}."


def _drop_placeholder(text: str) -> str:
    cleaned = _clean(text)
    return "" if cleaned.lower() in _PLACEHOLDER_TOKENS else cleaned


def _overview_section(payload: NewsletterStructuredPayload) -> DetailedSummarySection:
    detailed = payload.detailed_summary
    sentences = _split_sentences(payload.brief_summary)
    primary = sentences[0] if sentences else _ensure_sentence(detailed.issue_thesis)
    if not primary:
        primary = "Newsletter issue captured in the Zettelkasten."

    subs: dict[str, list[str]] = {}
    publication = _drop_placeholder(detailed.publication_identity)
    if publication:
        subs["Publication"] = [publication]

    stance = (detailed.stance or "").lower()
    stance_blurb = _STANCE_BLURBS.get(stance)
    if stance_blurb:
        subs["Stance"] = [stance_blurb]

    thesis = _drop_placeholder(detailed.issue_thesis)
    if thesis and thesis != primary:
        subs["Core argument"] = [_ensure_sentence(thesis)]

    return DetailedSummarySection(
        heading="Overview",
        bullets=[primary],
        sub_sections=subs,
    )


def _sections_walkthrough(
    payload: NewsletterStructuredPayload,
) -> DetailedSummarySection | None:
    subs: dict[str, list[str]] = {}
    for section in payload.detailed_summary.sections or []:
        heading = _drop_placeholder(section.heading) or "Section"
        bullets = [
            _ensure_sentence(_drop_placeholder(b))
            for b in (section.bullets or [])
        ]
        bullets = [b for b in bullets if b]
        if not bullets:
            continue
        key, idx = heading, 2
        while key in subs:
            key = f"{heading} ({idx})"
            idx += 1
        subs[key] = bullets
    if not subs:
        return None
    return DetailedSummarySection(
        heading="Section walkthrough",
        bullets=[],
        sub_sections=subs,
    )


def _conclusions_section(
    payload: NewsletterStructuredPayload,
) -> DetailedSummarySection | None:
    items = payload.detailed_summary.conclusions_or_recommendations or []
    bullets = [_ensure_sentence(_drop_placeholder(i)) for i in items]
    bullets = [b for b in bullets if b]
    if not bullets:
        return None
    return DetailedSummarySection(
        heading="Conclusions and recommendations",
        bullets=bullets,
    )


def _closing_remarks_section(
    payload: NewsletterStructuredPayload,
) -> DetailedSummarySection:
    """Prefer CTA, then last conclusion, then final brief sentence.

    Every newsletter summary terminates on Closing remarks so the renderer
    has a stable tail section and the UI never shows a hanging section list.
    """
    cta = _drop_placeholder(payload.detailed_summary.cta or "")
    if cta:
        return DetailedSummarySection(
            heading="Closing remarks",
            bullets=[_ensure_sentence(cta)],
        )
    conclusions = [
        _drop_placeholder(c)
        for c in (payload.detailed_summary.conclusions_or_recommendations or [])
    ]
    conclusions = [c for c in conclusions if c]
    if conclusions:
        return DetailedSummarySection(
            heading="Closing remarks",
            bullets=[_ensure_sentence(conclusions[-1])],
        )
    sentences = _split_sentences(payload.brief_summary)
    if sentences:
        return DetailedSummarySection(
            heading="Closing remarks",
            bullets=[_ensure_sentence(sentences[-1])],
        )
    return DetailedSummarySection(
        heading="Closing remarks",
        bullets=["The issue stands on its stated thesis without an explicit call to action."],
    )


def compose_newsletter_detailed(
    payload: NewsletterStructuredPayload,
) -> list[DetailedSummarySection]:
    sections: list[DetailedSummarySection] = [_overview_section(payload)]
    walkthrough = _sections_walkthrough(payload)
    if walkthrough is not None:
        sections.append(walkthrough)
    conclusions = _conclusions_section(payload)
    if conclusions is not None:
        sections.append(conclusions)
    sections.append(_closing_remarks_section(payload))
    return sections
