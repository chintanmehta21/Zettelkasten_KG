"""Unit tests for ``website.core.summary_normalizer``.

Covers production-observed bugs:
  * YouTube/GitHub canonical-list rows where Overview has both a top-level
    thesis bullet AND a "Core argument" sub-section that duplicates it.
  * GitHub Overview parent containing an "Overview" sub-section
    (case-insensitive match against parent heading).
Plus a regression guard on newsletter-shaped detailed_summary so legitimate
non-duplicate sub-sections are preserved.
"""
from __future__ import annotations

import json

import pytest

from website.core.summary_normalizer import normalize_summary_for_wire


def _detailed(envelope_json: str) -> list[dict]:
    return json.loads(envelope_json)["detailed_summary"]


def _section(detailed: list[dict], heading: str) -> dict | None:
    for s in detailed:
        if s.get("heading") == heading:
            return s
    return None


def test_youtube_overview_drops_duplicate_core_argument_sub():
    """Overview top-level bullet matches the Core argument sub → sub dropped."""
    thesis = (
        "The market for zero-day vulnerabilities is a complex, covert "
        "ecosystem operating across blurred boundaries."
    )
    raw = {
        "brief_summary": "Short brief.",
        "detailed_summary": [
            {
                "heading": "Overview",
                "bullets": [thesis],
                "sub_sections": {
                    "Format and speakers": ["Format: commentary. Speakers: Mac OS X."],
                    "Core argument": [thesis],
                },
            }
        ],
    }
    detailed = _detailed(normalize_summary_for_wire(raw, "youtube"))
    overview = _section(detailed, "Overview")
    assert overview is not None
    assert overview["bullets"] == [thesis]
    assert "Core argument" not in overview["sub_sections"]
    # Non-duplicate sub stays.
    assert "Format and speakers" in overview["sub_sections"]


def test_github_overview_drops_self_named_sub():
    """An "Overview" sub-section nested inside the Overview parent is dropped."""
    raw = {
        "detailed_summary": [
            {
                "heading": "Overview",
                "bullets": ["Pydantic is a data validation library for Python."],
                "sub_sections": {
                    "Architecture": ["Modules and types"],
                    "Overview": ["Repeated overview blurb"],
                    "Stack": ["Python 3.10+"],
                },
            }
        ],
    }
    detailed = _detailed(normalize_summary_for_wire(raw, "github"))
    overview = _section(detailed, "Overview")
    assert overview is not None
    keys = set(overview["sub_sections"].keys())
    assert "Overview" not in keys
    assert "Architecture" in keys
    assert "Stack" in keys


def test_github_overview_drops_core_argument_substring_match():
    """Substring-containment match between top bullet and sub bullet → drop."""
    top = (
        "Pydantic is a data validation library for Python 3.10+ that leverages "
        "type hints to enforce schema constraints at runtime."
    )
    sub = "Pydantic is a data validation library for Python 3.10+ that leverages type hints."
    raw = {
        "detailed_summary": [
            {
                "heading": "Overview",
                "bullets": [top],
                "sub_sections": {"Core argument": [sub]},
            }
        ],
    }
    detailed = _detailed(normalize_summary_for_wire(raw, "github"))
    overview = _section(detailed, "Overview")
    assert overview is not None
    assert "Core argument" not in overview["sub_sections"]


def test_newsletter_non_duplicate_subs_preserved():
    """Regression guard: legitimate non-overlapping sub-sections survive."""
    raw = {
        "detailed_summary": [
            {
                "heading": "Overview",
                "bullets": ["Issue covers the post-mortem of an outage."],
                "sub_sections": {
                    "Publication": ["Stratechery"],
                    "Format and speakers": ["Long-form essay by Ben Thompson."],
                },
            },
            {
                "heading": "Section: Root cause",
                "bullets": ["A misconfigured load balancer caused cascading failures."],
                "sub_sections": {},
            },
        ],
    }
    detailed = _detailed(normalize_summary_for_wire(raw, "newsletter"))
    overview = _section(detailed, "Overview")
    assert overview is not None
    assert overview["bullets"] == ["Issue covers the post-mortem of an outage."]
    # Both subs survive — neither duplicates the top bullet.
    assert "Publication" in overview["sub_sections"]
    assert "Format and speakers" in overview["sub_sections"]


