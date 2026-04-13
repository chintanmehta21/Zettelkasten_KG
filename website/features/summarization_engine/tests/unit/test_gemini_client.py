"""Tests for TieredGeminiClient."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.core.gemini_client import (
    GenerateResult,
    TieredGeminiClient,
)


@pytest.fixture
def fake_pool():
    pool = MagicMock()
    pool.generate_content = AsyncMock()
    return pool


@pytest.mark.asyncio
async def test_generate_pro_tier_calls_pool(fake_pool):
    response = MagicMock()
    response.text = '{"ok": true}'
    response.usage_metadata = MagicMock(
        prompt_token_count=100,
        candidates_token_count=50,
    )
    fake_pool.generate_content.return_value = (response, "gemini-2.5-pro", 0)

    client = TieredGeminiClient(fake_pool, load_config())
    result = await client.generate("hello", tier="pro")

    assert isinstance(result, GenerateResult)
    assert result.text == '{"ok": true}'
    assert result.model_used == "gemini-2.5-pro"
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    fake_pool.generate_content.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_flash_tier_starts_with_flash(fake_pool):
    response = MagicMock()
    response.text = "x"
    response.usage_metadata = MagicMock(prompt_token_count=10, candidates_token_count=5)
    fake_pool.generate_content.return_value = (response, "gemini-2.5-flash", 0)

    client = TieredGeminiClient(fake_pool, load_config())
    await client.generate("hi", tier="flash")

    _, kwargs = fake_pool.generate_content.call_args
    assert kwargs["starting_model"] == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_generate_passes_response_schema_for_structured(fake_pool):
    from pydantic import BaseModel

    class Out(BaseModel):
        value: str

    response = MagicMock()
    response.text = '{"value": "x"}'
    response.usage_metadata = MagicMock(prompt_token_count=10, candidates_token_count=5)
    fake_pool.generate_content.return_value = (response, "gemini-2.5-flash", 0)

    client = TieredGeminiClient(fake_pool, load_config())
    await client.generate("x", tier="flash", response_schema=Out)

    _, kwargs = fake_pool.generate_content.call_args
    assert kwargs["config"]["response_mime_type"] == "application/json"
    # response_schema is NOT passed to Gemini (additionalProperties unsupported)
    assert "response_schema" not in kwargs["config"]
