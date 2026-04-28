"""Per-class regression: STEP_BACK queries return grounded answers without
canned refusal."""

from __future__ import annotations

from uuid import uuid4

import pytest

from website.features.rag_pipeline.types import ChatQuery, QueryClass

from .conftest import assert_no_canned_refusal, build_orchestrator


@pytest.mark.asyncio
async def test_step_back_supported(grounded_answer_text) -> None:
    orch = build_orchestrator(
        query_class=QueryClass.STEP_BACK,
        answer_text=grounded_answer_text,
        critic_verdicts=["supported"],
    )
    turn = await orch.answer(
        query=ChatQuery(content="Why does anyone build a personal wiki at all?"),
        user_id=uuid4(),
    )
    assert turn.critic_verdict == "supported"
    assert_no_canned_refusal(turn.content)
