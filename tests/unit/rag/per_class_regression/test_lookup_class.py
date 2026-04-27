"""Per-class regression: LOOKUP queries must not over-refuse on grounded
paraphrase answers (the q3/q8 smoking-gun in iter-02/scores.md)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from website.features.rag_pipeline.types import ChatQuery, QueryClass

from .conftest import assert_no_canned_refusal, build_orchestrator


@pytest.mark.asyncio
async def test_lookup_paraphrase_does_not_canned_refuse(grounded_answer_text) -> None:
    """q3-style: critic accepts paraphrase as 'supported' -> answer flows."""
    orch = build_orchestrator(
        query_class=QueryClass.LOOKUP,
        answer_text=grounded_answer_text,
        critic_verdicts=["supported"],
    )
    turn = await orch.answer(
        query=ChatQuery(content="What does the Pragmatic Engineer say about personal wikis?"),
        user_id=uuid4(),
    )
    assert turn.content
    assert turn.critic_verdict == "supported"
    assert_no_canned_refusal(turn.content)
    assert len(turn.citations) >= 1


@pytest.mark.asyncio
async def test_lookup_2nd_pass_unsupported_returns_low_confidence_not_refusal(
    grounded_answer_text,
) -> None:
    """Spec 2A.2 + 2A.3: q8-style — even when critic stays unsupported on
    retry, the answer is the model's draft + low-confidence tag, NEVER
    a canned refusal."""
    orch = build_orchestrator(
        query_class=QueryClass.LOOKUP,
        answer_text=grounded_answer_text,
        critic_verdicts=["unsupported", "unsupported"],
    )
    turn = await orch.answer(
        query=ChatQuery(content="How do I set up zk for personal wiki?"),
        user_id=uuid4(),
    )
    assert turn.critic_verdict == "retried_low_confidence"
    assert "<summary>How sure am I?</summary>" in turn.content
    assert_no_canned_refusal(turn.content)
