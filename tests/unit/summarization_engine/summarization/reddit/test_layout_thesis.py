"""Tests for the Reddit Thesis cornerstone injection (P6).

Locks the contract that ``compose_reddit_detailed`` always returns an
Overview section whose ``sub_sections`` contains a non-empty single-sentence
``Thesis`` entry, deterministically derived from the validated payload —
no LLM calls, no hallucinated facts.
"""
from __future__ import annotations

from website.features.summarization_engine.summarization.reddit.layout import (
    _extract_thesis_from_detailed,
    compose_reddit_detailed,
)
from website.features.summarization_engine.summarization.reddit.schema import (
    RedditCluster,
    RedditDetailedPayload,
    RedditStructuredPayload,
)


_TERMINAL_PUNCT = (".", "!", "?")


def _assert_thesis_shape(thesis: str) -> None:
    assert isinstance(thesis, str)
    assert thesis, "Thesis must be a non-empty string"
    assert thesis.endswith(_TERMINAL_PUNCT), f"Thesis must end with terminal punct: {thesis!r}"
    interior = thesis.rstrip(".!?")
    for terminator in (". ", "! ", "? "):
        assert terminator not in interior, f"Thesis must be a single sentence: {thesis!r}"


def _assert_overview_has_thesis(sections) -> str:
    overview = next(s for s in sections if s.heading == "Overview")
    assert "Core argument" in overview.sub_sections, "Overview.sub_sections must contain 'Core argument'"
    thesis_bullets = overview.sub_sections["Core argument"]
    assert len(thesis_bullets) == 1
    first_key = next(iter(overview.sub_sections.keys()))
    assert first_key == "Core argument", (
        f"Core argument must be the first sub-section, got: {first_key!r}"
    )
    _assert_thesis_shape(thesis_bullets[0])
    return thesis_bullets[0]


def _base_payload(**overrides) -> RedditStructuredPayload:
    detailed = {
        "op_intent": "Asking whether Rajkot truly drives IPO grey-market premium numbers.",
        "reply_clusters": [
            {
                "theme": "Skeptical of data",
                "reasoning": "No primary source was provided",
                "examples": ["GMP varies across brokers"],
            }
        ],
        "counterarguments": ["Mumbai brokers dominate the grey market"],
        "unresolved_questions": ["Can anyone produce broker tape?"],
        "moderation_context": "Mods removed low-effort replies",
    }
    detailed.update(overrides.pop("detailed_summary", {}))
    return RedditStructuredPayload(
        mini_title="r/india gmp-rajkot claim disputed",
        brief_summary=(
            "OP claims Rajkot drives IPO GMP numbers. Replies push back. "
            "Mumbai is cited. Data is thin. Mods removed several posts. "
            "Thread still open."
        ),
        tags=["india", "ipo", "gmp", "rajkot", "reddit-india", "investing", "grey-market"],
        detailed_summary=detailed,
        **overrides,
    )


def test_thesis_happy_path_uses_op_intent_first_sentence():
    """When op_intent is present, thesis = its first sentence."""
    payload = _base_payload()
    sections = compose_reddit_detailed(payload)
    thesis = _assert_overview_has_thesis(sections)
    assert "Rajkot" in thesis or "rajkot" in thesis.lower()


def test_thesis_fallback_uses_unresolved_question_when_op_intent_missing():
    """Empty op_intent → 'OP asked <first unresolved question>'."""
    payload = _base_payload()
    cleared = payload.model_copy(
        update={
            "detailed_summary": payload.detailed_summary.model_copy(
                update={"op_intent": ""}
            )
        }
    )
    thesis = _extract_thesis_from_detailed(cleared)
    _assert_thesis_shape(thesis)
    assert thesis.lower().startswith("op asked"), thesis
    assert "broker tape" in thesis.lower()


def test_thesis_skeleton_fallback_uses_subreddit_and_first_cluster_theme():
    """No op_intent, no questions → 'r/<sub> thread on <first cluster theme>'."""
    payload = _base_payload()
    cleared_detailed = payload.detailed_summary.model_copy(
        update={"op_intent": "", "unresolved_questions": []}
    )
    cleared = payload.model_copy(update={"detailed_summary": cleared_detailed})
    thesis = _extract_thesis_from_detailed(cleared)
    _assert_thesis_shape(thesis)
    assert thesis.lower().startswith("r/india thread on")
    assert "skeptical" in thesis.lower()


def test_thesis_terminal_punct_guaranteed_via_as_sentence():
    """Even when op_intent has no terminator, as_sentence forces one."""
    detailed = RedditDetailedPayload(
        op_intent="seeking advice without any terminator",
        reply_clusters=[
            RedditCluster(theme="Helpful tips", reasoning="Many users chimed in"),
        ],
        counterarguments=[],
        unresolved_questions=[],
        moderation_context=None,
    )
    payload = RedditStructuredPayload(
        mini_title="r/learnpython newbie asks for advice",
        brief_summary=(
            "Newbie asks for advice. Replies suggest tutorials. "
            "Some suggest projects. Others recommend books. "
            "Discussion stays civil. Thread is open."
        ),
        tags=["python", "learning", "beginner", "advice", "tutorials", "reddit", "community"],
        detailed_summary=detailed,
    )
    sections = compose_reddit_detailed(payload)
    thesis = _assert_overview_has_thesis(sections)
    assert thesis.endswith(_TERMINAL_PUNCT)
