"""Tests for :mod:`website.features.rag_pipeline.generation.sanitize`."""

from website.features.rag_pipeline.generation.sanitize import (
    sanitize_answer,
    strip_invalid_citations,
)


def test_clean_answer_passes_through_unchanged() -> None:
    """A well-formed answer with no leakage should be untouched (modulo the
    outer whitespace strip, which is always applied)."""
    text = 'Transformers scale better than RNNs [id="zettel-1"].'
    assert sanitize_answer(text) == text


def test_strips_balanced_scratchpad_block() -> None:
    text = (
        '<scratchpad>Zettel A is most relevant. Zettel B contradicts it.</scratchpad>\n\n'
        'Self-attention replaces recurrence [id="attn"].'
    )
    result = sanitize_answer(text)
    assert "<scratchpad>" not in result
    assert "Zettel A" not in result
    assert 'Self-attention replaces recurrence [id="attn"].' in result


def test_strips_trailing_unclosed_scratchpad() -> None:
    """If the model ran out of tokens mid-scratchpad, the unclosed span is
    truncated so the user never sees partial chain-of-thought."""
    text = 'Final answer [id="a"].\n\n<scratchpad>Then I noticed that'
    result = sanitize_answer(text)
    assert "<scratchpad>" not in result
    assert "Then I noticed" not in result
    assert 'Final answer [id="a"].' in result


def test_removes_leaked_context_tags_but_keeps_inner_text() -> None:
    """Rule 7 forbids echoing context XML. If the model leaks <zettel> or
    <passage> tags, strip the tags but preserve any paraphrased content
    between them so the answer isn't gutted."""
    text = (
        '<context><zettel id="x"><passage>Transformers scale better.</passage></zettel></context>'
        ' [id="x"]'
    )
    result = sanitize_answer(text)
    assert "<context>" not in result
    assert "<zettel" not in result
    assert "<passage" not in result
    assert "Transformers scale better." in result
    assert '[id="x"]' in result


def test_strips_leading_answer_prefix() -> None:
    text = 'Answer: The transformer paper is from 2017 [id="paper"].'
    assert sanitize_answer(text) == 'The transformer paper is from 2017 [id="paper"].'


def test_leading_answer_prefix_case_insensitive() -> None:
    assert sanitize_answer("answer:  hello") == "hello"
    assert sanitize_answer("ANSWER: hi there") == "hi there"


def test_collapses_extra_blank_lines() -> None:
    text = "First paragraph.\n\n\n\n\nSecond paragraph."
    assert sanitize_answer(text) == "First paragraph.\n\nSecond paragraph."


def test_preserves_single_paragraph_break() -> None:
    text = "First paragraph.\n\nSecond paragraph."
    assert sanitize_answer(text) == text


def test_empty_string_returns_empty() -> None:
    assert sanitize_answer("") == ""


def test_whitespace_only_returns_empty() -> None:
    assert sanitize_answer("   \n\t  \n  ") == ""


def test_strip_invalid_citations_keeps_all_when_every_id_valid() -> None:
    text = 'Transformers scale better [id="zettel-a"] and parallelize [id="zettel-b"].'
    cleaned, dropped = strip_invalid_citations(text, {"zettel-a", "zettel-b"})
    assert cleaned == text
    assert dropped == []


def test_strip_invalid_citations_drops_hallucinated_id_and_reports_it() -> None:
    text = 'Claim A [id="real"] and claim B [id="hallucinated"].'
    cleaned, dropped = strip_invalid_citations(text, {"real"})
    assert '[id="hallucinated"]' not in cleaned
    assert '[id="real"]' in cleaned
    assert dropped == ["hallucinated"]


def test_strip_invalid_citations_tightens_space_before_punctuation() -> None:
    """After removing a citation token the space before a period would leave
    a gap. Verify the cleanup collapses the gap so the sentence reads
    naturally."""
    text = 'Transformers scale well [id="bogus"].'
    cleaned, dropped = strip_invalid_citations(text, {"real"})
    assert cleaned == "Transformers scale well."
    assert dropped == ["bogus"]


def test_strip_invalid_citations_reports_every_bad_occurrence() -> None:
    """Duplicates and order matter for observability — callers should be
    able to count hallucination frequency from the returned list without
    re-parsing the original string."""
    text = 'A [id="x"] B [id="y"] C [id="x"] D [id="real"].'
    cleaned, dropped = strip_invalid_citations(text, {"real"})
    assert dropped == ["x", "y", "x"]
    assert '[id="real"]' in cleaned


def test_strip_invalid_citations_accepts_single_quoted_ids() -> None:
    """Some LLMs normalize double quotes to single quotes inside citation
    tokens. Both forms should be recognized by the validator."""
    text = "Claim [id='zettel-a'] stands."
    cleaned, dropped = strip_invalid_citations(text, {"zettel-a"})
    assert cleaned == text
    assert dropped == []


def test_strip_invalid_citations_noop_on_empty_input() -> None:
    cleaned, dropped = strip_invalid_citations("", {"anything"})
    assert cleaned == ""
    assert dropped == []


def test_strip_invalid_citations_empty_valid_set_drops_every_id() -> None:
    """When the context produced no candidates there are no valid ids — any
    citation the LLM emits is a hallucination and must be stripped."""
    text = 'Made up [id="a"] stuff [id="b"].'
    cleaned, dropped = strip_invalid_citations(text, set())
    assert '[id="' not in cleaned
    assert dropped == ["a", "b"]
