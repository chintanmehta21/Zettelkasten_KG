"""Regression tests for _coerce_detailed_to_markdown / _encode_summary_payload.

Guards against the iter-23 github regression where a list-of-dict
``detailed_summary`` was stringified via ``str(list)`` — producing a Python
repr with single quotes that the frontend renderer could not parse.
"""
from __future__ import annotations

import json

import pytest

from website.core.persist import (
    _coerce_detailed_to_markdown,
    _encode_summary_payload,
    _normalize_summary_text,
)


def test_coerce_list_of_dicts_produces_markdown_not_python_repr():
    detailed = [
        {
            "heading": "Overview",
            "bullets": ["Pydantic is a data validation library."],
            "sub_sections": {
                "Core argument": ["Uses type hints to define data."],
                "Stack": ["Python", "Rust"],
            },
        }
    ]
    md = _coerce_detailed_to_markdown(detailed)
    assert "## Overview" in md
    assert "- Pydantic is a data validation library." in md
    assert "### Core argument" in md
    assert "- Uses type hints to define data." in md
    # Must NOT contain Python repr artifacts
    assert "{'" not in md
    assert "'heading':" not in md


def test_coerce_empty_inputs():
    assert _coerce_detailed_to_markdown(None) == ""
    assert _coerce_detailed_to_markdown("") == ""
    assert _coerce_detailed_to_markdown([]) == ""
    assert _coerce_detailed_to_markdown({}) == ""


def test_coerce_string_passthrough():
    # Already-markdown strings should pass through unchanged.
    md = "## Overview\n- A bullet."
    assert _coerce_detailed_to_markdown(md) == md


def test_coerce_single_dict_is_treated_as_one_section():
    detailed = {
        "heading": "Solo",
        "bullets": ["Point one."],
    }
    md = _coerce_detailed_to_markdown(detailed)
    assert md.startswith("## Solo")
    assert "- Point one." in md


def test_coerce_pydantic_section_model():
    from website.features.summarization_engine.summarization.github.schema import (
        GitHubDetailedSection,
    )

    section = GitHubDetailedSection(
        heading="Overview",
        bullets=["Fact A.", "Fact B."],
        module_or_feature="Overview",
    )
    md = _coerce_detailed_to_markdown([section])
    assert "## Overview" in md
    assert "- Fact A." in md
    assert "- Fact B." in md
    assert "{'" not in md


def test_normalize_summary_text_handles_list_of_dicts():
    detailed = [
        {"heading": "Overview", "bullets": ["Core fact."], "sub_sections": {}}
    ]
    normalized = _normalize_summary_text(detailed)
    assert "## Overview" in normalized
    assert "- Core fact." in normalized
    assert "{'" not in normalized


def test_encode_summary_payload_roundtrips_structured_detailed():
    payload = {
        "brief_summary": "A concise brief.",
        "detailed_summary": [
            {
                "heading": "Overview",
                "bullets": ["Bullet one.", "Bullet two."],
                "sub_sections": {"Stack": ["Python", "Rust"]},
            }
        ],
    }
    encoded = _encode_summary_payload(payload)
    # Top level must be valid JSON (double-quoted).
    parsed = json.loads(encoded)
    assert parsed["brief_summary"] == "A concise brief."
    # Detailed is now markdown inside JSON — NOT a Python repr.
    detailed = parsed["detailed_summary"]
    assert isinstance(detailed, str)
    assert "## Overview" in detailed
    assert "- Bullet one." in detailed
    assert "### Stack" in detailed
    # Python repr artifacts MUST be absent.
    assert "{'" not in detailed
    assert "'heading'" not in detailed


def test_encode_summary_payload_json_roundtrip_no_single_quote_repr():
    """End-to-end guard: encoded summary must survive json.loads without
    exposing Python repr fragments."""
    payload = {
        "brief_summary": "Brief.",
        "detailed_summary": [
            {"heading": "A", "bullets": ["x"]},
            {"heading": "B", "bullets": ["y"]},
        ],
    }
    encoded = _encode_summary_payload(payload)
    parsed = json.loads(encoded)
    # Frontend does JSON.parse(summary) -> .detailed_summary; ensure the
    # string it gets starts with a markdown heading, not a "[{'" fragment.
    assert parsed["detailed_summary"].startswith("## A")


@pytest.mark.parametrize("source_type", ["github", "youtube", "reddit", "newsletter"])
def test_all_source_types_survive_structured_payload(source_type):
    payload = {
        "brief_summary": "Brief.",
        "detailed_summary": [
            {"heading": f"{source_type} overview", "bullets": ["Fact."], "sub_sections": {}}
        ],
    }
    encoded = _encode_summary_payload(payload)
    parsed = json.loads(encoded)
    assert f"## {source_type} overview" in parsed["detailed_summary"]
    assert "{'" not in parsed["detailed_summary"]
