"""Numeric-grounding validator.

Cross-source check: every numeric token in the summary must appear
verbatim in the source (case-insensitive, whitespace-normalized).

This is the single source of truth for numeric-token extraction and
grounding across the codebase. Callers that need stricter behavior
(e.g., the Newsletter intra-summarizer stripper, which must also flag
small bare integers like ``42``) can lower ``min_bare_integer_digits``.
Default is ``3`` for cross-source evaluator use, which matches the
original evaluator semantics (ignore small counts like ``50 offices``
that are common noise).
"""
from __future__ import annotations

import re

# Default minimum digit count for a bare integer to register as a numeric
# token. Evaluator scoring uses 3 (ignore small counts like "50 offices").
# The Newsletter intra-summarizer stripper overrides this to 1 so small
# fabricated counts like "42 teams" are also stripped when unsupported.
_DEFAULT_MIN_BARE_INTEGER_DIGITS = 3

# Patterns that are independent of the bare-integer threshold.
_DOLLAR = re.compile(r"\$\d+[\d.,]*")
_PERCENT = re.compile(r"\d+(?:\.\d+)?%")
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")

_WS = re.compile(r"\s+")


def _bare_int_pattern(min_digits: int) -> re.Pattern[str]:
    # ``\b\d{N,}\b`` — at least ``N`` digits, word-boundary isolated.
    # N==1 matches any bare integer (Newsletter-strict mode).
    return re.compile(rf"\b\d{{{max(1, min_digits)},}}\b")


def _normalize(text: str) -> str:
    return _WS.sub(" ", text).lower().strip()


def extract_numeric_tokens(
    text: str, *, min_bare_integer_digits: int = _DEFAULT_MIN_BARE_INTEGER_DIGITS
) -> list[str]:
    """Extract numeric tokens from ``text``.

    Covered shapes: ``$N``/``$N,NNN.NN`` (currency), ``N%``/``N.N%``
    (percentages), ``YYYY-MM-DD`` (ISO dates), ``19xx``/``20xx`` (years),
    and bare integers with at least ``min_bare_integer_digits`` digits.

    Order is pattern-then-input-order, deduplicated while preserving
    first-seen order.
    """
    if not text:
        return []
    patterns: tuple[re.Pattern[str], ...] = (
        _DOLLAR,
        _PERCENT,
        _ISO_DATE,
        _YEAR,
        _bare_int_pattern(min_bare_integer_digits),
    )
    seen: set[str] = set()
    out: list[str] = []
    for pat in patterns:
        for match in pat.findall(text):
            if match not in seen:
                seen.add(match)
                out.append(match)
    return out


def ground_numeric_claims(
    summary: str,
    source: str,
    *,
    min_bare_integer_digits: int = _DEFAULT_MIN_BARE_INTEGER_DIGITS,
) -> tuple[bool, list[str]]:
    """Classify each numeric token in ``summary`` as grounded or not.

    A token is grounded when its lowercase form appears in the
    whitespace-normalized lowercase ``source``. Returns
    ``(all_grounded, ungrounded_tokens)``.
    """
    tokens = extract_numeric_tokens(
        summary, min_bare_integer_digits=min_bare_integer_digits
    )
    if not tokens:
        return (True, [])
    norm_source = _normalize(source or "")
    ungrounded = [t for t in tokens if t.lower() not in norm_source]
    return (not ungrounded, ungrounded)


def numeric_validator(
    summary: str,
    source: str,
    *,
    threshold: float = 1.0,
    min_bare_integer_digits: int = _DEFAULT_MIN_BARE_INTEGER_DIGITS,
) -> dict:
    tokens = extract_numeric_tokens(
        summary, min_bare_integer_digits=min_bare_integer_digits
    )
    total = len(tokens)
    if total == 0:
        return {"grounded": True, "ungrounded": [], "ratio": 1.0}
    norm_source = _normalize(source or "")
    ungrounded = [t for t in tokens if t.lower() not in norm_source]
    grounded_count = total - len(ungrounded)
    ratio = grounded_count / total
    return {
        "grounded": ratio >= threshold,
        "ungrounded": ungrounded,
        "ratio": ratio,
    }
