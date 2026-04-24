"""Dynamic composition tests for YouTube detailed_summary.

Layout contract: see docs/superpowers/plans/2026-04-23-youtube-summary-hardening.md
Phase 1. Overview section always first with sub_sections 'Format and speakers'
and 'Thesis'; per-chapter sections under a 'Chapter walkthrough' heading;
'Closing remarks' (NOT 'Closing Takeaway') section last when the payload has a
closing_takeaway. No section emits JSON-stringified ChapterBullet payloads.
"""
from __future__ import annotations

import pytest

from website.features.summarization_engine.summarization.youtube.layout import (
    compose_youtube_detailed,
)
from website.features.summarization_engine.summarization.youtube.schema import (
    ChapterBullet,
    YouTubeDetailedPayload,
    YouTubeStructuredPayload,
)


def _payload(**detailed_overrides) -> YouTubeStructuredPayload:
    detailed_kwargs = dict(
        thesis="DMT is under-studied despite being produced in the human body.",
        format="lecture",
        chapters_or_segments=[
            ChapterBullet(
                timestamp="00:15",
                title="Introduction and Pharmacology",
                bullets=[
                    "DMT is a short-acting tryptamine.",
                    "Half-life in plasma is under ten minutes.",
                    "It is produced endogenously in mammals.",
                    "Strassman's pineal gland hypothesis remains unproven.",
                    "Cross-cultural use spans millennia.",
                ],
            ),
        ],
        demonstrations=[],
        closing_takeaway="DMT needs more rigorous clinical study.",
    )
    detailed_kwargs.update(detailed_overrides)
    detailed = YouTubeDetailedPayload(**detailed_kwargs)
    return YouTubeStructuredPayload(
        mini_title="DMT lecture",
        brief_summary=(
            "Joe Rogan explains that DMT is a short-acting tryptamine. "
            "He walks through pharmacology, legal status, and reports. "
            "The closing takeaway is that DMT remains under-studied."
        ),
        tags=[
            "psychedelics", "neuroscience", "lecture",
            "dmt", "pharmacology", "consciousness", "science",
        ],
        speakers=["Joe Rogan"],
        entities_discussed=["Rick Strassman", "MAPS"],
        detailed_summary=detailed,
    )


def test_overview_section_is_first_and_folds_thesis_format_speakers():
    sections = compose_youtube_detailed(_payload())
    assert sections[0].heading == "Overview"
    assert sections[0].sub_sections, "Overview must carry sub_sections"
    assert "Format and speakers" in sections[0].sub_sections
    assert "Core argument" in sections[0].sub_sections
    fmt_lines = " ".join(sections[0].sub_sections["Format and speakers"])
    assert "lecture" in fmt_lines.lower()
    assert "Joe Rogan" in fmt_lines


def test_chapter_walkthrough_section_emits_nested_timestamp_headings():
    sections = compose_youtube_detailed(_payload())
    walkthrough = [s for s in sections if s.heading == "Chapter walkthrough"]
    assert walkthrough, "must have a Chapter walkthrough section"
    subs = walkthrough[0].sub_sections
    assert any("Introduction and Pharmacology" in h for h in subs)
    assert any(h.startswith("00:15") for h in subs)


def test_chapter_bullets_are_strings_not_json():
    sections = compose_youtube_detailed(_payload())
    for section in sections:
        for bullet in section.bullets:
            assert isinstance(bullet, str)
            assert not bullet.lstrip().startswith("{")
        for _, bullets in section.sub_sections.items():
            for bullet in bullets:
                assert isinstance(bullet, str)
                assert not bullet.lstrip().startswith("{")


def test_closing_section_renamed_to_closing_remarks():
    sections = compose_youtube_detailed(_payload())
    headings = [s.heading for s in sections]
    assert "Closing remarks" in headings
    assert "Closing Takeaway" not in headings


def test_closing_remarks_absent_when_payload_has_no_takeaway():
    sections = compose_youtube_detailed(_payload(closing_takeaway=""))
    headings = [s.heading for s in sections]
    assert "Closing remarks" not in headings


def test_demonstrations_only_emitted_when_present():
    sections = compose_youtube_detailed(_payload())
    assert not any(s.heading == "Demonstrations" for s in sections)

    populated = _payload(demonstrations=["Live DMT extraction demo"])
    sections2 = compose_youtube_detailed(populated)
    assert any(s.heading == "Demonstrations" for s in sections2)


def test_timestamp_omitted_when_placeholder_or_filler():
    # Use "N/A" as placeholder timestamp. 5 bullets meet the chapter contract.
    no_ts = _payload(
        chapters_or_segments=[
            ChapterBullet(
                timestamp="N/A",
                title="Pharmacology",
                bullets=["A.", "B.", "C.", "D.", "E."],
            ),
        ]
    )
    sections = compose_youtube_detailed(no_ts)
    walkthrough = next(s for s in sections if s.heading == "Chapter walkthrough")
    assert "Pharmacology" in walkthrough.sub_sections
    assert not any(h.startswith("N/A") for h in walkthrough.sub_sections)


def test_filler_timestamp_00_00_is_dropped():
    filler = _payload(
        chapters_or_segments=[
            ChapterBullet(
                timestamp="00:00",
                title="Pharmacology",
                bullets=["A.", "B.", "C.", "D.", "E."],
            ),
        ]
    )
    sections = compose_youtube_detailed(filler)
    walkthrough = next(s for s in sections if s.heading == "Chapter walkthrough")
    assert not any(h.startswith("00:00") for h in walkthrough.sub_sections)
