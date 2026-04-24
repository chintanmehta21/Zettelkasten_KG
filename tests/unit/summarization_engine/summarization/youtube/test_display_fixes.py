"""D1/D2 display-bug regressions (iter-20 petrodollar lecture).

D1: ``_normalize_mini_title`` stripped intra-word apostrophes so
    ``Petrodollar's`` became ``Petrodollar`` + ``s`` and the stopword
    filter dropped the bare ``s``, yielding
    ``"Petrodollar s Decline US Dominance"``.

D2: naive sentence splitters broke on abbreviations like ``U.S.`` so
    the overview bullet truncated to ``"...implications for U."`` and
    the brief-repair logic saw fragments instead of full sentences.
"""
from __future__ import annotations

import json
from pathlib import Path

from website.features.summarization_engine.summarization.common.text_guards import (
    split_sentences,
)
from website.features.summarization_engine.summarization.youtube.layout import (
    _first_sentence,
)
from website.features.summarization_engine.summarization.youtube.schema import (
    _normalize_mini_title,
    _split_sentences,
)


# ---------- D1: mini_title apostrophe / hyphen preservation ----------


def test_normalize_mini_title_preserves_possessive_apostrophe():
    result = _normalize_mini_title("Petrodollar's Decline & US Dominance")
    assert "Petrodollar's" in result
    # The old bug surfaced a standalone 's' after the split; ensure that
    # never appears as its own whitespace-separated token.
    tokens = result.split()
    assert "s" not in tokens


def test_normalize_mini_title_preserves_curly_apostrophe():
    # \u2019 is the curly right single quote that Gemini often emits.
    result = _normalize_mini_title("Petrodollar\u2019s Decline & US Dominance")
    assert "Petrodollar\u2019s" in result


def test_normalize_mini_title_preserves_contractions():
    result = _normalize_mini_title("Don't Stop Believing Now")
    assert "Don't" in result


def test_normalize_mini_title_preserves_hyphenated_word():
    result = _normalize_mini_title("State-of-the-art Systems Today")
    assert "State-of-the-art" in result


def test_normalize_mini_title_drops_bare_apostrophe_token():
    # "' word" should not produce an empty token.
    result = _normalize_mini_title("' only noise apostrophe")
    assert "" not in result.split()
    # And must still produce a non-empty title.
    assert result.strip()


def test_normalize_mini_title_empty_falls_back_to_default():
    assert _normalize_mini_title("") == "YouTube Summary"
    assert _normalize_mini_title("   ") == "YouTube Summary"


# ---------- D2: abbreviation-aware sentence splitter ----------


def test_split_sentences_handles_us_abbreviation():
    sentences = split_sentences("Speaker discussed U.S. policy. Then moved on.")
    assert len(sentences) == 2
    assert "U.S." in sentences[0]
    assert sentences[1] == "Then moved on."


def test_split_sentences_handles_multiple_abbreviations():
    sentences = split_sentences(
        "Dr. Smith vs. Mr. Jones went to Inc."
    )
    # Entire phrase is one sentence — every period is inside an
    # abbreviation, nothing should split.
    assert len(sentences) == 1
    assert "Dr. Smith" in sentences[0]
    assert "Inc." in sentences[0]


def test_split_sentences_handles_decimals():
    sentences = split_sentences("Pi is 3.14 approximately. The next fact.")
    assert len(sentences) == 2
    assert "3.14" in sentences[0]


def test_split_sentences_handles_petrodollar_brief():
    # Direct replay of the iter-20 brief_summary fragment.
    brief = (
        "This lecture explores the potential decline of the petrodollar "
        "system and its implications for U.S. global dominance. The "
        "speaker outlines a hypothetical scenario where geopolitical "
        "shifts lead Gulf States to challenge the dollar's role in oil "
        "trade."
    )
    sentences = split_sentences(brief)
    assert len(sentences) == 2
    assert "U.S. global dominance" in sentences[0]
    # First sentence must not end at "U."
    assert not sentences[0].rstrip().endswith(" U.")


def test_split_sentences_handles_ai_style_single_letter_dot():
    sentences = split_sentences("The A.I. boom continues. Another sentence.")
    assert len(sentences) == 2
    assert "A.I." in sentences[0]


def test_split_sentences_preserves_existing_multi_sentence_behavior():
    # Regression guard for the speaker_fallback_chain test input style.
    sentences = split_sentences(
        "A. B. C. D. E. Full brief needed to pass repair helpers."
    )
    # Each single-letter-period followed by SPACE + uppercase letter is
    # a valid sentence boundary (not an abbreviation glued together).
    assert len(sentences) == 6


def test_split_sentences_empty():
    assert split_sentences("") == []
    assert split_sentences("   ") == []


# _split_sentences in schema.py is the pipeline entry; confirm it now
# routes through the shared splitter.
def test_schema_split_sentences_delegates_to_shared_helper():
    sentences = _split_sentences("U.S. policy matters here. The end.")
    assert len(sentences) == 2
    assert "U.S." in sentences[0]


# ---------- Overview bullet (first-sentence) regression ----------


def test_first_sentence_preserves_us_abbreviation():
    brief = (
        "This lecture explores the potential decline of the petrodollar "
        "system and its implications for U.S. global dominance. The "
        "speaker outlines a hypothetical scenario."
    )
    first = _first_sentence(brief)
    assert "U.S." in first
    assert "global dominance" in first
    assert not first.endswith(" U.")


# ---------- Fixture replay: iter-20 summary.json ----------


_ITER20_SUMMARY = (
    Path(__file__).resolve().parents[5]
    / "docs"
    / "summary_eval"
    / "youtube"
    / "iter-20"
    / "summary.json"
)


def test_replay_iter20_brief_overview_after_fix():
    """Replay iter-20 brief through the fixed splitter/first-sentence path.

    The on-disk ``summary.json`` is the BROKEN output — the brief
    contains ``"implications for U. S. Global dominance."`` (post-bug
    with a stray space). This test uses the correctly-cased source
    string (``U.S.``) to confirm the fixed code produces a clean
    single-sentence overview.
    """
    # Synthesize a corrected raw brief that the LLM would emit given the
    # known subject matter.
    raw_brief = (
        "This lecture explores the potential decline of the petrodollar "
        "system and its implications for U.S. global dominance. The "
        "speaker outlines a hypothetical scenario where geopolitical "
        "shifts and perceived U.S. security failures lead Gulf States "
        "to challenge the dollar's role in oil trade. The presentation "
        "details the petrodollar's historical context."
    )
    overview_bullet = _first_sentence(raw_brief)
    assert overview_bullet.endswith("global dominance.")
    assert "U.S." in overview_bullet
    # Old bug signature:
    assert not overview_bullet.rstrip().endswith(" U.")

    # And the same text through the schema-level splitter yields 3.
    assert len(_split_sentences(raw_brief)) == 3


def test_replay_iter20_mini_title_after_fix():
    """The raw LLM mini_title is not archived, so reconstruct the most
    likely input (``Petrodollar's Decline & US Dominance``) and confirm
    the fixed normalizer preserves the apostrophe."""
    result = _normalize_mini_title("Petrodollar's Decline & US Dominance")
    assert "Petrodollar's" in result
    # Check the iter-20 broken on-disk output is different from the new
    # fixed output so future reviewers can see the behaviour change.
    if _ITER20_SUMMARY.exists():
        broken = json.loads(_ITER20_SUMMARY.read_text(encoding="utf-8"))
        assert broken["mini_title"] == "Petrodollar s Decline US Dominance"
        assert result != broken["mini_title"]