def test_youtube_lead_in_thesis_dedupes_against_core_argument_sub():
    """Top bullet "In this lecture, X argues that <thesis>" vs sub
    "<Thesis>" — lead-in stripped, then containment dedupe fires."""
    top = (
        "In this lecture, Andrej Karpathy argues that large language models "
        "are fundamentally next-token predictors built on the transformer "
        "architecture."
    )
    sub = (
        "Large Language Models are fundamentally next-token predictors built "
        "on the Transformer architecture."
    )
    raw = {
        "detailed_summary": [
            {
                "heading": "Overview",
                "bullets": [top],
                "sub_sections": {
                    "Format and speakers": ["Format: lecture. Speakers: Andrej Karpathy."],
                    "Core argument": [sub],
                },
            }
        ],
    }
    detailed = _detailed(normalize_summary_for_wire(raw, "youtube"))
    overview = _section(detailed, "Overview")
    assert overview is not None
    # Lead-in stripped from the rendered bullet so it doesn't repeat
    # Format-and-speakers metadata.
    assert overview["bullets"][0].lower().startswith("large language models")
    # Core argument sub dropped as a semantic duplicate.
    assert "Core argument" not in overview["sub_sections"]
    assert "Format and speakers" in overview["sub_sections"]


def test_overview_sub_dropped_under_non_overview_parent():
    """An "Overview" sub nested under e.g. "Features and modules" is dropped
    everywhere, not just under the Overview parent."""
    raw = {
        "detailed_summary": [
            {
                "heading": "Overview",
                "bullets": ["Pydantic top-level summary."],
                "sub_sections": {},
            },
            {
                "heading": "Features and modules",
                "bullets": [],
                "sub_sections": {
                    "Architecture": ["modules + types"],
                    "Overview": ["should never appear here"],
                    "Modules": ["pydantic.v1, pydantic.dataclasses"],
                },
            },
        ],
    }
    detailed = _detailed(normalize_summary_for_wire(raw, "github"))
    feats = _section(detailed, "Features and modules")
    assert feats is not None
    keys = set(feats["sub_sections"].keys())
    assert "Overview" not in keys
    assert "Architecture" in keys
    assert "Modules" in keys


def test_chapter_bullets_python_repr_expanded():
    """Single-quoted dict bullets parse via ast.literal_eval and expand."""
    raw = {
        "detailed_summary": [
            {
                "heading": "Chapter walkthrough",
                "bullets": [
                    "{'timestamp': 'N/A', 'title': 'Connecting the dots', "
                    "'bullets': ['Jobs reflects on calligraphy.', 'Macintosh born.']}",
                    "{'timestamp': 'N/A', 'title': 'Love and loss', "
                    "'bullets': ['Fired from Apple at 30.', 'Founded NeXT.']}",
                ],
                "sub_sections": {},
            }
        ],
    }
    detailed = _detailed(normalize_summary_for_wire(raw, "youtube"))
    chap = _section(detailed, "Chapter walkthrough")
    assert chap is not None
    assert chap["bullets"] == []  # raw blobs consumed
    assert "Connecting the dots" in chap["sub_sections"]
    assert "Love and loss" in chap["sub_sections"]
    assert chap["sub_sections"]["Connecting the dots"][0].startswith("Jobs")


def test_chapter_bullets_list_of_dicts_in_one_string():
    """Single bullet whose value is a JSON list of chapter dicts expands."""
    raw = {
        "detailed_summary": [
            {
                "heading": "Chapter walkthrough",
                "bullets": [
                    '[{"timestamp": "N/A", "title": "Intro", "bullets": ["Greeting."]},'
                    ' {"timestamp": "N/A", "title": "Body", "bullets": ["Argument."]}]'
                ],
                "sub_sections": {},
            }
        ],
    }
    detailed = _detailed(normalize_summary_for_wire(raw, "youtube"))
    chap = _section(detailed, "Chapter walkthrough")
    assert chap is not None
    assert "Intro" in chap["sub_sections"]
    assert "Body" in chap["sub_sections"]


def test_speakers_user_agent_filtered_in_format_and_speakers():
    """``Speakers: Mac OS X.`` → ``Speakers: not identified``."""
    raw = {
        "detailed_summary": [
            {
                "heading": "Overview",
                "bullets": ["The market for zero-day vulnerabilities is covert."],
                "sub_sections": {
                    "Format and speakers": ["Format: commentary. Speakers: Mac OS X."],
                },
            }
        ],
    }
    detailed = _detailed(normalize_summary_for_wire(raw, "youtube"))
    fmt = _section(detailed, "Overview")["sub_sections"]["Format and speakers"][0]
    assert "Mac OS X" not in fmt
    assert "not identified" in fmt.lower()


