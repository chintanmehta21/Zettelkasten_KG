"""Dynamic composition of GitHub DetailedSummarySection hierarchy.

GitHubStructuredPayload already uses GitHubDetailedSection with populated
``main_stack`` / ``public_interfaces`` / ``usability_signals``; this composer
re-projects the LLM's raw sections into a stable Overview → feature walk-
through → Benchmarks & examples → Closing remarks hierarchy with nested
sub_sections so the renderer emits consistent ## / ### / bullet markdown.
"""
from __future__ import annotations

import re
from typing import Iterable

from website.features.summarization_engine.core.models import DetailedSummarySection
from website.features.summarization_engine.summarization.github.schema import (
    GitHubDetailedSection,
    GitHubStructuredPayload,
)

_PLACEHOLDER_TOKENS = {"", "n/a", "none", "null"}


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


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        cleaned = _drop_placeholder(item)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _overview_section(payload: GitHubStructuredPayload) -> DetailedSummarySection:
    arch_sentences = _split_sentences(payload.architecture_overview)
    primary = arch_sentences[0] if arch_sentences else _first_sentence(payload.brief_summary)
    if not primary:
        primary = "Documented software repository with an explicit public surface."

    subs: dict[str, list[str]] = {}

    if len(arch_sentences) > 1:
        subs["Architecture"] = arch_sentences[1:4]
    elif arch_sentences:
        subs["Architecture"] = [arch_sentences[0]]

    stack: list[str] = []
    for section in payload.detailed_summary:
        stack.extend(section.main_stack or [])
    stack_clean = _dedupe(stack)
    if stack_clean:
        subs["Stack"] = [", ".join(stack_clean[:6])]

    return DetailedSummarySection(
        heading="Overview",
        bullets=[primary],
        sub_sections=subs,
    )


def _first_sentence(text: str) -> str:
    cleaned = _clean(text)
    if not cleaned:
        return ""
    match = re.match(r".+?[.!?]", cleaned)
    return match.group(0).strip() if match else cleaned


def _feature_sub_entries(section: GitHubDetailedSection) -> list[str]:
    """Merge bullets + public_interfaces + usability_signals into one list."""
    entries: list[str] = []
    for bullet in section.bullets or []:
        cleaned = _drop_placeholder(bullet)
        if cleaned:
            entries.append(_ensure_sentence(cleaned))

    interfaces = _dedupe(section.public_interfaces or [])
    if interfaces:
        entries.append(f"Public surface: {', '.join(interfaces[:6])}.")

    signals = _dedupe(section.usability_signals or [])
    if signals:
        entries.append(f"Usability signals: {', '.join(signals[:6])}.")
    return entries


def _features_section(
    payload: GitHubStructuredPayload,
) -> DetailedSummarySection | None:
    subs: dict[str, list[str]] = {}
    for section in payload.detailed_summary or []:
        heading = _drop_placeholder(section.heading) or _drop_placeholder(section.module_or_feature)
        if not heading:
            heading = "Feature"
        bullets = _feature_sub_entries(section)
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
        heading="Features and modules",
        bullets=[],
        sub_sections=subs,
    )


def _benchmarks_section(
    payload: GitHubStructuredPayload,
) -> DetailedSummarySection | None:
    items = payload.benchmarks_tests_examples or []
    bullets = [_ensure_sentence(_drop_placeholder(i)) for i in items]
    bullets = [b for b in bullets if b]
    if not bullets:
        return None
    return DetailedSummarySection(
        heading="Benchmarks and examples",
        bullets=bullets,
    )


def _closing_remarks_section(
    payload: GitHubStructuredPayload,
) -> DetailedSummarySection:
    """Synthesized closing line from the first usability signal or purpose.

    GitHub payloads have no explicit closing field, so we synthesize a
    stable takeaway from the brief summary's last complete sentence (or the
    architecture overview when the brief is unusable) to guarantee every
    summary ends with a Closing remarks section.
    """
    sentences = _split_sentences(payload.brief_summary)
    takeaway = sentences[-1] if sentences else ""
    if not takeaway:
        arch = _split_sentences(payload.architecture_overview)
        takeaway = arch[-1] if arch else ""
    if not takeaway:
        takeaway = "Repository is documented and ready for developer adoption."
    return DetailedSummarySection(
        heading="Closing remarks",
        bullets=[_ensure_sentence(takeaway)],
    )


def compose_github_detailed(
    payload: GitHubStructuredPayload,
) -> list[DetailedSummarySection]:
    sections: list[DetailedSummarySection] = [_overview_section(payload)]
    features = _features_section(payload)
    if features is not None:
        sections.append(features)
    benchmarks = _benchmarks_section(payload)
    if benchmarks is not None:
        sections.append(benchmarks)
    sections.append(_closing_remarks_section(payload))
    return sections
