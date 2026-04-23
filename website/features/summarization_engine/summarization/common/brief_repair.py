"""Shared brief-summary repair primitives used by per-source schema modules.

Each source (YouTube, Reddit, GitHub, Newsletter) has its own domain-specific
rebuild logic in its ``schema.py`` (different structural inputs: chapters vs.
reply_clusters vs. architecture_overview), but the low-level text operations
— splitting sentences, checking terminal punctuation, trimming to a character
or sentence budget, and normalizing fragments into complete sentences — are
identical. This module centralizes those primitives so the per-source repair
flows share a single, tested implementation.

Backward-compatibility: the public function names are chosen to match the
private helpers that previously lived inside each ``schema.py`` module. Each
per-source module keeps its own orchestration function (``_repair_brief_summary``)
but delegates primitives here.
"""
from __future__ import annotations

import re

__all__ = [
    "normalize_whitespace",
    "sentence_split",
    "has_terminal_punct",
    "as_sentence",
    "trim_fragment",
    "clip_to_sentence_window",
    "clip_to_char_budget",
]


_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")
_TERMINAL_PUNCT = (".", "!", "?")


def normalize_whitespace(text: str) -> str:
    """Collapse any run of whitespace into a single space and strip ends."""
    return re.sub(r"\s+", " ", (text or "")).strip()


def sentence_split(text: str) -> list[str]:
    """Split text into stripped, non-empty sentence strings.

    Uses a sentence-terminator lookbehind so the trailing punctuation is
    preserved on each sentence (matches prior Reddit/GitHub behavior).
    Empty/whitespace-only fragments are dropped.
    """
    cleaned = normalize_whitespace(text)
    if not cleaned:
        return []
    return [s.strip() for s in _SENTENCE_BOUNDARY_RE.split(cleaned) if s.strip()]


def has_terminal_punct(text: str) -> bool:
    """True when the last non-whitespace char is '.', '!', or '?'."""
    cleaned = (text or "").strip()
    return bool(cleaned) and cleaned[-1] in _TERMINAL_PUNCT


def as_sentence(text: str) -> str:
    """Return ``text`` trimmed, normalized, and terminated with a period.

    Trailing connector punctuation (",", ";", ":") is stripped before adding
    the period so the result is syntactically well-formed. Empty input
    returns an empty string.
    """
    cleaned = normalize_whitespace(text).rstrip(",;:")
    if not cleaned:
        return ""
    if cleaned.endswith(_TERMINAL_PUNCT):
        return cleaned
    return f"{cleaned}."


def trim_fragment(text: str, max_words: int) -> str:
    """Trim ``text`` to ``max_words`` words, stripping trailing connectors.

    Whitespace is normalized first. If the input has fewer than
    ``max_words`` words the full (normalized, right-stripped) string is
    returned. ``max_words`` must be positive.
    """
    if max_words <= 0:
        return ""
    cleaned = normalize_whitespace(text).rstrip(",;:")
    if not cleaned:
        return ""
    words = re.findall(r"\S+", cleaned)
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(",;:")


def clip_to_sentence_window(
    sentences: list[str],
    *,
    max_sentences: int,
    max_chars: int,
) -> str:
    """Return the first N sentences joined, subject to a char budget.

    The join is space-separated. If the joined result exceeds ``max_chars``
    the function falls back to joining as many whole sentences as fit
    (never splitting mid-sentence). Returns an empty string when there are
    no sentences.
    """
    if not sentences or max_sentences <= 0 or max_chars <= 0:
        return ""
    head = sentences[:max_sentences]
    joined = " ".join(head).strip()
    if len(joined) <= max_chars:
        return joined
    acc: list[str] = []
    for sentence in head:
        candidate = (" ".join([*acc, sentence])).strip()
        if len(candidate) > max_chars:
            break
        acc.append(sentence)
    return " ".join(acc).strip()


def clip_to_char_budget(text: str, *, max_chars: int) -> str:
    """Truncate ``text`` at the last sentence boundary within ``max_chars``.

    Avoids mid-word / mid-clause truncation, which the evaluator flags as a
    truncation issue. If the text already fits, it is returned unchanged.
    If no sentence boundary exists at or after position 200, the raw
    ``text[:max_chars]`` is returned as a last-resort fallback (matches the
    prior GitHub behavior).
    """
    if max_chars <= 0:
        return ""
    cleaned = normalize_whitespace(text)
    if len(cleaned) <= max_chars:
        return cleaned
    window = cleaned[:max_chars]
    last_boundary = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    if last_boundary >= 200:
        return window[: last_boundary + 1]
    return window
