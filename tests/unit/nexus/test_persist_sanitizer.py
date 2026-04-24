"""Unit tests for the nexus persist-layer sanitizer.

Locks three guarantees:
  1. Sentinel tokens (``[RESERVED]``, ``<SENTINEL:foo>``, ``_schema_fallback_``)
     never survive ``_normalize_summary_text``.
  2. A trailing unterminated sentence fragment on a multi-line body is
     dropped so persisted summaries always end on a terminated sentence or a
     structural marker (heading, list item).
  3. Well-formed inputs (terminated sentences, headings, list items) pass
     through without mutation.
"""
from __future__ import annotations

from website.experimental_features.nexus.service.persist import (
    _drop_unterminated_tail,
    _normalize_summary_text,
    _strip_sentinel_text,
)


def test_strip_sentinel_text_removes_bracketed_reserved():
    assert (
        _strip_sentinel_text("Body line [RESERVED] more text.")
        == "Body line more text."
    )


def test_strip_sentinel_text_removes_angle_sentinel():
    assert (
        _strip_sentinel_text("Body <SENTINEL:foo> end.") == "Body end."
    )


def test_strip_sentinel_text_removes_schema_fallback():
    assert (
        _strip_sentinel_text("See _schema_fallback_ note.") == "See note."
    )


def test_strip_sentinel_text_preserves_newlines():
    text = "Line 1.\n_schema_fallback_\nLine 3."
    out = _strip_sentinel_text(text)
    assert "\n" in out
    assert "schema_fallback" not in out


def test_drop_unterminated_tail_removes_dangling_fragment():
    text = "First sentence done.\nSecond sentence also done.\nThird frag without"
    out = _drop_unterminated_tail(text)
    assert out.endswith("done.")
    assert "Third frag" not in out


def test_drop_unterminated_tail_keeps_markdown_heading_tail():
    text = "Paragraph.\n## A heading"
    out = _drop_unterminated_tail(text)
    assert out.endswith("A heading")


def test_drop_unterminated_tail_keeps_list_marker_tail():
    text = "Intro.\n- bullet item"
    out = _drop_unterminated_tail(text)
    assert out.endswith("bullet item")


def test_drop_unterminated_tail_preserves_terminated_body():
    text = "All good.\nStill good.\nAlso good."
    assert _drop_unterminated_tail(text) == text


def test_normalize_summary_text_applies_all_steps():
    raw = (
        "Opening sentence.\n"
        "[RESERVED] middle bit with _sentinel_ token.\n"
        "Truncated frag without terminator"
    )
    out = _normalize_summary_text(raw)
    assert "RESERVED" not in out
    assert "sentinel" not in out.lower() or "_sentinel_" not in out
    assert "Truncated frag" not in out
    assert out.endswith(".")


def test_normalize_summary_text_handles_none():
    assert _normalize_summary_text(None) == ""


def test_normalize_summary_text_single_line_passes_through():
    # Single-line inputs don't get their tail dropped (caller enforces).
    assert _normalize_summary_text("Just one line") == "Just one line"
