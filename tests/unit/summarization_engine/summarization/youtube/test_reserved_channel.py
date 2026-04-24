"""Tests for the YouTube cross-source reserved-tag plumbing.

The schema-layer ``model_validator`` cannot see ``ingest.metadata`` (the
channel name lives there, not in the payload), so the YouTube summarizer
re-normalizes the already-cleaned tags with ``reserved=`` to guarantee
``yt-<channel-slug>`` survives truncation. These tests cover the helper
in isolation plus the end-to-end behaviour through the summarizer's tag
pipeline.
"""
from __future__ import annotations

from typing import Any

import pytest

from website.features.summarization_engine.summarization.common.structured import (
    _normalize_tags,
)
from website.features.summarization_engine.summarization.youtube.summarizer import (
    _slugify_channel,
    _yt_reserved,
)


# ---------------------------------------------------------------------------
# _yt_reserved happy path + slug edge cases
# ---------------------------------------------------------------------------


def test_yt_reserved_happy_path_channel_and_format() -> None:
    payload: dict[str, Any] = {"detailed_summary": {"format": "explainer"}}
    ingest_metadata = {"channel": "Two Minute Papers"}
    assert _yt_reserved(payload=payload, ingest_metadata=ingest_metadata) == [
        "yt-two-minute-papers",
        "explainer",
    ]


def test_yt_reserved_trailing_whitespace_and_caps() -> None:
    payload: dict[str, Any] = {"detailed_summary": {"format": "Tutorial"}}
    ingest_metadata = {"channel": "  TWO MINUTE PAPERS  "}
    assert _yt_reserved(payload=payload, ingest_metadata=ingest_metadata) == [
        "yt-two-minute-papers",
        "tutorial",
    ]


def test_yt_reserved_special_characters_collapse_dashes() -> None:
    payload: dict[str, Any] = {"detailed_summary": {"format": "review"}}
    ingest_metadata = {"channel": "The Verge!"}
    assert _yt_reserved(payload=payload, ingest_metadata=ingest_metadata) == [
        "yt-the-verge",
        "review",
    ]


def test_yt_reserved_non_ascii_only_channel_drops_slug() -> None:
    """Non-ASCII channel names that collapse to empty after slugify are
    dropped from reserved; format alone survives so the cross-source
    contract still pins the format label."""
    payload: dict[str, Any] = {"detailed_summary": {"format": "lecture"}}
    ingest_metadata = {"channel": "日本語チャンネル"}
    assert _yt_reserved(payload=payload, ingest_metadata=ingest_metadata) == ["lecture"]


def test_yt_reserved_no_channel_no_format_returns_empty() -> None:
    """Backward compatibility: legacy callers (no channel metadata, no
    payload) get ``[]`` so the call is byte-identical to today's
    behavior."""
    assert _yt_reserved(payload=None, ingest_metadata=None) == []
    assert _yt_reserved(payload={}, ingest_metadata={}) == []


def test_yt_reserved_uses_alternate_metadata_keys() -> None:
    payload: dict[str, Any] = {"detailed_summary": {"format": "interview"}}
    ingest_metadata = {"uploader": "Lex Fridman"}
    assert _yt_reserved(payload=payload, ingest_metadata=ingest_metadata) == [
        "yt-lex-fridman",
        "interview",
    ]


def test_yt_reserved_format_only_when_channel_missing() -> None:
    payload: dict[str, Any] = {"detailed_summary": {"format": "vlog"}}
    assert _yt_reserved(payload=payload, ingest_metadata={}) == ["vlog"]


def test_yt_reserved_channel_only_when_format_missing() -> None:
    ingest_metadata = {"channel": "Veritasium"}
    assert _yt_reserved(payload=None, ingest_metadata=ingest_metadata) == ["yt-veritasium"]


# ---------------------------------------------------------------------------
# _slugify_channel direct edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Two Minute Papers", "two-minute-papers"),
        ("The Verge!", "the-verge"),
        ("  TWO MINUTE PAPERS  ", "two-minute-papers"),
        ("---weird---name---", "weird-name"),
        ("3Blue1Brown", "3blue1brown"),
        ("a   b", "a-b"),
        ("", ""),
        ("日本語チャンネル", ""),
        ("@@@@", ""),
    ],
)
def test_slugify_channel_rules(raw: str, expected: str) -> None:
    assert _slugify_channel(raw) == expected


# ---------------------------------------------------------------------------
# End-to-end: feed the reserved set through _normalize_tags and confirm the
# yt-<slug> survives even when topical tags push past the cap.
# ---------------------------------------------------------------------------


def test_yt_channel_slug_survives_truncation_when_topical_tags_exceed_cap() -> None:
    payload: dict[str, Any] = {"detailed_summary": {"format": "explainer"}}
    ingest_metadata = {"channel": "Two Minute Papers"}
    reserved = _yt_reserved(payload=payload, ingest_metadata=ingest_metadata)

    # 10 topical tags already at the cap; without reserved plumbing the
    # channel slug would never appear because the LLM-emitted topical set
    # already fills tags_max.
    topical = [
        "neural-networks",
        "transformers",
        "attention",
        "language-models",
        "diffusion",
        "rendering",
        "raytracing",
        "physics-simulation",
        "research-paper",
        "explainer",
    ]
    final = _normalize_tags(topical, tags_min=7, tags_max=10, reserved=reserved)

    assert "yt-two-minute-papers" in final
    assert "explainer" in final
    assert len(final) == 10
    # Reserved is placed first.
    assert final[0] == "yt-two-minute-papers"
    assert final[1] == "explainer"


def test_yt_channel_slug_no_duplication_when_already_in_topical() -> None:
    payload: dict[str, Any] = {"detailed_summary": {"format": "review"}}
    ingest_metadata = {"channel": "MKBHD"}
    reserved = _yt_reserved(payload=payload, ingest_metadata=ingest_metadata)
    topical = [
        "yt-mkbhd",  # LLM happened to emit the slug too
        "review",
        "iphone",
        "android",
        "smartphones",
        "tech-review",
        "gadgets",
    ]
    final = _normalize_tags(topical, tags_min=7, tags_max=10, reserved=reserved)
    assert final.count("yt-mkbhd") == 1
    assert final.count("review") == 1
    assert final[0] == "yt-mkbhd"
    assert final[1] == "review"


def test_yt_no_reserved_keeps_legacy_behavior() -> None:
    """When ``_yt_reserved`` returns ``[]`` (no channel, no format), the
    summarizer skips the re-normalization entirely. Confirm the helper
    yields the empty list so the production guard ``if reserved:`` holds."""
    assert _yt_reserved(payload=None, ingest_metadata=None) == []
    # And _normalize_tags with reserved=[] is byte-identical to a call
    # without ``reserved=`` (cleaning + dedup + cap only).
    topical = ["python", "fastapi", "async", "pydantic", "typing", "uvicorn", "starlette"]
    no_reserved = _normalize_tags(topical, tags_min=7, tags_max=10)
    empty_reserved = _normalize_tags(topical, tags_min=7, tags_max=10, reserved=[])
    assert no_reserved == empty_reserved
