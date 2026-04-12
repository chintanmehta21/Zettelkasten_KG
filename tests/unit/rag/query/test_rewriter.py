from types import SimpleNamespace

import pytest

from website.features.rag_pipeline.query.rewriter import QueryRewriter


@pytest.mark.asyncio
async def test_rewrite_returns_original_when_no_history() -> None:
    rewriter = QueryRewriter(pool=SimpleNamespace())
    assert await rewriter.rewrite("What about later work?", []) == "What about later work?"


@pytest.mark.asyncio
async def test_rewrite_uses_last_5_turns() -> None:
    calls = {}

    class _Pool:
        async def generate_content(self, contents, **kwargs):
            calls["prompt"] = contents
            return "Standalone question"

    history = [{"role": "user", "content": f"turn-{idx}"} for idx in range(6)]
    result = await QueryRewriter(pool=_Pool()).rewrite("follow up", history)

    assert result == "Standalone question"
    assert "turn-0" not in calls["prompt"]
    assert "turn-1" in calls["prompt"]
    assert "turn-5" in calls["prompt"]


@pytest.mark.asyncio
async def test_rewrite_falls_back_to_original_on_llm_error() -> None:
    class _Pool:
        async def generate_content(self, contents, **kwargs):
            raise RuntimeError("boom")

    query = "What about his later work?"
    result = await QueryRewriter(pool=_Pool()).rewrite(query, [{"role": "user", "content": "Earlier context"}])
    assert result == query

