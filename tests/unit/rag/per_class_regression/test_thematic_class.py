"""Per-class regression: THEMATIC queries return grounded synthesis without
canned refusal."""

from __future__ import annotations

from uuid import uuid4

import pytest

from website.features.rag_pipeline.types import ChatQuery, QueryClass

from .conftest import assert_no_canned_refusal, build_orchestrator


@pytest.mark.asyncio
async def test_thematic_supported(grounded_answer_text) -> None:
    orch = build_orchestrator(
        query_class=QueryClass.THEMATIC,
        answer_text=grounded_answer_text,
        critic_verdicts=["supported"],
    )
    turn = await orch.answer(
        query=ChatQuery(content="What are the recurring themes around personal knowledge management?"),
        user_id=uuid4(),
    )
    assert turn.critic_verdict == "supported"
    assert_no_canned_refusal(turn.content)
