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
