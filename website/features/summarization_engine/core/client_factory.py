"""Factory helpers for summarization engine clients."""

from __future__ import annotations

from typing import Any

from website.features.summarization_engine.core.config import EngineConfig
from website.features.summarization_engine.core.gemini_client import TieredGeminiClient


def build_tiered_gemini_client(
    *,
    key_pool: Any | None = None,
    config: EngineConfig | None = None,
) -> TieredGeminiClient:
    """Build a TieredGeminiClient with shared default key-pool/config wiring."""
    if key_pool is None:
        from website.features.api_key_switching import get_key_pool

        key_pool = get_key_pool()
    if config is None:
        from website.features.summarization_engine.core.config import load_config

        config = load_config()
    return TieredGeminiClient(key_pool, config)
