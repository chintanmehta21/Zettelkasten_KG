"""iter-07 Fix D: VAGUE-query gazetteer expansion (no LLM).

When a query is classified VAGUE and contains <=4 content tokens (after
stop-word removal), expand it via a static synonym gazetteer so BM25 can
find lexically distant matches (e.g. "commencement" -> "graduation /
stanford 2005 / valedictory"). The expansion is appended as additional
search variants alongside the original query and HyDE variant; downstream
retrieval logic is unchanged.

This module is intentionally pure-Python + JSON. No new external calls.
"""

from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path

_log = logging.getLogger(__name__)

_GAZETTEER_PATH = Path(__file__).resolve().parent.parent / "assets" / "vague_gazetteer.json"

# Conservative stopword list — only the highest-frequency English function
# words. Keep it small so we don't accidentally strip a content-bearing
# token like "death" or "wiki".
_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "of", "in", "on", "at", "to", "for", "with", "by", "from", "up", "down",
    "and", "or", "but", "if", "while", "as", "into", "through",
    "i", "you", "he", "she", "it", "we", "they", "me", "my", "your",
    "this", "that", "these", "those", "any", "some", "all", "no", "not",
    "do", "does", "did", "have", "has", "had",
    "what", "which", "who", "when", "where", "why", "how",
    "anything", "something", "about",
    "tell", "show", "give", "say", "said",
    "can", "could", "would", "should", "may", "might", "must",
})

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z\-]+")


def _content_tokens(query: str) -> list[str]:
    """Lower-cased content tokens after stop-word removal."""
    if not query:
        return []
    return [
        t.lower()
        for t in _TOKEN_RE.findall(query)
        if t.lower() not in _STOPWORDS and len(t) > 1
    ]


@lru_cache(maxsize=1)
def _load_gazetteer() -> dict[str, list[str]]:
    try:
        with _GAZETTEER_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        _log.warning("vague gazetteer missing at %s", _GAZETTEER_PATH)
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        _log.warning("vague gazetteer load failed: %s", exc)
        return {}
    return {
        k.lower(): list(v)
        for k, v in data.items()
        if not k.startswith("_") and isinstance(v, list)
    }


def is_short_vague(query: str, max_tokens: int = 4) -> bool:
    """True when the query has <= max_tokens content tokens after stop-word strip."""
    return 0 < len(_content_tokens(query)) <= max_tokens


def expand_vague(query: str, *, max_expansions: int = 4) -> list[str]:
    """Return up to ``max_expansions`` gazetteer-derived search variants.

    Pure helper. Empty list when the query is too long, has no matches, or
    the gazetteer is missing. Variants are deterministic, lower-cased, and
    deduped.
    """
    if not os.environ.get("RAG_VAGUE_GAZETTEER_ENABLED", "true").lower() not in (
        "false", "0", "no", "off"
    ):
        # gate disabled
        return []
    enabled = os.environ.get("RAG_VAGUE_GAZETTEER_ENABLED", "true").lower() not in (
        "false", "0", "no", "off"
    )
    if not enabled:
        return []
    if not is_short_vague(query):
        return []
    gaz = _load_gazetteer()
    if not gaz:
        return []
    variants: list[str] = []
    seen: set[str] = set()
    for tok in _content_tokens(query):
        for expansion in gaz.get(tok, ()):
            cleaned = expansion.strip().lower()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                variants.append(cleaned)
                if len(variants) >= max_expansions:
                    return variants
    return variants
