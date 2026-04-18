"""Tests for :mod:`website.features.rag_pipeline.generation.sanitize`."""

from website.features.rag_pipeline.generation.sanitize import sanitize_answer


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
