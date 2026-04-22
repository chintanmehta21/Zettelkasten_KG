"""API key switching for Gemini with multi-source key discovery."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from website.core.settings import get_settings
from website.features.api_key_switching.key_pool import (
    GeminiKeyPool,
    _load_keys_from_file,
    candidate_api_env_paths,
)

logger = logging.getLogger(__name__)

_API_ENV_PATHS = tuple(str(path) for path in candidate_api_env_paths(Path(__file__)))

_pool: GeminiKeyPool | None = None


def init_key_pool() -> GeminiKeyPool:
    """Initialize the global key pool singleton."""
    global _pool  # noqa: PLW0603

    for path in _API_ENV_PATHS:
        keys = _load_keys_from_file(path)
        if keys:
            logger.info("Loaded %d Gemini API key(s) from %s", len(keys), path)
            _pool = GeminiKeyPool(keys)
            return _pool

    env_csv = os.environ.get("GEMINI_API_KEYS", "").strip()
    if env_csv:
        env_keys = [key.strip() for key in env_csv.split(",") if key.strip()]
        if env_keys:
            logger.info(
                "Loaded %d Gemini API key(s) from GEMINI_API_KEYS env var",
                len(env_keys),
            )
            _pool = GeminiKeyPool(env_keys)
            return _pool

    settings = get_settings()
    if settings.gemini_api_key.strip():
        logger.info("Using single GEMINI_API_KEY from settings")
        _pool = GeminiKeyPool([settings.gemini_api_key.strip()])
        return _pool

    raise ValueError(
        "No Gemini API keys found. Provide keys via api_env, GEMINI_API_KEYS, "
        "or GEMINI_API_KEY."
    )


def get_key_pool() -> GeminiKeyPool:
    """Return the global key pool, creating it on first access."""
    global _pool  # noqa: PLW0603
    if _pool is None:
        _pool = init_key_pool()
    return _pool
