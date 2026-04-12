import pytest

from website.features.rag_pipeline.errors import LLMUnavailable
from website.features.rag_pipeline.generation.claude_backend import ClaudeBackend


def test_claude_backend_disabled_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert ClaudeBackend().enabled is False


@pytest.mark.asyncio
async def test_claude_backend_raises_when_disabled_and_called(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    backend = ClaudeBackend()
    with pytest.raises(LLMUnavailable):
        await backend.generate(system_prompt="sys", user_prompt="usr", quality="high")

