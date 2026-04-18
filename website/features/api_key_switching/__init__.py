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
import os
from pathlib import Path

from website.core.settings import get_settings
from website.features.api_key_switching.key_pool import GeminiKeyPool, _load_keys_from_file

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent  # website/features/api_key_switching → project root

_FEATURE_DIR = Path(__file__).parent  # website/features/api_key_switching/

_API_ENV_PATHS = (
    str(_FEATURE_DIR / "api_env"),     # editable file in the feature dir
    str(_PROJECT_ROOT / "api_env"),     # project root (alternative)
    "/etc/secrets/api_env",            # Render Secret File
)

_pool: GeminiKeyPool | None = None


def init_key_pool() -> GeminiKeyPool:
    """Initialize the global key pool.

    Loader priority (first non-empty source wins):
      1. api_env file at one of _API_ENV_PATHS (one key per line)
      2. GEMINI_API_KEYS environment variable (comma-separated list)
      3. settings.gemini_api_key (backward compat with single-key)

    Raises ValueError if no source yields any keys.
    """
    global _pool  # noqa: PLW0603

    # Source 1: api_env file
    for path in _API_ENV_PATHS:
        keys = _load_keys_from_file(path)
        if keys:
            logger.info("Loaded %d Gemini API key(s) from %s", len(keys), path)
            _pool = GeminiKeyPool(keys)
            return _pool

    # Source 2: GEMINI_API_KEYS env var (comma-separated)
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

    # Source 3: backward compat — single key from settings
    settings = get_settings()
    if settings.gemini_api_key.strip():
        logger.info("Using single GEMINI_API_KEY from settings (backward compat)")
        _pool = GeminiKeyPool([settings.gemini_api_key.strip()])
        return _pool

    raise ValueError(
        "No Gemini API keys found. Provide keys via:\n"
        "  1. api_env file (one key per line) in website/features/api_key_switching, project root, or /etc/secrets/api_env\n"
        "  2. GEMINI_API_KEYS environment variable (comma-separated)\n"
        "  3. GEMINI_API_KEY environment variable (single key, legacy)"
    )


def get_key_pool() -> GeminiKeyPool:
    """Return the global key pool singleton.

    Auto-initializes on first call if init_key_pool() hasn't been called.
    """
    global _pool  # noqa: PLW0603
    if _pool is None:
        _pool = init_key_pool()
    return _pool
