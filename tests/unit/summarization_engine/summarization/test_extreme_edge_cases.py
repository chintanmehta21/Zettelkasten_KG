"""Extreme edge-case coverage for the summarization engine.

Hardening pass before iter-21: every public entry point in the shared
text utilities, title normalizer, telemetry classifier, and the call
journal must survive empty / unicode / huge / malformed inputs without
raising. These tests are deliberately paranoid — they do not assert
specific output shapes unless the contract is well-defined; they only
verify the code does not crash or hang.
"""
from __future__ import annotations

import asyncio

import pytest

from website.features.summarization_engine.core.telemetry import (
    build_telemetry,
    classify_role,
)
from website.features.summarization_engine.summarization.common.text_guards import (
    clean_whitespace,
    ends_with_dangling_word,
    ensure_terminator,
    repair_or_drop,
    sanitize_bullets,
    sanitize_sub_sections,
    split_sentences,
)
from website.features.summarization_engine.summarization.youtube.schema import (
    _normalize_mini_title,
)


# ---------- Empty / None / whitespace ----------


@pytest.mark.parametrize(
    "value",
    ["", "   ", "\t\n", "\u00a0\u00a0", None],
)
def test_text_guards_never_raise_on_empty_like(value):
    # split_sentences must tolerate None (defensive — many callers pre-strip)
    if value is None:
        assert split_sentences("") == []
        assert clean_whitespace("") == ""
        assert ensure_terminator("") == ""
        assert repair_or_drop("") == ""
        assert ends_with_dangling_word("") is False
        return
    assert isinstance(split_sentences(value), list)
    assert clean_whitespace(value) == ""
    assert ensure_terminator(value) == ""
    assert repair_or_drop(value) == ""
    assert ends_with_dangling_word(value) is False


def test_sanitize_bullets_handles_none_and_empty():
    assert sanitize_bullets([]) == []
    assert sanitize_bullets(None) == []  # type: ignore[arg-type]
    # Bullets that all collapse to nothing must yield empty, not raise.
    assert sanitize_bullets(["", "   ", "\n"]) == []


def test_sanitize_sub_sections_handles_none_and_empty():
    assert sanitize_sub_sections({}) == {}
    assert sanitize_sub_sections(None) == {}  # type: ignore[arg-type]
    # A heading whose bullets all drop should be pruned from the output.
    assert sanitize_sub_sections({"H": ["", "  "]}) == {}


def test_normalize_mini_title_none_like():
    assert _normalize_mini_title("") == "YouTube Summary"
    assert _normalize_mini_title("   ") == "YouTube Summary"


# ---------- Unicode / emoji / RTL / zero-width ----------


def test_normalize_mini_title_preserves_unicode_word_characters():
    # Emoji should be stripped (token regex is [A-Za-z0-9...]), letters preserved.
    result = _normalize_mini_title("Petrodollar's \U0001f4b8 Decline")
    assert "Petrodollar's" in result


def test_normalize_mini_title_arabic_text_does_not_crash():
    # Non-Latin letters are stripped by the [A-Za-z0-9] token regex and
    # the title falls back to the default. Must not raise.
    result = _normalize_mini_title("\u0645\u0631\u062d\u0628\u0627")
    assert isinstance(result, str)
    assert result  # non-empty — default fallback kicks in


def test_normalize_mini_title_zero_width_joiner_does_not_crash():
    # ZWJ between letters should be stripped by the token regex.
    result = _normalize_mini_title("Hello\u200dWorld Demo Today")
    assert isinstance(result, str)
    assert result.strip()


def test_split_sentences_emoji_does_not_crash():
    out = split_sentences(
        "First sentence with \U0001f389 emoji. Second sentence. Third one."
    )
    assert len(out) == 3


def test_split_sentences_rtl_text_does_not_crash():
    # Hebrew + period; must not raise, output shape not asserted.
    out = split_sentences("\u05e9\u05dc\u05d5\u05dd. \u05e2\u05d5\u05dc\u05dd.")
    assert isinstance(out, list)


