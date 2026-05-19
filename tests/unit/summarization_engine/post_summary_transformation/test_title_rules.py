from __future__ import annotations

from website.features.summarization_engine.post_summary_transformation.rules import (
    title as t,
)


def test_word_boundary_trim_no_midword_cut():
    s = "Analysis of FT Piece: Rethinking Heterodox Policies in Polycrisis economics"
    out = t.trim_to_word_boundary(s, 60)
    assert len(out) <= 60
    # never ends mid a truncated word: out is a whitespace-trimmed prefix of s
    assert s.startswith(out)
    assert out == out.rstrip()
    # the char immediately after out must be a space (word boundary) or nothing
    # (exact fit) — never an alphanumeric mid-word character
    next_char = s[len(out):len(out) + 1]
    assert next_char == "" or next_char.isspace()


def test_word_boundary_trim_keeps_short_titles_verbatim():
    assert t.trim_to_word_boundary("Short title", 60) == "Short title"


def test_word_boundary_trim_single_long_word_hard_cut_fallback():
    # pathological: one token longer than the cap -> hard slice (can't keep a
    # whole word and stay <= cap); acceptable, documented.
    assert t.trim_to_word_boundary("x" * 80, 60) == "x" * 60


def test_no_ellipsis_added():
    out = t.trim_to_word_boundary("alpha beta gamma delta " * 5, 60)
    assert "…" not in out and "..." not in out
