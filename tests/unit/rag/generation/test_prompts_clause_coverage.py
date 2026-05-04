"""iter-10 P13: clause-coverage self-check rule in SYSTEM_PROMPT.

iter-09 RAGAS answer_relevancy 74.29 vs faithfulness 87.50 — model is faithful
but doesn't fully address every clause of multi-part questions. The rule
forces explicit per-clause coverage acknowledgement before finalising.
"""
from website.features.rag_pipeline.generation.prompts import SYSTEM_PROMPT


def test_system_prompt_contains_coverage_check_block():
    assert "COVERAGE CHECK" in SYSTEM_PROMPT


def test_system_prompt_mentions_sub_question_or_clause():
    assert "sub-question" in SYSTEM_PROMPT.lower() or "clause" in SYSTEM_PROMPT.lower()


def test_system_prompt_forbids_inventing_facts_to_plug_gap():
    """Coverage check must NOT invite hallucination to fill missing clauses."""
    assert "do not invent" in SYSTEM_PROMPT.lower()


def test_system_prompt_keeps_existing_refusal_phrase():
    """The new rule must not break the canned refusal contract."""
    assert "I can't find that in your Zettels." in SYSTEM_PROMPT
