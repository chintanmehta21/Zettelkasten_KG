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


# ---------------------------------------------------------------------------
# 2026-04-25 audit fixes — tests use broken-data strings observed live in
# Supabase prior to the fix landing.
# ---------------------------------------------------------------------------


def test_brief_strips_mac_os_x_from_inline_list():
    """Card 0 (Zero-Day) brief had a UA leak: ``"references Windows 10,
    Mac OS X, and Bugtraq."`` The list-aware scrubber drops Mac OS X while
    preserving Windows 10 and Bugtraq AND the leading ``"references"`` verb.
    """
    raw = {
        "brief_summary": (
            "In this commentary, the speaker argues that the market for "
            "zero-day vulnerabilities is covert. Along the way the speaker "
            "references Windows 10, Mac OS X, and Bugtraq."
        ),
        "detailed_summary": [],
    }
    env = json.loads(normalize_summary_for_wire(raw, "youtube"))
    brief = env["brief_summary"]
    assert "Mac OS X" not in brief
    assert "Windows 10" in brief
    assert "Bugtraq" in brief
    # Lead-in clause and verb survive intact.
    assert "references Windows 10 and Bugtraq" in brief


def test_lead_in_strip_recapitalizes_first_letter():
    """``"In this commentary, the speaker argues that the market..."`` ->
    ``"The market..."`` with re-capitalized first letter (not "the market.").
    """
    raw = {
        "detailed_summary": [
            {
                "heading": "Overview",
                "bullets": [
                    "In this commentary, the speaker argues that the market "
                    "for zero-day vulnerabilities is covert."
                ],
                "sub_sections": {},
            }
        ],
    }
    detailed = _detailed(normalize_summary_for_wire(raw, "youtube"))
    overview = _section(detailed, "Overview")
    assert overview is not None
    assert overview["bullets"], "lead-in strip must not zero out the bullet"
    first = overview["bullets"][0]
    assert first[0] == "T", f"expected 'T' (recapitalized), got {first[:30]!r}"
    assert first.startswith("The market")


def test_chapter_dicts_in_subsections_are_unwrapped():
    """Card 10/11 stored chapter walkthroughs as JSON-string bullets nested
    inside ``sub_sections["Chapter walkthrough"]`` — the renderer leaked the
    raw JSON. The expander must traverse sub_sections too."""
    raw = {
        "detailed_summary": [
            {
                "heading": "Overview",
                "bullets": ["Steve Jobs delivered a 2005 Stanford address."],
                "sub_sections": {
                    "Chapter walkthrough": [
                        '{"timestamp": "N/A", "title": "Connecting the Dots", '
                        '"bullets": ["Jobs reflects on calligraphy."]}',
                        '{"timestamp": "N/A", "title": "Love and Loss", '
                        '"bullets": ["Jobs talks about being fired."]}',
                    ],
                },
            }
        ],
    }
    detailed = _detailed(normalize_summary_for_wire(raw, "youtube"))
    overview = _section(detailed, "Overview")
    assert overview is not None
    keys = list(overview["sub_sections"].keys())
    # The wrapper key is dropped; chapter titles surface as peer subs.
    assert "Connecting the Dots" in keys
    assert "Love and Loss" in keys
    # No JSON blob survives in any bullet.
    for v in overview["sub_sections"].values():
        for b in v:
            assert not b.lstrip().startswith("{"), f"raw JSON leaked: {b!r}"


def test_chapter_dicts_with_unescaped_quotes_regex_fallback():
    """When chapter bullets contain unescaped quotes (``print("hello")``)
    JSON.parse + ast.literal_eval both fail. The regex fallback extracts
    title + bullets directly."""
    bullet = (
        '{"timestamp": "N/A", "title": "Code Demo", '
        '"bullets": ["The instructor types print("hello world") on screen."]}'
    )
    raw = {
        "detailed_summary": [
            {
                "heading": "Chapter walkthrough",
                "bullets": [bullet],
                "sub_sections": {},
            }
        ],
    }
    detailed = _detailed(normalize_summary_for_wire(raw, "youtube"))
    chap = _section(detailed, "Chapter walkthrough")
    assert chap is not None
    keys = list(chap["sub_sections"].keys())
    assert "Code Demo" in keys
    # The original raw JSON blob must NOT survive verbatim in any rendered
    # bullet — partial recovery (title-only, body mangled by the unescaped
    # nested quotes) is acceptable; leaking the literal "{"timestamp"..."
    # is not.
    assert chap["bullets"] == [], (
        f"raw JSON bullet leaked through expander: {chap['bullets']!r}"
    )
    for k, v in chap["sub_sections"].items():
        for b in v:
            assert "timestamp" not in b
            assert not b.lstrip().startswith("{")


