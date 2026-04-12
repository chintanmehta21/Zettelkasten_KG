"""Bridge helpers for the existing Gemini key pool implementation."""

from __future__ import annotations

from functools import lru_cache

from website.features.api_key_switching import get_key_pool


@lru_cache(maxsize=1)
def get_gemini_pool():
    """Return the shared Gemini key-pool singleton."""
    return get_key_pool()


def get_generation_pool():
    """Backward-compatible alias for generation call sites."""
    return get_gemini_pool()


def get_embedding_pool():
    """Backward-compatible alias for embedding call sites."""
    return get_gemini_pool()
