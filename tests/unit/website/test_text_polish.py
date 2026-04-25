"""Unit tests for ``website.core.text_polish``.

Each polish rule has positive (transforms input) and negative
(leaves benign input untouched) cases.  Idempotency is verified for the
full pipeline.
"""
from __future__ import annotations

import pytest

from website.core.text_polish import (
    comma_after_adverbial,
    comma_outside_quote,
    dedupe_articles,
    fix_sentence_punctuation,
    is_caveat_only_line,
    normalize_apostrophes,
    polish,
    polish_envelope,
    rewrite_reddit_tag,
    rewrite_tags,
    strip_caveats,
    strip_dangling_preposition,
)


# ---- caveat / pipeline-metadata stripping --------------------------------

class TestStripCaveats:
    def test_drops_caveat_clause(self):
        s = "OP raised concerns. Caveat: Rendered comments covered only part of the thread (13/38 visible; divergence 65."
        out = strip_caveats(s)
        assert "Caveat" not in out
        assert "OP raised concerns" in out

    def test_drops_note_to_ingester(self):
        out = strip_caveats("Body. Note to ingester: skip this.")
        assert "Note to ingester" not in out
        assert "Body" in out

    def test_keeps_non_caveat_text(self):
        s = "Plain prose with no metadata at all."
        assert strip_caveats(s) == s

    def test_full_caveat_line_detection(self):
        assert is_caveat_only_line("Caveat: divergence 65%.")
        assert is_caveat_only_line("Pipeline note: skip me")
        assert not is_caveat_only_line("This sentence is fine.")


# ---- apostrophe restoration / quote normalization -------------------------

class TestApostrophes:
    def test_restores_proper_noun_possessive(self):
        out = normalize_apostrophes("Karpathy s LLM Introduction")
        assert "Karpathy's LLM" in out

    def test_restores_long_word_possessive(self):
        out = normalize_apostrophes("LeCun s Vision of AI")
        assert "LeCun's Vision" in out

    def test_does_not_touch_short_word(self):
        # "is s foo" — leading is too short, should not become "is's"
        out = normalize_apostrophes("it s ok")
        assert "it's" not in out  # 'it' is too short to trigger our rule

    def test_curly_to_straight(self):
        out = normalize_apostrophes("‘hello’ and “world”")
        assert "'hello'" in out
        assert '"world"' in out

    def test_idempotent(self):
        s = "Karpathy's LLM"
        assert normalize_apostrophes(normalize_apostrophes(s)) == normalize_apostrophes(s)


# ---- comma after adverbial leads ------------------------------------------

class TestCommaAfterAdverbial:
    def test_along_the_way(self):
        out = comma_after_adverbial("Along the way The speaker references Windows 10.")
        assert out.startswith("Along the way, The speaker")

    def test_in_fact_mid_paragraph(self):
        s = "He spoke. In fact The speaker noted X."
        out = comma_after_adverbial(s)
        assert "In fact, The speaker" in out

    def test_however(self):
        out = comma_after_adverbial("However Things changed.")
        assert out == "However, Things changed."

    def test_no_change_when_already_comma(self):
        s = "However, things changed."
        assert comma_after_adverbial(s) == s

    def test_no_change_when_lowercase_follows(self):
        s = "Along the way the speaker mumbled."
        # Our rule requires uppercase next char — should not insert.
        assert comma_after_adverbial(s) == s


# ---- comma outside closing quote ------------------------------------------

class TestCommaOutsideQuote:
    def test_single_quote(self):
        out = comma_outside_quote("'product-minded engineers,' the article said.")
        assert "engineers'," in out
        assert "engineers,'" not in out

    def test_double_quote(self):
        out = comma_outside_quote('"foo," he said.')
        assert 'foo",' in out

    def test_no_open_quote_skips(self):
        # No matching open quote in same sentence; leave alone.
        out = comma_outside_quote("trailing,'unmatched")
        assert out == "trailing,'unmatched"

    def test_flip_when_possessive_apostrophes_precede(self):
        # Real-world Pragmatic Engineer brief — possessives "Hoskins'" and
        # "O'Reilly" must NOT throw off parity counting; the inner quoted
        # phrase 'The Product-Minded Engineer' should still get its comma
        # flipped outside the closing quote.
        text = (
            "It introduces Drew Hoskins' new O'Reilly book, "
            "'The Product-Minded Engineer,' detailing his extensive "
            "background."
        )
        out = comma_outside_quote(text)
        assert "'The Product-Minded Engineer'," in out
        assert "'The Product-Minded Engineer,'" not in out

    def test_flip_with_multiple_possessives_and_double_quote(self):
        text = "Don't worry — 'go ahead,' he said about Sam's plan."
        out = comma_outside_quote(text)
        assert "'go ahead'," in out
        assert "'go ahead,'" not in out