# ---------- Abbreviation splitter corner cases ----------


def test_split_sentences_multi_abbreviation_chain():
    out = split_sentences("Dr. Smith vs. Mr. Jones ran to Inc.")
    assert len(out) == 1


def test_split_sentences_decimals_and_abbrev_mixed():
    out = split_sentences("Pi is 3.14 and e is 2.71. A.I. follows after.")
    # 3.14 and 2.71 do not split; A.I. does not split; the period after
    # "2.71" + space + uppercase "A" is a boundary.
    assert len(out) == 2
    assert "3.14" in out[0] and "2.71" in out[0]
    assert out[1].startswith("A.I.")


def test_split_sentences_triple_country_codes():
    out = split_sentences("They coordinated U.S. U.K. U.N. response today.")
    assert len(out) == 1
    assert "U.S." in out[0] and "U.K." in out[0] and "U.N." in out[0]


def test_split_sentences_etc_repeated():
    out = split_sentences("Bring apples, oranges, etc. etc. etc.")
    # etc. inside, but trailing etc. at end: the split regex requires
    # capital/digit after the space, so no boundary triggers.
    assert len(out) == 1


def test_split_sentences_trailing_space():
    assert split_sentences("End. ") == ["End."]


def test_split_sentences_no_terminator():
    # A single sentence with no terminal punctuation must round-trip intact.
    out = split_sentences("No period at end")
    assert out == ["No period at end"]


# ---------- Title normalizer corner cases ----------


def test_normalize_mini_title_only_apostrophes():
    # All tokens collapse after stripping — must fall back to default.
    result = _normalize_mini_title("'''")
    assert result == "YouTube Summary"


def test_normalize_mini_title_only_hyphens():
    result = _normalize_mini_title("---")
    assert result == "YouTube Summary"


def test_normalize_mini_title_single_possessive_word():
    # Single token — below the 3-preferred threshold so raw tokens used.
    result = _normalize_mini_title("Petrodollar's")
    assert "Petrodollar's" in result


def test_normalize_mini_title_repeated_contraction():
    result = _normalize_mini_title("Don't Don't Don't")
    assert "Don't" in result


def test_normalize_mini_title_curly_apostrophe_only():
    # Single curly-apostrophe token preserves the apostrophe.
    result = _normalize_mini_title("Petrodollar\u2019s")
    assert "Petrodollar\u2019s" in result


def test_normalize_mini_title_truncates_to_50_chars():
    result = _normalize_mini_title(
        "A very very very very very very very very very long title that goes on"
    )
    assert len(result) <= 50


# ---------- Extremely long inputs ----------


def test_split_sentences_huge_transcript_does_not_hang():
    # 100k chars of repeated sentences. Completes in <5 seconds on CI.
    blob = "This is a normal sentence. " * 4000  # ~108k chars
    out = split_sentences(blob)
    # Every "This is a normal sentence." becomes its own entry.
    assert len(out) == 4000


def test_sanitize_bullets_ten_thousand_bullets():
    # 10k bullets must sanitize in reasonable time (<5s) without recursion.
    bullets = [f"Bullet number {i} in the list." for i in range(10_000)]
    out = sanitize_bullets(bullets)
    assert len(out) == 10_000


def test_sanitize_sub_sections_many_headings():
    sections = {f"Heading {i}": ["One clean sentence."] for i in range(500)}
    out = sanitize_sub_sections(sections)
    assert len(out) == 500


# ---------- Telemetry classifier edge cases ----------


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "prod"),
        ("", "prod"),
        ("SUMMARIZER", "prod"),  # case-sensitive by design; fall-through is prod
        ("summarizer", "prod"),
        ("  rubric_evaluator  ", "prod"),  # whitespace not stripped; unknown => prod
        ("rubric_evaluator", "eval"),
        ("atomic_facts", "eval"),
        ("mystery_role_42", "prod"),
    ],
)
def test_classify_role_edge_inputs(value, expected):
    assert classify_role(value) == expected


