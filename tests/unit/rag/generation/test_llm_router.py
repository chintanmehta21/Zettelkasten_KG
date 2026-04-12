import pytest

from website.features.rag_pipeline.generation.llm_router import LLMRouter
from website.features.rag_pipeline.types import ChatQuery


class _Backend:
    def __init__(self, name: str, enabled: bool = True):
        self.name = name
        self.enabled = enabled

    async def generate(self, *, system_prompt, user_prompt, quality):
        return self.name


@pytest.mark.asyncio
async def test_router_picks_gemini_when_claude_disabled() -> None:
    router = LLMRouter(gemini=_Backend("gemini"), claude=_Backend("claude", enabled=False))
    result = await router.generate(query=ChatQuery(content="q", quality="high"), system_prompt="sys", user_prompt="usr")
    assert result == "gemini"


@pytest.mark.asyncio
async def test_router_picks_claude_when_quality_high_and_enabled() -> None:
    router = LLMRouter(gemini=_Backend("gemini"), claude=_Backend("claude", enabled=True))
    result = await router.generate(query=ChatQuery(content="q", quality="high"), system_prompt="sys", user_prompt="usr")
    assert result == "claude"