def test_youtube_lecture_dedupe_after_lead_in_strip():
    """Card 5 (Karpathy) had:
       Top: "In this lecture, Andrej Karpathy argues that LLMs are
              fundamentally next-token predictors..."
       Sub Core argument: "Large Language Models are fundamentally next-token
              predictors..."
    After stripping the lead-in from the top bullet the two collide; dedupe
    must run AFTER the strip so the sub gets dropped."""
    raw = {
        "detailed_summary": [
            {
                "heading": "Overview",
                "bullets": [
                    "In this lecture, Andrej Karpathy argues that large "
                    "language models are fundamentally next-token predictors "
                    "trained on internet text."
                ],
                "sub_sections": {
                    "Core argument": [
                        "Large Language Models are fundamentally next-token "
                        "predictors trained on internet text."
                    ],
                    "Format and speakers": ["Lecture by Andrej Karpathy."],
                },
            }
        ],
    }
    detailed = _detailed(normalize_summary_for_wire(raw, "youtube"))
    overview = _section(detailed, "Overview")
    assert overview is not None
    assert "Core argument" not in overview["sub_sections"], (
        f"Core argument sub should have been deduped, got: "
        f"{list(overview['sub_sections'].keys())}"
    )
    # Non-redundant sub stays.
    assert "Format and speakers" in overview["sub_sections"]
    # And the rendered top bullet is the lead-in-stripped, recapitalized form.
    assert overview["bullets"][0].startswith("Large language models")


def test_chapter_wrap_threshold_lowered_to_four():
    """Card 8 (Effective Public Speaking) emitted 14 chapter-style h2s. The
    earlier ``>= 6`` heuristic was correct for that card; this regression test
    asserts the threshold catches even smaller talks (4 chapter-like h2s)."""
    raw = {
        "detailed_summary": [
            {"heading": "Overview", "bullets": ["A talk on speaking."], "sub_sections": {}},
            {"heading": "Opening Hook", "bullets": ["Lead with a story."], "sub_sections": {}},
            {"heading": "Body Structure", "bullets": ["Three points."], "sub_sections": {}},
            {"heading": "Vocal Variety", "bullets": ["Pace and tone."], "sub_sections": {}},
            {"heading": "Closing the Loop", "bullets": ["Tie back to opening."], "sub_sections": {}},
        ],
    }
    detailed = _detailed(normalize_summary_for_wire(raw, "youtube"))
    headings = [s.get("heading") for s in detailed]
    # Overview survives at the top.
    assert headings[0] == "Overview"
    # All chapter-like h2s now nested under Chapter walkthrough.
    assert "Chapter walkthrough" in headings
    chap = _section(detailed, "Chapter walkthrough")
    assert chap is not None
    sub_keys = list(chap["sub_sections"].keys())
    assert "Opening Hook" in sub_keys
    assert "Closing the Loop" in sub_keys
    # The flat h2s are gone from top level.
    assert "Opening Hook" not in headings
    assert "Closing the Loop" not in headings


def test_legitimate_os_mention_in_chapter_body_is_preserved():
    """``"complex operating systems like Windows 10 and Mac OS X"`` is
    legitimate substantive content (the speaker is discussing OSes), not a
    UA leak. The brief scrubber must NOT touch detailed-section bullets."""
    chapter_body = (
        "Zero-day vulnerabilities exist in complex operating systems like "
        "Windows 10 and Mac OS X."
    )
    raw = {
        "brief_summary": "A talk on zero-days.",
        "detailed_summary": [
            {
                "heading": "Chapter walkthrough",
                "bullets": [],
                "sub_sections": {"Introduction": [chapter_body]},
            }
        ],
    }
    detailed = _detailed(normalize_summary_for_wire(raw, "youtube"))
    chap = _section(detailed, "Chapter walkthrough")
    assert chap is not None
    body = " ".join(chap["sub_sections"]["Introduction"])
    assert "Mac OS X" in body
    assert "Windows 10" in body
