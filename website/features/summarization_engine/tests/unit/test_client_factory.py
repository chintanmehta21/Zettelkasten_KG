"""Tests for summarization engine Gemini client factory."""

from unittest.mock import MagicMock

from website.features.summarization_engine.core.client_factory import (
    build_tiered_gemini_client,
)
from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.core.gemini_client import TieredGeminiClient


def test_build_tiered_gemini_client_uses_supplied_pool_and_config():
    pool = MagicMock()
    config = load_config()

    client = build_tiered_gemini_client(key_pool=pool, config=config)

    assert isinstance(client, TieredGeminiClient)
    assert client._pool is pool
    assert client._config is config
