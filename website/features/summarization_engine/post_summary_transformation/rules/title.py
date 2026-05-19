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


# A token we must never recase: subreddit/repo prefix, pure acronym (FT, US,
# APIs), camelCase / mixed-cap brand (GitHub, iOS, arXiv), or anything that
# already starts uppercase.
_PREFIX_RE = re.compile(r"^(r/[^\s]+|[^/\s]+/[^/\s]+)$")
_ACRONYM_RE = re.compile(r"^[A-Z0-9]{2,}s?$")
_CAMEL_RE = re.compile(r"[a-z][A-Z]|^[a-z]+[A-Z]")


def _is_preserved(tok: str) -> bool:
    if not tok:
        return True
    if _PREFIX_RE.match(tok):
        return True
    if _ACRONYM_RE.match(tok):
        return True
    if _CAMEL_RE.search(tok):
        return True
    return tok[0].isupper()  # already capitalized — leave intact


def capitalize_title(title: str) -> str:
    """Capitalize ONLY the first *content* word (the first token that is not a
    r/<sub> or owner/repo prefix). Preserve acronyms, camelCase/brands, the
    prefix, and any already-capitalized token. Interior words untouched.
    Idempotent. Never reconstructs/inserts/removes words."""
    if not isinstance(title, str) or not title.strip():
        return title
    tokens = title.split(" ")
    for i, tok in enumerate(tokens):
        if tok == "":
            continue
        if _PREFIX_RE.match(tok):
            continue  # skip the prefix, keep scanning for first content word
        if _is_preserved(tok):
            return title  # first content word already fine — change nothing
        tokens[i] = tok[0].upper() + tok[1:]
        return " ".join(tokens)
    return title


from website.features.summarization_engine.post_summary_transformation import registry as _reg  # noqa: E402

_reg.register(source_type=None, field_kind="title")(capitalize_title)
