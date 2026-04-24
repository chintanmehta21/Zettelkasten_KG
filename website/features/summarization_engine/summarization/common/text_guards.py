"""Shared text-integrity helpers for source composers.

These guards prevent the class of regression observed in YouTube iter-08
where the ``closing_takeaway`` emitted ``"The main takeaway is DMT is a
powerful."`` — a grammatically truncated sentence ending in a dangling
adjective + terminal period. The helpers here are deliberately narrow:
they do NOT invent new prose; they either repair the tail with a neutral
continuation or drop the sentence entirely when repair is not possible.
"""
from __future__ import annotations

import re

_DANGLING_TAIL_WORDS = frozenset(
    {
        # conjunctions / prepositions
        "and", "or", "but", "nor", "so", "yet", "for", "as", "because",
        "with", "of", "to", "in", "on", "by", "from", "into", "at", "over",
        "under", "upon", "via", "through", "between", "during", "without",
        "within", "across", "toward", "towards",
        # articles / determiners
        "a", "an", "the", "this", "that", "these", "those",
        # linking verbs / modals (only dangerous when terminal)
        "is", "are", "was", "were", "be", "been", "being",
        "has", "have", "had", "having",
        "will", "would", "can", "could", "should", "shall", "may", "might",
        "must", "do", "does", "did",
        # relatives / interrogatives
        "which", "that", "who", "whom", "whose", "where", "when", "while",
        # common adjective scaffolds that only make sense before a noun
        "such", "some", "many", "most", "few", "more", "less",
        "powerful", "strong", "major", "key", "main", "important",
    }
)

_TERMINAL_PUNCT = ".!?"


def clean_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


# Abbreviations that MUST NOT terminate a sentence even when followed by
# whitespace + capital letter. Matched case-insensitively. Any period
# inside these tokens (e.g. "U.S.") is elided before the raw split so
# downstream punctuation-aware regexes never see them as sentence ends.
#
# Rationale (iter-20 regression): YouTube brief summaries contained
# ``"implications for U.S. global dominance."`` which the naive
# ``re.split(r"(?<=[.!?])\s+", ...)`` splitter turned into three
# fragments (``"implications for U."``, ``"S."``, ``"global..."``).
# That fed truncated fragments into the overview bullet and the
# brief-repair sanity checks, producing the user-visible bug
# ``"This lecture explores... implications for U."``.
_ABBREVIATIONS = (
    # Country / region codes
    "U.S.A.", "U.S.S.R.", "U.S.", "U.K.", "U.N.", "E.U.",
    # Titles / honorifics
    "Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "Sr.", "Jr.", "St.",
    # Common Latin / business abbreviations
    "etc.", "e.g.", "i.e.", "vs.", "No.", "Inc.", "Ltd.", "Co.", "Corp.",
)
# Sort longest-first so "U.S.A." matches before "U.S." during substitution.
_ABBR_SORTED = tuple(sorted(_ABBREVIATIONS, key=len, reverse=True))
_ABBR_SENTINEL = "\x00"  # never appears in LLM output


def _protect_abbreviations(text: str) -> str:
    """Replace every period inside a known abbreviation with a sentinel.

    Does a case-insensitive literal scan to preserve the original casing
    of the text. Also collapses single-letter ALLCAPS runs like ``A.I.``
    so that a period between two single uppercase letters is never treated
    as a sentence boundary.
    """
    if not text:
        return text
    protected = text
    # Case-insensitive literal replacement of each abbreviation. We build
    # one alternation regex; the sub swaps '.' inside the match for the
    # sentinel byte.
    pattern = re.compile(
        "(" + "|".join(re.escape(a) for a in _ABBR_SORTED) + ")",
        re.IGNORECASE,
    )
    protected = pattern.sub(
        lambda m: m.group(0).replace(".", _ABBR_SENTINEL),
        protected,
    )
    # Generic guard: single-letter-dot-single-letter sequences like
    # "A.I." or "J.F.K.".
    protected = re.sub(
        r"\b([A-Za-z])\.(?=[A-Za-z]\.)",
        r"\1" + _ABBR_SENTINEL,
        protected,
    )
    protected = re.sub(
        r"\b([A-Za-z])\.(?=[A-Za-z])",
        r"\1" + _ABBR_SENTINEL,
        protected,
    )
    # Numeric decimals: "3.14", "1.5x" — the period is not a boundary.
    protected = re.sub(r"(\d)\.(?=\d)", r"\1" + _ABBR_SENTINEL, protected)
    return protected


