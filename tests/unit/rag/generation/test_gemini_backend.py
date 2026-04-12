from types import SimpleNamespace

import pytest

from website.features.rag_pipeline.errors import LLMUnavailable
from website.features.rag_pipeline.generation.gemini_backend import GeminiBackend


def _response(text="hello", prompt_tokens=10, completion_tokens=5, total_tokens=15, finish_reason="STOP"):
    return SimpleNamespace(
        text=text,
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt_tokens,
            candidates_token_count=completion_tokens,
            total_token_count=total_tokens,
        ),
        candidates=[SimpleNamespace(finish_reason=finish_reason)],
    )


@pytest.mark.asyncio
async def test_generate_succeeds_with_fast_tier() -> None:
    class _Pool:
        async def generate_content(self, contents, **kwargs):
            return _response("fast result"), "gemini-2.5-flash", 0

    result = await GeminiBackend(pool=_Pool()).generate(system_prompt="sys", user_prompt="usr", quality="fast")
    assert result.content == "fast result"
    assert result.model == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_falls_through_to_next_tier_on_rate_limit() -> None:
    class _Pool:
        def __init__(self):
            self.calls = []

        async def generate_content(self, contents, **kwargs):
            self.calls.append(kwargs["starting_model"])
            if kwargs["starting_model"] == "gemini-2.5-pro":
                raise RuntimeError("429 RESOURCE_EXHAUSTED")
            return _response("fallback result"), kwargs["starting_model"], 0

    pool = _Pool()
    result = await GeminiBackend(pool=pool).generate(system_prompt="sys", user_prompt="usr", quality="high")
    assert pool.calls == ["gemini-2.5-pro", "gemini-2.5-flash"]
    assert result.model == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_raises_llm_unavailable_when_all_tiers_exhausted() -> None:
    class _Pool:
        async def generate_content(self, contents, **kwargs):
            raise RuntimeError("429 RESOURCE_EXHAUSTED")

    with pytest.raises(LLMUnavailable):
        await GeminiBackend(pool=_Pool()).generate(system_prompt="sys", user_prompt="usr", quality="fast")


@pytest.mark.asyncio
async def test_generation_result_has_model_and_tokens() -> None:
    class _Pool:
        async def generate_content(self, contents, **kwargs):
            return _response(), "gemini-2.5-flash", 1

    result = await GeminiBackend(pool=_Pool()).generate(system_prompt="sys", user_prompt="usr", quality="fast")
    assert result.token_counts == {"prompt": 10, "completion": 5, "total": 15}
    assert result.finish_reason == "STOP"

