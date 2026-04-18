from website.features.rag_pipeline.generation.prompts import (
    CHAIN_OF_THOUGHT_PREFIX,
    SYSTEM_PROMPT,
    USER_TEMPLATE,
)


def test_system_prompt_contains_seven_rules() -> None:
    for number in range(1, 8):
        assert f"{number}." in SYSTEM_PROMPT


def test_user_template_has_context_xml_and_query_placeholders() -> None:
    assert "{context_xml}" in USER_TEMPLATE
    assert "{user_query}" in USER_TEMPLATE


def test_cot_prefix_exists_as_separate_constant() -> None:
    assert "<scratchpad>" in CHAIN_OF_THOUGHT_PREFIX


def test_system_prompt_specifies_citation_format() -> None:
    """The citation format must be concrete so the LLM doesn't invent its own
    ([1], [source], etc.). The assembler emits zettel ids as ``id="..."`` and
    the prompt must reference that exact shape."""
    assert '[id="<zettel-id>"]' in SYSTEM_PROMPT


def test_system_prompt_mentions_primary_passage_signal() -> None:
    """Context assembly marks the highest-score passage with primary="true".
    The prompt must tell the LLM this attribute exists and how to weight it,
    otherwise the signal is wasted."""
    assert 'primary="true"' in SYSTEM_PROMPT


def test_system_prompt_has_canonical_refusal_phrase() -> None:
    """A fixed refusal phrase lets callers (UI, evals) detect out-of-scope
    answers deterministically instead of pattern-matching fuzzy hedging."""
    assert "I can't find that in your Zettels." in SYSTEM_PROMPT


def test_system_prompt_forbids_outside_knowledge() -> None:
    """Rule 1 must explicitly forbid supplementing with training-data
    knowledge — the default LLM tendency is to 'fill in' and that breaks
    groundedness."""
    assert "common knowledge" in SYSTEM_PROMPT.lower()

