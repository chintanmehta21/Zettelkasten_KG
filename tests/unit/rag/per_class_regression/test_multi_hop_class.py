"""Per-class regression: MULTI_HOP queries return grounded answers without
canned refusal when retrieval surfaces candidates."""

from __future__ import annotations

from uuid import uuid4

import pytest

from website.features.rag_pipeline.types import ChatQuery, QueryClass

from .conftest import assert_no_canned_refusal, build_orchestrator


@pytest.mark.asyncio
async def test_multi_hop_supported(grounded_answer_text) -> None:
    orch = build_orchestrator(
        query_class=QueryClass.MULTI_HOP,
        answer_text=grounded_answer_text,
        critic_verdicts=["supported"],
    )
    turn = await orch.answer(
        query=ChatQuery(
            content=(
                "Compare the Pragmatic Engineer's wiki advice with the Substack "
                "newsletter on note-taking systems."
            )
        ),
        user_id=uuid4(),
    )
    assert turn.critic_verdict == "supported"
    assert_no_canned_refusal(turn.content)
