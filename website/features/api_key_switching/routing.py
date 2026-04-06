# website/features/api_key_switching/routing.py
"""Content-aware starting model selection.

Routes content to the most appropriate starting model tier based on
content length and source type. This is a suggestion, not a constraint —
the key pool still falls through the full attempt chain on rate limits.
"""

from __future__ import annotations

# Models available in the generative fallback chain.
_BEST_MODEL = "gemini-2.5-flash"
_LITE_MODEL = "gemini-2.5-flash-lite"

# Source types that always warrant the best model.
_COMPLEX_SOURCES = frozenset({"youtube", "newsletter", "github"})

# Content shorter than this (chars) uses the lite model when the source
# type doesn't force the best model.
_SHORT_THRESHOLD = 2000


def select_starting_model(
    content_length: int,
    source_type: str | None = None,
) -> str:
    """Select the starting model based on content characteristics.

    Returns the model name to try first.  The key pool will fall through
    to the other model if this one is rate-limited.
    """
    # Complex sources always get the best model.
    if source_type in _COMPLEX_SOURCES:
        return _BEST_MODEL

    # Long or medium content gets the best model.
    if content_length >= _SHORT_THRESHOLD:
        return _BEST_MODEL

    # Short, non-complex content uses the lite model.
    return _LITE_MODEL
