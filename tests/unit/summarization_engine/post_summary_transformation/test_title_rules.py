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


def test_youtube_title_keeps_conjunctions():
    from website.features.summarization_engine.summarization.youtube import schema as ys
    out = ys._normalize_mini_title("Silk Road's Rise and Fall of a Marketplace")
    assert "and" in out.lower().split() or "&" in out
    # 'and' is no longer treated as a droppable stopword for titles
    assert "and" not in ys._TITLE_STOPWORDS
    assert "or" not in ys._TITLE_STOPWORDS
    assert "vs" not in ys._TITLE_STOPWORDS


def test_youtube_title_no_trailing_conjunction():
    from website.features.summarization_engine.summarization.youtube import schema as ys
    # words[:5] slice lands on a trailing coordinating conjunction; B2'
    # strips it so the mini_title never ends on a dangling "and"/"or"/etc.
    out = ys._normalize_mini_title("DMT Identity History Effects and Theories")
    assert out == "DMT Identity History Effects"
    # case-insensitive + looped (multiple trailing conjunctions collapse)
    assert ys._normalize_mini_title("Cats Dogs AND OR") == "Cats Dogs"
    assert ys._normalize_mini_title("Risk versus Reward vs") == "Risk versus Reward"
    assert ys._normalize_mini_title("Crypto Boom &") == "Crypto Boom"
    # interior conjunctions are preserved (only the trailing one is stripped;
    # "of" is dropped here by the pre-existing _TITLE_STOPWORDS filter, not B2')
    assert ys._normalize_mini_title("Rise and Fall of Empires") == "Rise and Fall Empires"
    # idempotent
    once = ys._normalize_mini_title("DMT Identity History Effects and Theories")
    assert ys._normalize_mini_title(once) == once
    # conjunctions still NOT re-added to the stopword set
    assert "and" not in ys._TITLE_STOPWORDS
    assert "vs" not in ys._TITLE_STOPWORDS


def test_capitalize_first_content_word_only():
    cap = t.capitalize_title
    assert cap("r/IAmA first-time heroin risks") == "r/IAmA First-time heroin risks"
    assert cap("r/philosophy seeks philosophical perspectives") == "r/philosophy Seeks philosophical perspectives"
    assert cap("owner/repo does something") == "owner/repo Does something"
    assert cap("seeks the truth") == "Seeks the truth"
    # preserve acronyms / camelCase / brands / already-capitalized / interior
    assert cap("GitHub ships iOS arXiv tool") == "GitHub ships iOS arXiv tool"
    assert cap("FT analysis of US policy") == "FT analysis of US policy"
    assert cap("Already Good Title") == "Already Good Title"
    assert cap("") == ""
    assert cap("r/AskHistorians") == "r/AskHistorians"  # prefix only, nothing to cap