def test_speakers_partial_filter_keeps_human_names():
    raw = {
        "detailed_summary": [
            {
                "heading": "Overview",
                "bullets": ["Top bullet."],
                "sub_sections": {
                    "Format and speakers": [
                        "Format: lecture. Speakers: Andrej Karpathy, Mac OS X."
                    ],
                },
            }
        ],
    }
    detailed = _detailed(normalize_summary_for_wire(raw, "youtube"))
    fmt = _section(detailed, "Overview")["sub_sections"]["Format and speakers"][0]
    assert "Andrej Karpathy" in fmt
    assert "Mac OS X" not in fmt


def test_brief_drops_trailing_incomplete_sentence():
    """Brief ending in ``... requiring trust in.`` has the trailing fragment
    stripped, but earlier complete sentences are preserved."""
    brief = (
        "This lecture explains the speech's central themes. "
        "One cannot plan a life path forward but can only connect the dots "
        "looking backward, requiring trust in."
    )
    raw = {"brief_summary": brief, "detailed_summary": []}
    out = json.loads(normalize_summary_for_wire(raw, "youtube"))
    assert "trust in." not in out["brief_summary"]
    assert "central themes" in out["brief_summary"]


def test_brief_drops_company_from_key_voices():
    brief = (
        "The speech is a 2005 Stanford commencement address. "
        "Key voices and figures include Steve Jobs and Apple. "
        "The address is widely cited."
    )
    raw = {"brief_summary": brief, "detailed_summary": []}
    out = json.loads(normalize_summary_for_wire(raw, "youtube"))
    assert "Apple" not in out["brief_summary"]
    assert "Steve Jobs" in out["brief_summary"]
    assert "widely cited" in out["brief_summary"]


def test_chapter_like_flat_h2s_wrapped_under_walkthrough():
    """>5 short flat h2s with no Chapter walkthrough → wrapped."""
    sections = [{"heading": "Overview", "bullets": ["Top."], "sub_sections": {}}]
    chapter_titles = [
        "Eye contact basics", "Vocal projection", "Pacing and pauses",
        "Body language", "Handling questions", "Opening hooks",
        "Closing strong",
    ]
    for t in chapter_titles:
        sections.append({"heading": t, "bullets": [f"Tip about {t}."], "sub_sections": {}})
    raw = {"detailed_summary": sections}
    detailed = _detailed(normalize_summary_for_wire(raw, "youtube"))
    walkthrough = _section(detailed, "Chapter walkthrough")
    assert walkthrough is not None
    keys = set(walkthrough["sub_sections"].keys())
    for t in chapter_titles:
        assert t in keys
    # The flat h2s should no longer appear as top-level sections.
    headings = {s["heading"] for s in detailed}
    assert "Eye contact basics" not in headings


def test_closing_takeaway_heading_remapped_to_closing_remarks():
    """Raw 'Closing Takeaway' / 'closing_takeaway' heading → 'Closing remarks'."""
    raw = {
        "detailed_summary": [
            {"heading": "Overview", "bullets": ["x"], "sub_sections": {}},
            {"heading": "closing_takeaway", "bullets": ["Recap: y."], "sub_sections": {}},
        ],
    }
    detailed = _detailed(normalize_summary_for_wire(raw, "youtube"))
    headings = [s["heading"] for s in detailed]
    assert "Closing remarks" in headings
    assert "closing_takeaway" not in headings


def test_na_timestamp_stripped_from_chapter_titles():
    raw = {
        "detailed_summary": [
            {
                "heading": "Chapter walkthrough",
                "bullets": [],
                "sub_sections": {"N/A — Connecting the dots": ["b1"]},
            }
        ],
    }
    detailed = _detailed(normalize_summary_for_wire(raw, "youtube"))
    chap = _section(detailed, "Chapter walkthrough")
    assert chap is not None
    keys = list(chap["sub_sections"].keys())
    assert any("Connecting the dots" == k for k in keys)
    assert all("N/A" not in k for k in keys)


def test_idempotent_on_already_clean_envelope():
    """Running the normalizer twice produces the same envelope."""
    raw = {
        "mini_title": "Zero-day market",
        "brief_summary": "Brief.",
        "detailed_summary": [
            {
                "heading": "Overview",
                "bullets": ["The market for zero-day vulnerabilities is covert."],
                "sub_sections": {"Format and speakers": ["Commentary"]},
            }
        ],
        "closing_remarks": "",
    }
    once = normalize_summary_for_wire(raw, "youtube")
    twice = normalize_summary_for_wire(json.loads(once), "youtube")
    assert json.loads(once) == json.loads(twice)
