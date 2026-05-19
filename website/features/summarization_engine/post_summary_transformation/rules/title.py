"""Title text-quality rules (registered into the registry in Task B3).

Conservative + pin-point: title-only. Never reconstructs missing words.
"""
from __future__ import annotations

import re


def trim_to_word_boundary(text: str, max_chars: int) -> str:
    """Trim ``text`` to at most ``max_chars`` WITHOUT cutting mid-word and
    WITHOUT adding an ellipsis. If the whole string already fits, return it
    unchanged. If a single leading token exceeds the cap (pathological), hard
    slice to ``max_chars`` (can't keep a whole word within the cap)."""
    if not isinstance(text, str) or len(text) <= max_chars:
        return text
    window = text[:max_chars]
    if text[max_chars:max_chars + 1].isspace():
        return window.rstrip()
    cut = window.rfind(" ")
    if cut <= 0:
        return window  # one token longer than the cap — hard slice fallback
    return window[:cut].rstrip()