# ---- sentence-final punctuation -------------------------------------------

class TestPunctuation:
    def test_double_period(self):
        assert fix_sentence_punctuation("Sentence..").endswith("Sentence.")

    def test_comma_period(self):
        assert "X." in fix_sentence_punctuation("X,.")

    def test_space_period(self):
        assert fix_sentence_punctuation("Word .") == "Word."


# ---- duplicated articles --------------------------------------------------

class TestDedupeArticles:
    def test_the_the(self):
        assert dedupe_articles("see the the cat") == "see the cat"

    def test_is_is(self):
        assert dedupe_articles("it is is here") == "it is here"

    def test_no_change(self):
        s = "the cat is here"
        assert dedupe_articles(s) == s


# ---- dangling preposition -------------------------------------------------

class TestDanglingPreposition:
    def test_strips_with(self):
        assert strip_dangling_preposition("He left with.") == "He left."

    def test_strips_and(self):
        assert strip_dangling_preposition("Things and.") == "Things."

    def test_keeps_normal(self):
        s = "He left."
        assert strip_dangling_preposition(s) == s


# ---- reddit tag rewrite ---------------------------------------------------

class TestRedditTag:
    def test_basic_rewrite(self):
        assert rewrite_reddit_tag("r-hinduism") == "r/hinduism"

    def test_underscore_preserved(self):
        # Subreddit ids can have underscores; keep them as-is.
        assert rewrite_reddit_tag("r-machine_learning") == "r/machine_learning"

    def test_idempotent(self):
        # Already-rewritten tags pass through unchanged.
        assert rewrite_reddit_tag("r/hinduism") == "r/hinduism"

    def test_unrelated_tag_untouched(self):
        assert rewrite_reddit_tag("ml") == "ml"
        assert rewrite_reddit_tag("python") == "python"

    def test_rewrite_tags_list(self):
        assert rewrite_tags(["r-hinduism", "philosophy"]) == ["r/hinduism", "philosophy"]


# ---- full polish pipeline -------------------------------------------------

class TestPolish:
    def test_full_pipeline(self):
        s = (
            "Along the way The speaker references Windows 10. "
            "Karpathy s LLM intro covers 'product-minded engineers,' he said. "
            "Caveat: divergence 65%."
        )
        out = polish(s)
        assert "Along the way, The speaker" in out
        assert "Karpathy's LLM" in out
        assert "engineers'," in out
        assert "Caveat" not in out

    def test_idempotent(self):
        s = "Along the way The speaker spoke. Karpathy s view changed."
        once = polish(s)
        twice = polish(once)
        assert once == twice

    def test_empty(self):
        assert polish("") == ""
        assert polish(None) == ""


# ---- envelope walker ------------------------------------------------------

class TestPolishEnvelope:
    def test_walks_brief_and_detailed(self):
        env = {
            "mini_title": "Karpathy s LLM",
            "brief_summary": "However The speaker spoke.",
            "detailed_summary": [
                {
                    "heading": "Overview",
                    "bullets": [
                        "Along the way The speaker noted X.",
                        "Caveat: pipeline note.",
                        "Real bullet here.",
                    ],
                    "sub_sections": {
                        "Sub": ["In fact The author wrote Y."],
                    },
                }
            ],
            "closing_remarks": "Eventually He stopped.",
        }
        out = polish_envelope(env)
        assert out["mini_title"] == "Karpathy's LLM"
        assert out["brief_summary"].startswith("However, The speaker")
        sec = out["detailed_summary"][0]
        # Caveat-only bullet dropped, others polished.
        assert all("Caveat" not in b for b in sec["bullets"])
        assert any("Along the way," in b for b in sec["bullets"])
        assert "In fact, The author" in sec["sub_sections"]["Sub"][0]
        assert out["closing_remarks"].startswith("Eventually, He")

    def test_non_dict_passthrough(self):
        assert polish_envelope("string") == "string"
        assert polish_envelope(None) is None
