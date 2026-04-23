"""Dynamic composition of Reddit DetailedSummarySection hierarchy.

The extractor routes RedditStructuredPayload through this module so the
renderer (``website/core/pipeline.py::_render_detailed_summary``) receives
populated ``sub_sections`` rather than raw schema-key headings. Keeping the
layout here — not in common/structured.py — mirrors the youtube/layout.py
pattern and lets us unit-test without importing the extractor.
"""
from __future__ import annotations

import re
from typing import Iterable

from website.features.summarization_engine.core.models import DetailedSummarySection
from website.features.summarization_engine.summarization.reddit.schema import (
    RedditCluster,
    RedditStructuredPayload,
)

_PLACEHOLDER_TOKENS = {"", "n/a", "none", "null"}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _first_sentence(text: str) -> str:
    cleaned = _clean(text)
    if not cleaned:
        return ""
    match = re.match(r".+?[.!?]", cleaned)
    return match.group(0).strip() if match else cleaned


def _ensure_sentence(text: str) -> str:
    """Force a complete sentence terminator on non-empty text."""
    cleaned = _clean(text).rstrip(",;:")
    if not cleaned:
        return ""
    if cleaned.endswith((".", "!", "?")):
        return cleaned
    return f"{cleaned}."


def _drop_placeholder(text: str) -> str:
    cleaned = _clean(text)
    return "" if cleaned.lower() in _PLACEHOLDER_TOKENS else cleaned


def _overview_section(payload: RedditStructuredPayload) -> DetailedSummarySection:
    primary = _first_sentence(payload.brief_summary) or "Reddit thread captured in the Zettelkasten."
    subs: dict[str, list[str]] = {}

    op_intent = _drop_placeholder(payload.detailed_summary.op_intent)
    if op_intent:
        subs["OP intent"] = [_ensure_sentence(op_intent)]

    mod_ctx = _drop_placeholder(payload.detailed_summary.moderation_context or "")
    if mod_ctx:
        subs["Moderation context"] = [_ensure_sentence(mod_ctx)]

    return DetailedSummarySection(
        heading="Overview",
        bullets=[primary],
        sub_sections=subs,
    )


def _cluster_bullets(cluster: RedditCluster) -> list[str]:
    """Reasoning + representative examples, sentence-cleaned."""
    bullets: list[str] = []
    reasoning = _drop_placeholder(cluster.reasoning)
    if reasoning:
        bullets.append(_ensure_sentence(reasoning))
    for example in cluster.examples or []:
        cleaned = _drop_placeholder(example)
        if cleaned:
            bullets.append(_ensure_sentence(cleaned))
    return bullets


def _reply_clusters_section(
    payload: RedditStructuredPayload,
) -> DetailedSummarySection | None:
    subs: dict[str, list[str]] = {}
    for cluster in payload.detailed_summary.reply_clusters or []:
        theme = _drop_placeholder(cluster.theme) or "Reply cluster"
        bullets = _cluster_bullets(cluster)
        if not bullets:
            continue
        base = theme
        key, idx = base, 2
        while key in subs:
            key = f"{base} ({idx})"
            idx += 1
        subs[key] = bullets
    if not subs:
        return None
    return DetailedSummarySection(
        heading="Reply clusters",
        bullets=[],
        sub_sections=subs,
    )


def _list_section(
    heading: str,
    items: Iterable[str],
) -> DetailedSummarySection | None:
    bullets = [_ensure_sentence(_drop_placeholder(i)) for i in (items or [])]
    bullets = [b for b in bullets if b]
    if not bullets:
        return None
    return DetailedSummarySection(heading=heading, bullets=bullets)


def _closing_remarks_section(
    payload: RedditStructuredPayload,
) -> DetailedSummarySection:
    """Synthesized closing takeaway derived from the rich payload.

    Reddit's schema has no explicit closing field — we synthesize one from
    the unresolved questions or moderation caveats so every summary has a
    stable 'Closing remarks' section for downstream rendering.
    """
    questions = [
        _drop_placeholder(q) for q in (payload.detailed_summary.unresolved_questions or [])
    ]
    questions = [q for q in questions if q]
    counters = [
        _drop_placeholder(c) for c in (payload.detailed_summary.counterarguments or [])
    ]
    counters = [c for c in counters if c]

    if questions:
        takeaway = _ensure_sentence(
            f"Open question still active in the thread: {questions[0].rstrip('.?!')}"
        )
    elif counters:
        takeaway = _ensure_sentence(
            f"Main counterpoint to watch: {counters[0].rstrip('.?!')}"
        )
    else:
        takeaway = "The thread reached rough consensus with no major unresolved questions."

    return DetailedSummarySection(heading="Closing remarks", bullets=[takeaway])


def compose_reddit_detailed(
    payload: RedditStructuredPayload,
) -> list[DetailedSummarySection]:
    sections: list[DetailedSummarySection] = [_overview_section(payload)]
    walkthrough = _reply_clusters_section(payload)
    if walkthrough is not None:
        sections.append(walkthrough)
    counters = _list_section(
        "Counterarguments",
        payload.detailed_summary.counterarguments or [],
    )
    if counters is not None:
        sections.append(counters)
    questions = _list_section(
        "Open questions",
        payload.detailed_summary.unresolved_questions or [],
    )
    if questions is not None:
        sections.append(questions)
    sections.append(_closing_remarks_section(payload))
    return sections
