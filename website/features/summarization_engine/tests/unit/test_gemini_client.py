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


@pytest.mark.asyncio
async def test_generate_multimodal_passes_contents_to_pool(fake_pool):
    response = MagicMock()
    response.text = "TITLE: Test Video\nCHANNEL: TestCh\nCONTENT:\nSome content"
    response.usage_metadata = MagicMock(
        prompt_token_count=200,
        candidates_token_count=80,
    )
    fake_pool.generate_content.return_value = (response, "gemini-2.5-flash", 1)

    client = TieredGeminiClient(fake_pool, load_config())
    # Simulate multimodal: a mock Part + text prompt
    mock_part = MagicMock()
    result = await client.generate_multimodal(
        [mock_part, "Analyze this video"],
        label="yt-test",
    )

    assert isinstance(result, GenerateResult)
    assert result.text == "TITLE: Test Video\nCHANNEL: TestCh\nCONTENT:\nSome content"
    assert result.model_used == "gemini-2.5-flash"
    assert result.input_tokens == 200
    assert result.output_tokens == 80
    assert result.key_index == 1

    _, kwargs = fake_pool.generate_content.call_args
    assert kwargs["contents"] == [mock_part, "Analyze this video"]
    assert kwargs["label"] == "yt-test"
    assert kwargs["starting_model"] == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_generate_multimodal_custom_starting_model(fake_pool):
    response = MagicMock()
    response.text = "ok"
    response.usage_metadata = None
    fake_pool.generate_content.return_value = (response, "gemini-2.5-pro", 0)

    client = TieredGeminiClient(fake_pool, load_config())
    result = await client.generate_multimodal(
        ["text content"],
        starting_model="gemini-2.5-pro",
    )

    assert result.model_used == "gemini-2.5-pro"
    assert result.input_tokens == 0  # usage_metadata is None
    _, kwargs = fake_pool.generate_content.call_args
    assert kwargs["starting_model"] == "gemini-2.5-pro"
