"""Per-class regression: VAGUE queries surface a grounded answer rather than
canned refusal when retrieval returns matched candidates."""

from __future__ import annotations

from uuid import uuid4

import pytest

from website.features.rag_pipeline.types import ChatQuery, QueryClass

from .conftest import assert_no_canned_refusal, build_orchestrator


@pytest.mark.asyncio
async def test_vague_query_supported(grounded_answer_text) -> None:
    orch = build_orchestrator(
        query_class=QueryClass.VAGUE,
        answer_text=grounded_answer_text,
        critic_verdicts=["supported"],
    )
    turn = await orch.answer(
        query=ChatQuery(content="anything about wikis?"),
        user_id=uuid4(),
    )
    assert turn.critic_verdict == "supported"
    assert_no_canned_refusal(turn.content)


@pytest.mark.asyncio
async def test_vague_query_partial_still_returns_answer(grounded_answer_text) -> None:
    orch = build_orchestrator(
        query_class=QueryClass.VAGUE,
        answer_text=grounded_answer_text,
        critic_verdicts=["partial"],
    )
    turn = await orch.answer(
        query=ChatQuery(content="anything about that?"),
        user_id=uuid4(),
    )
    assert turn.critic_verdict == "partial"
    assert turn.content
    assert_no_canned_refusal(turn.content)
