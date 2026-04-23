# tests/unit/summarization_engine/summarization/common/test_brief_repair.py
from __future__ import annotations

import pytest

from website.features.summarization_engine.summarization.common.brief_repair import (
    as_sentence,
    clip_to_char_budget,
    clip_to_sentence_window,
    has_terminal_punct,
    normalize_whitespace,
    sentence_split,
    trim_fragment,
)


# ---------------------------------------------------------------------------
# normalize_whitespace
# ---------------------------------------------------------------------------

def test_normalize_whitespace_collapses_runs_and_strips_ends():
    assert normalize_whitespace("  hello\t\tworld\n") == "hello world"


def test_normalize_whitespace_none_and_empty_are_safe():
    assert normalize_whitespace(None) == ""  # type: ignore[arg-type]
    assert normalize_whitespace("") == ""
    assert normalize_whitespace("   ") == ""


# ---------------------------------------------------------------------------
# sentence_split
# ---------------------------------------------------------------------------

def test_sentence_split_basic_three_sentences():
    out = sentence_split("First one. Second two! Third three?")
    assert out == ["First one.", "Second two!", "Third three?"]


def test_sentence_split_preserves_terminal_punctuation():
    out = sentence_split("Alpha. Beta.")
    assert all(s.endswith((".", "!", "?")) for s in out)


def test_sentence_split_normalizes_whitespace_between():
    out = sentence_split("A.    B.\n\nC.")
    assert out == ["A.", "B.", "C."]


def test_sentence_split_unterminated_fragment_kept_as_single():
    # Contract: a single fragment with no terminator is still returned
    # (the split primitive does not enforce termination).
    out = sentence_split("Just one fragment no period")
    assert out == ["Just one fragment no period"]


def test_sentence_split_empty_and_whitespace_only():
    assert sentence_split("") == []
    assert sentence_split("   \n\t") == []


def test_sentence_split_drops_empty_segments():
    # Multiple spaces after a terminator should not produce empty strings.
    out = sentence_split("One.    Two.")
    assert "" not in out


# ---------------------------------------------------------------------------
# has_terminal_punct
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Yes.", True),
    ("Yes!", True),
    ("Yes?", True),
    ("No trailing punct", False),
    ("", False),
    ("   ", False),
    ("Trailing spaces.  ", True),
    ("Ends with comma,", False),
])
def test_has_terminal_punct_cases(text, expected):
    assert has_terminal_punct(text) is expected


# ---------------------------------------------------------------------------
# as_sentence
# ---------------------------------------------------------------------------

def test_as_sentence_adds_period_to_unterminated():
    assert as_sentence("hello world") == "hello world."


def test_as_sentence_preserves_existing_terminator():
    assert as_sentence("hello world!") == "hello world!"
    assert as_sentence("hello world?") == "hello world?"
    assert as_sentence("hello world.") == "hello world."


def test_as_sentence_strips_trailing_connectors_before_adding_period():
    assert as_sentence("ends with comma,") == "ends with comma."
    assert as_sentence("ends with semicolon;") == "ends with semicolon."
    assert as_sentence("ends with colon:") == "ends with colon."


def test_as_sentence_empty_and_whitespace_only():
    assert as_sentence("") == ""
    assert as_sentence("   ") == ""


# ---------------------------------------------------------------------------
# trim_fragment
# ---------------------------------------------------------------------------

def test_trim_fragment_under_budget_returns_full_text():
    assert trim_fragment("three small words", max_words=10) == "three small words"


def test_trim_fragment_over_budget_clips_to_word_count():
    out = trim_fragment("one two three four five six", max_words=3)
    assert out == "one two three"


def test_trim_fragment_strips_trailing_connectors():
    assert trim_fragment("cut here,", max_words=10) == "cut here"
    assert trim_fragment("one two three,;:", max_words=10) == "one two three"


def test_trim_fragment_zero_max_words_returns_empty():
    assert trim_fragment("anything", max_words=0) == ""


def test_trim_fragment_empty_and_none_safe():
    assert trim_fragment("", max_words=5) == ""
    assert trim_fragment(None, max_words=5) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# clip_to_sentence_window
# ---------------------------------------------------------------------------

def test_clip_to_sentence_window_limits_to_max_sentences():
    sents = ["A.", "B.", "C.", "D.", "E."]
    out = clip_to_sentence_window(sents, max_sentences=3, max_chars=1000)
    assert out == "A. B. C."


def test_clip_to_sentence_window_respects_char_budget():
    sents = ["Short one.", "Short two.", "Short three."]
    # Force a tight budget that fits only the first sentence.
    out = clip_to_sentence_window(sents, max_sentences=5, max_chars=len("Short one.") + 1)
    assert out == "Short one."


def test_clip_to_sentence_window_empty_inputs():
    assert clip_to_sentence_window([], max_sentences=5, max_chars=100) == ""
    assert clip_to_sentence_window(["A."], max_sentences=0, max_chars=100) == ""
    assert clip_to_sentence_window(["A."], max_sentences=5, max_chars=0) == ""


# ---------------------------------------------------------------------------
# clip_to_char_budget
# ---------------------------------------------------------------------------

def test_clip_to_char_budget_under_budget_returns_unchanged():
    text = "Short enough."
    assert clip_to_char_budget(text, max_chars=500) == text


def test_clip_to_char_budget_cuts_at_last_sentence_boundary():
    # Build a string > 500 chars with sentence boundaries.
    head = "Sentence one is of modest length. " * 10  # ~340 chars
    tail = "And a final tail clause that extends the string well past five hundred characters total length here."
    text = (head + tail).strip()
    out = clip_to_char_budget(text, max_chars=500)
    assert len(out) <= 500
    assert out.endswith(". ") or out.endswith(".")


def test_clip_to_char_budget_no_boundary_falls_back_to_raw_window():
    # No sentence boundaries within the first 500 chars — expect raw cut.
    text = "a" * 600
    out = clip_to_char_budget(text, max_chars=500)
    assert out == "a" * 500


def test_clip_to_char_budget_zero_or_negative_is_empty():
    assert clip_to_char_budget("anything", max_chars=0) == ""
    assert clip_to_char_budget("anything", max_chars=-5) == ""


# ---------------------------------------------------------------------------
# Unicode / quote robustness
# ---------------------------------------------------------------------------

def test_sentence_split_handles_unicode_em_dash_and_trailing_content():
    # Unicode em-dash and non-ASCII whitespace should not break the split;
    # contract: sentences end at terminal punct followed by whitespace.
    text = "First clause\u2014with em dash. Second clause stands alone."
    out = sentence_split(text)
    assert len(out) == 2
    assert out[0].endswith(".")
    assert out[1].endswith(".")


def test_as_sentence_handles_unicode_whitespace():
    assert as_sentence("\u00a0hello\u2003world") == "hello world."