def _restore_abbreviations(text: str) -> str:
    return text.replace(_ABBR_SENTINEL, ".") if text else text


def split_sentences(text: str) -> list[str]:
    """Split ``text`` into sentences without breaking on abbreviations.

    Handles U.S., Dr., e.g., 3.14, A.I. and a handful of other common
    cases listed in ``_ABBREVIATIONS``. Also refuses to break when a
    period is followed by a lowercase letter — that is never a sentence
    boundary in well-formed prose.
    """
    cleaned = clean_whitespace(text)
    if not cleaned:
        return []
    protected = _protect_abbreviations(cleaned)
    # Split on terminal punctuation followed by whitespace AND an
    # uppercase letter / digit / quote. A period before a lowercase
    # letter (``"3. option"`` in a list, or an abbreviation we missed)
    # stays intact.
    raw = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'\u201c\u2018(\[])", protected)
    return [_restore_abbreviations(s).strip() for s in raw if s and s.strip()]


def ensure_terminator(text: str) -> str:
    """Ensure text ends with a terminal punctuation mark."""
    cleaned = clean_whitespace(text).rstrip(",;:")
    if not cleaned:
        return ""
    if cleaned.endswith(tuple(_TERMINAL_PUNCT)):
        return cleaned
    return f"{cleaned}."


def ends_with_dangling_word(text: str) -> bool:
    """Return True if the final word (before terminator) is a dangling connector.

    Detects the iter-08 class of bug: ``"The main takeaway is DMT is a powerful."``
    — the terminal word ``powerful`` is an adjective scaffold that requires a
    following noun. Also catches prepositions (``"driven by the."``),
    linking verbs (``"the core claim is."``), and articles.
    """
    cleaned = clean_whitespace(text).rstrip(_TERMINAL_PUNCT).rstrip(",;:").strip()
    if not cleaned:
        return False
    match = re.search(r"([A-Za-z][A-Za-z'-]*)$", cleaned)
    if not match:
        return False
    last = match.group(1).lower()
    return last in _DANGLING_TAIL_WORDS


def repair_or_drop(text: str) -> str:
    """Return a safe version of ``text`` or an empty string.

    Strategy:
      1. Normalize whitespace + terminator.
      2. If the sentence ends in a dangling connector, walk backwards to
         the previous sentence boundary and return the prior sentence. If
         there is none, return ''.
      3. Otherwise return the sentence with a terminator.
    """
    cleaned = clean_whitespace(text)
    if not cleaned:
        return ""
    terminated = ensure_terminator(cleaned)
    if not ends_with_dangling_word(terminated):
        return terminated

    sentences = split_sentences(terminated)
    while sentences and ends_with_dangling_word(sentences[-1]):
        sentences.pop()
    if not sentences:
        return ""
    return " ".join(sentences)


def sanitize_bullets(bullets: list[str]) -> list[str]:
    """Apply repair_or_drop to every bullet, removing drops."""
    out: list[str] = []
    for bullet in bullets or []:
        safe = repair_or_drop(bullet)
        if safe:
            out.append(safe)
    return out


def sanitize_sub_sections(sub_sections: dict[str, list[str]]) -> dict[str, list[str]]:
    """Apply repair_or_drop to every bullet in every sub-section."""
    out: dict[str, list[str]] = {}
    for heading, bullets in (sub_sections or {}).items():
        safe_bullets = sanitize_bullets(bullets)
        if safe_bullets:
            out[heading] = safe_bullets
    return out
