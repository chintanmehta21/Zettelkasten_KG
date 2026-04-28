"""Iter-03 fix: GeminiKeyPool must expose generate_structured.

Both website/features/rag_pipeline/query/metadata.py:_a_pass and
ingest/metadata_enricher.py:_extract_entities call key_pool.generate_structured;
its absence caused those paths to log
"'GeminiKeyPool' object has no attribute 'generate_structured'" and degrade
silently to slower fallbacks, contributing to OOM pressure under load.
"""
from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from website.features.api_key_switching.key_pool import GeminiKeyPool


def test_method_exists_and_signature():
    assert hasattr(GeminiKeyPool, "generate_structured")
    sig = inspect.signature(GeminiKeyPool.generate_structured)
    params = sig.parameters
    assert "prompt" in params
    assert "response_schema" in params
    assert "model_preference" in params
    assert params["model_preference"].default == "flash-lite"


@pytest.mark.asyncio
async def test_generate_structured_returns_parsed_dict():
    pool = GeminiKeyPool.__new__(GeminiKeyPool)  # bypass __init__ creds check
    fake_response = MagicMock()
    fake_response.text = '{"entities":["a","b"],"authors":["c"]}'
    pool.generate_content = AsyncMock(return_value=(fake_response, "gemini-2.5-flash-lite", 0))

    out = await pool.generate_structured(
        prompt="extract entities",
        response_schema={"type": "object"},
        model_preference="flash-lite",
    )
    assert out == {"entities": ["a", "b"], "authors": ["c"]}
    pool.generate_content.assert_awaited_once()
    call_kwargs = pool.generate_content.await_args.kwargs
    assert call_kwargs["config"]["response_mime_type"] == "application/json"
    assert call_kwargs["config"]["response_schema"] == {"type": "object"}
    assert call_kwargs["starting_model"] == "gemini-2.5-flash-lite"


@pytest.mark.asyncio
async def test_generate_structured_returns_text_on_invalid_json():
    pool = GeminiKeyPool.__new__(GeminiKeyPool)
    fake_response = MagicMock()
    fake_response.text = "not json"
    pool.generate_content = AsyncMock(return_value=(fake_response, "gemini-2.5-flash-lite", 0))

    out = await pool.generate_structured(prompt="x", response_schema={}, model_preference="flash-lite")
    assert out == "not json"


@pytest.mark.asyncio
async def test_generate_structured_returns_empty_on_empty_response():
    pool = GeminiKeyPool.__new__(GeminiKeyPool)
    fake_response = MagicMock()
    fake_response.text = ""
    pool.generate_content = AsyncMock(return_value=(fake_response, "gemini-2.5-flash-lite", 0))

    out = await pool.generate_structured(prompt="x", response_schema={}, model_preference="flash-lite")
    assert out == {}


@pytest.mark.asyncio
async def test_model_preference_mapping():
    pool = GeminiKeyPool.__new__(GeminiKeyPool)
    fake_response = MagicMock()
    fake_response.text = "{}"
    pool.generate_content = AsyncMock(return_value=(fake_response, "gemini-2.5-flash", 0))

    await pool.generate_structured(prompt="x", response_schema={}, model_preference="flash")
    assert pool.generate_content.await_args.kwargs["starting_model"] == "gemini-2.5-flash"

    await pool.generate_structured(prompt="x", response_schema={}, model_preference="pro")
    assert pool.generate_content.await_args.kwargs["starting_model"] == "gemini-2.5-pro"
