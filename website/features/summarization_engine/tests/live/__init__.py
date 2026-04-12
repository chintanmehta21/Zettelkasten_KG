"""Live tests for summarization engine v2.

Run with: python -m pytest website/features/summarization_engine/tests/live --live -q
"""
from __future__ import annotations

import os
from uuid import UUID

import pytest

from website.features.api_key_switching.key_pool import GeminiKeyPool
from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.core.orchestrator import summarize_url


pytestmark = pytest.mark.live


def _keys() -> list[str]:
    if os.environ.get("GEMINI_API_KEYS"):
        return [key.strip() for key in os.environ["GEMINI_API_KEYS"].split(",") if key.strip()]
    if os.environ.get("GEMINI_API_KEY"):
        return [os.environ["GEMINI_API_KEY"]]
    return []


@pytest.mark.asyncio
async def test_live_web_summary_pipeline():
    keys = _keys()
    if not keys:
        pytest.skip("GEMINI_API_KEY or GEMINI_API_KEYS required")
    client = TieredGeminiClient(GeminiKeyPool(keys), load_config())
    result = await summarize_url(
        "https://example.com",
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        gemini_client=client,
    )
    assert result.mini_title
    assert len(result.tags) >= 8
    assert result.metadata.source_type.value == "web"

