"""API Key Switching — multi-key rotation for Gemini API.

Usage::

    from website.features.api_key_switching import get_key_pool

    pool = get_key_pool()
    response, model, key_idx = await pool.generate_content(prompt)

Key loading priority (first non-empty source wins):
  1. api_env file at <project_root>/api_env
  2. api_env file at /etc/secrets/api_env
  3. settings.gemini_api_key (backward compat with single key)
"""

from __future__ import annotations

import logging
from pathlib import Path

from telegram_bot.config.settings import get_settings
from website.features.api_key_switching.key_pool import GeminiKeyPool, _load_keys_from_file

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent  # website/features/api_key_switching → project root

_API_ENV_PATHS = [
    str(_PROJECT_ROOT / "api_env"),
    "/etc/secrets/api_env",
]

_pool: GeminiKeyPool | None = None


def init_key_pool() -> GeminiKeyPool:
    """Initialize the global key pool.

    Raises ValueError if no keys found from any source.
    """
    global _pool  # noqa: PLW0603

    # Source 1 & 2: api_env file
    for path in _API_ENV_PATHS:
        keys = _load_keys_from_file(path)
        if keys:
            logger.info("Loaded %d Gemini API key(s) from %s", len(keys), path)
            _pool = GeminiKeyPool(keys)
            return _pool

    # Source 3: backward compat — single key from settings
    settings = get_settings()
    if settings.gemini_api_key.strip():
        logger.info("Using single GEMINI_API_KEY from settings (backward compat)")
        _pool = GeminiKeyPool([settings.gemini_api_key.strip()])
        return _pool

    raise ValueError(
        "No Gemini API keys found. Provide keys via:\n"
        "  1. api_env file (one key per line) at project root or /etc/secrets/api_env\n"
        "  2. GEMINI_API_KEY environment variable"
    )


def get_key_pool() -> GeminiKeyPool:
    """Return the global key pool singleton.

    Auto-initializes on first call if init_key_pool() hasn't been called.
    """
    global _pool  # noqa: PLW0603
    if _pool is None:
        init_key_pool()
    return _pool  # type: ignore[return-value]