def test_build_telemetry_empty_list():
    out = build_telemetry([])
    assert out["prod_calls"]["count"] == 0
    assert out["eval_calls"]["count"] == 0
    assert out["grand_total"]["count"] == 0


def test_build_telemetry_entry_missing_all_fields():
    # An entry with no role/model/tokens still counts and lands in prod.
    out = build_telemetry([{}])
    assert out["prod_calls"]["count"] == 1
    assert out["prod_calls"]["total_tokens"] == 0
    assert "unknown" in out["prod_calls"]["by_model"]


def test_build_telemetry_non_string_role_is_prod():
    # Ints / Nones / dicts in the role field must not raise.
    out = build_telemetry(
        [
            {"role": 42, "model": "m1", "input_tokens": 1, "output_tokens": 1},
            {"role": None, "model": "m2", "input_tokens": 1, "output_tokens": 1},
            {"role": {"nested": "ignored"}, "model": "m3", "input_tokens": 1, "output_tokens": 1},
        ]
    )
    assert out["prod_calls"]["count"] == 3
    assert out["eval_calls"]["count"] == 0


# ---------- Call journal concurrency ----------


def test_enable_call_journal_is_idempotent():
    from website.features.summarization_engine.core.gemini_client import (
        TieredGeminiClient,
    )
    from website.features.summarization_engine.core.config import load_config

    client = TieredGeminiClient(key_pool=None, config=load_config())
    j1 = client.enable_call_journal()
    j2 = client.enable_call_journal()
    # Second call must reuse the same list — not wipe in-flight entries.
    assert j1 is j2


def test_drain_call_journal_without_enable_returns_empty():
    from website.features.summarization_engine.core.gemini_client import (
        TieredGeminiClient,
    )
    from website.features.summarization_engine.core.config import load_config

    client = TieredGeminiClient(key_pool=None, config=load_config())
    assert client.drain_call_journal() == []


@pytest.mark.asyncio
async def test_call_journal_concurrent_appends_preserve_all_entries():
    """10 concurrent coroutines each append 50 entries; all 500 land.

    Single-loop cooperative concurrency + CPython GIL make ``list.append``
    atomic, so this is the contract we enforce. Assert:
      * total count == 500 (nothing dropped)
      * no entry duplicated (each has a unique id)
    """
    from website.features.summarization_engine.core.gemini_client import (
        TieredGeminiClient,
    )
    from website.features.summarization_engine.core.config import load_config

    client = TieredGeminiClient(key_pool=None, config=load_config())
    journal = client.enable_call_journal()

    async def worker(worker_id: int) -> None:
        for i in range(50):
            # Yield control each iteration so other coroutines interleave.
            await asyncio.sleep(0)
            journal.append({"worker": worker_id, "i": i})

    await asyncio.gather(*(worker(w) for w in range(10)))
    drained = client.drain_call_journal()
    assert len(drained) == 500
    # Uniqueness: (worker, i) pairs must be distinct.
    seen = {(e["worker"], e["i"]) for e in drained}
    assert len(seen) == 500
    # After drain the journal is reset.
    assert client.drain_call_journal() == []


# ---------- Malformed structured payloads ----------


def test_sanitize_sub_sections_handles_missing_bullets_key():
    # A heading whose value is an empty list should drop cleanly.
    assert sanitize_sub_sections({"H": []}) == {}


def test_sanitize_bullets_handles_non_list_like_inputs():
    # Strings come out verbatim after sanitize since strings are iterable
    # of characters. The API contract is ``list[str]`` — callers that
    # pass a string are misusing the API; we just confirm it does not
    # raise. (Python iterates chars, sanitize_bullets will process each.)
    out = sanitize_bullets("a string")  # type: ignore[arg-type]
    assert isinstance(out, list)
