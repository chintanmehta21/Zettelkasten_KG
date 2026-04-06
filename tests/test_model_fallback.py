"""Tests for summarizer integration with GeminiKeyPool.

Verifies that GeminiSummarizer correctly delegates to the pool and
handles responses and failures as expected.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from google.genai.errors import ClientError

from telegram_bot.models.capture import ExtractedContent, SourceType
from telegram_bot.pipeline.summarizer import GeminiSummarizer


def _make_content(body_len: int = 500, source_type: SourceType = SourceType.WEB) -> ExtractedContent:
    return ExtractedContent(
        url="https://example.com/test",
        source_type=source_type,
        title="Test",
        body="x" * body_len,
    )


def _make_mock_pool():
    """Create a mock key pool."""
    pool = MagicMock()
    pool.generate_content = AsyncMock()
    return pool


@patch("telegram_bot.pipeline.summarizer.get_key_pool")
def test_summarizer_uses_pool(mock_get_pool):
    """GeminiSummarizer delegates to get_key_pool()."""
    mock_pool = _make_mock_pool()
    mock_get_pool.return_value = mock_pool

    s = GeminiSummarizer()
    assert s._pool is mock_pool


@patch("telegram_bot.pipeline.summarizer.get_key_pool")
async def test_summarizer_passes_starting_model(mock_get_pool):
    """Summarizer passes content-aware starting_model to pool."""
    mock_pool = _make_mock_pool()
    mock_get_pool.return_value = mock_pool

    mock_response = MagicMock()
    mock_response.text = '{"detailed_summary":"s","brief_summary":"b","tags":{},"one_line_summary":"o"}'
    mock_response.usage_metadata = MagicMock(total_token_count=100)
    mock_pool.generate_content.return_value = (mock_response, "gemini-2.5-flash-lite", 0)

    s = GeminiSummarizer()
    content = _make_content(body_len=500, source_type=SourceType.WEB)
    result = await s.summarize(content)

    # Short web content -> flash-lite starting model
    call_kwargs = mock_pool.generate_content.call_args
    assert call_kwargs.kwargs["starting_model"] == "gemini-2.5-flash-lite"
    assert not result.is_raw_fallback


@patch("telegram_bot.pipeline.summarizer.get_key_pool")
async def test_summarizer_raw_fallback_on_pool_failure(mock_get_pool):
    """When pool raises (all keys/models exhausted), returns raw fallback."""
    mock_pool = _make_mock_pool()
    mock_get_pool.return_value = mock_pool

    mock_pool.generate_content.side_effect = ClientError(
        code=429,
        response_json={"error": {"message": "all exhausted"}},
    )

    s = GeminiSummarizer()
    content = _make_content(body_len=100)
    result = await s.summarize(content)

    assert result.is_raw_fallback is True
    assert result.summary == content.body[:5000]


@patch("telegram_bot.pipeline.summarizer.get_key_pool")
async def test_summarizer_deprecated_api_key_ignored(mock_get_pool):
    """Passing api_key is accepted but ignored (backward compat)."""
    mock_pool = _make_mock_pool()
    mock_get_pool.return_value = mock_pool

    s = GeminiSummarizer(api_key="old-key-ignored")
    assert s._pool is mock_pool


@patch("telegram_bot.pipeline.summarizer.get_key_pool")
async def test_summarizer_long_content_uses_flash(mock_get_pool):
    """Long content routes to gemini-2.5-flash starting model."""
    mock_pool = _make_mock_pool()
    mock_get_pool.return_value = mock_pool

    mock_response = MagicMock()
    mock_response.text = '{"detailed_summary":"s","brief_summary":"b","tags":{},"one_line_summary":"o"}'
    mock_response.usage_metadata = MagicMock(total_token_count=100)
    mock_pool.generate_content.return_value = (mock_response, "gemini-2.5-flash", 0)

    s = GeminiSummarizer()
    content = _make_content(body_len=10000, source_type=SourceType.YOUTUBE)
    await s.summarize(content)

    call_kwargs = mock_pool.generate_content.call_args
    assert call_kwargs.kwargs["starting_model"] == "gemini-2.5-flash"
