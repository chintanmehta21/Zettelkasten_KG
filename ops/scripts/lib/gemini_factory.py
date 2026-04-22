"""Instantiate a TieredGeminiClient from the same api_env the server uses."""
from __future__ import annotations

import os
from typing import Any

from website.features.api_key_switching.key_pool import (
    GeminiKeyPool,
    _load_keys_from_file,
    candidate_api_env_paths,
)
from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.core.gemini_client import TieredGeminiClient


def make_client() -> TieredGeminiClient:
    keys: list[Any] = []
    for name in ("GEMINI_API_KEY", "GEMINI_API_KEY_1", "GEMINI_API_KEY_2"):
        value = os.environ.get(name)
        if value:
            keys.append((value, "free"))
    env_keys = os.environ.get("GEMINI_API_KEYS")
    if env_keys:
        for raw in env_keys.split(","):
            raw = raw.strip()
            if raw:
                keys.append((raw, "free"))
    if not keys:
        for candidate in candidate_api_env_paths():
            loaded = _load_keys_from_file(str(candidate))
            if loaded:
                keys.extend(loaded)
                break
    if not keys:
        raise RuntimeError(
            "No Gemini API keys found — populate api_env or GEMINI_API_KEY(S)"
        )
    return TieredGeminiClient(GeminiKeyPool(keys), load_config())
