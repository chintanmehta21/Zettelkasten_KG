"""In-house deterministic grammar polish for summary envelopes.

Pure regex + dictionary passes. No LLM calls. Safe to run repeatedly
(idempotent).  Hooked from ``summary_normalizer.normalize_summary_for_wire``
so every ``/api/graph`` response is polished at the wire boundary.

Stack of passes (in order, applied to every text fragment):
1. Caveat / pipeline-metadata stripping
2. Apostrophe restoration / curly-quote normalization
3. Comma after sentence-leading adverbial phrases ("Along the way, ...")
4. Comma outside closing quote ("foo,'" -> "foo',")
5. Whitespace collapsing
6. Sentence-final punctuation cleanup ("..", ",.", " .")
7. Article / word duplication ("the the" -> "the")
8. Trailing dangling preposition ("...with the.") -> drop dangler
"""
from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Pass 1 — pipeline-metadata caveat stripping
# ---------------------------------------------------------------------------

# Anything starting with "Caveat:", "Note to ingester:", "Pipeline note:",
# "Moderation context:", or "Note:" followed by a metric / divergence number
# is internal pipeline chatter, never user-facing prose.
_CAVEAT_PREFIX_RE = re.compile(
    r"(?ix)"
    r"(?:^|(?<=[.!?]\s)|(?<=[.!?]\"\s)|(?<=[.!?]'\s))"
    r"(?:Caveat|Note\s+to\s+ingester|Pipeline\s+note|Moderation\s+context|"
    r"Ingest\s+note|Ingestion\s+note)"
    r"\s*:\s*[^.!?]*[.!?]?"
)

_NOTE_WITH_METRICS_RE = re.compile(
    r"(?ix)"
    r"(?:^|(?<=[.!?]\s))"
    r"Note\s*:\s*[^.!?]*?\d[^.!?]*?[.!?]"
)

# Whole-bullet caveats (when a list item is just metadata).
_FULL_CAVEAT_LINE_RE = re.compile(
    r"(?i)^\s*(?:Caveat|Note\s+to\s+ingester|Pipeline\s+note|Moderation\s+context|"
    r"Ingest\s+note|Ingestion\s+note)\s*:.*$"
)


def strip_caveats(text: str) -> str:
    if not text:
        return text
    out = _CAVEAT_PREFIX_RE.sub(" ", text)
    out = _NOTE_WITH_METRICS_RE.sub(" ", out)
    return re.sub(r"\s{2,}", " ", out).strip()


def is_caveat_only_line(text: str) -> bool:
    """Return True if the text is *entirely* a caveat / pipeline note."""
    if not text:
        return False
    return bool(_FULL_CAVEAT_LINE_RE.match(text.strip()))


# ---------------------------------------------------------------------------
# Pass 2 — apostrophe / quote normalization
# ---------------------------------------------------------------------------

_CURLY_APOST = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
}
_CURLY_QUOTE = {
    "“": '"',
    "”": '"',
    "„": '"',
    "‟": '"',
}

# "Karpathy s LLM" -> "Karpathy's LLM" (proper-noun possessive lost apostrophe).
# Conditions: leading word starts with uppercase OR is >3 chars, ends in a
# non-``s`` letter; the ``s`` is a standalone token; trailing word starts with
# a letter (so we don't grab numbers / punctuation).
_LOST_POSSESSIVE_RE = re.compile(
    r"\b([A-Z][A-Za-z]{1,}|[a-z]{4,})([^A-Za-z'])s(\s)([A-Za-z])"
)


def _normalize_quotes(text: str) -> str:
    if not text:
        return text
    out = text
    for k, v in _CURLY_APOST.items():
        out = out.replace(k, v)
    for k, v in _CURLY_QUOTE.items():
        out = out.replace(k, v)
    return out


def _restore_lost_possessives(text: str) -> str:
    if not text or " s " not in text.lower():
        return text

    def repl(m: re.Match[str]) -> str:
        head = m.group(1)
        sep = m.group(2)
        # Only fix when separator is a single space — otherwise leave alone.
        if sep != " ":
            return m.group(0)
        # Skip when head ends in 's' (would create "ss's").
        if head.endswith("s") or head.endswith("S"):
            return m.group(0)
        return f"{head}'s {m.group(4)}"

    return _LOST_POSSESSIVE_RE.sub(repl, text)


def normalize_apostrophes(text: str) -> str:
    return _restore_lost_possessives(_normalize_quotes(text))


# ---------------------------------------------------------------------------
# Pass 3 — comma after sentence-leading adverbial phrase
# ---------------------------------------------------------------------------

_ADVERBIAL_LEADS = (
    "In fact",
    "However",
    "Meanwhile",
    "Recently",
    "Eventually",
    "Nevertheless",
    "Therefore",
    "Furthermore",
    "Additionally",
    "Importantly",
    "Notably",
    "Along the way",
    "At the same time",
    "For example",
    "For instance",
    "On the other hand",
    "In contrast",
    "Of course",
    "Indeed",
    "Moreover",
    "Specifically",
    "Crucially",
    "First",
    "Second",
    "Third",
    "Finally",
)

_ADVERBIAL_RE = re.compile(
    r"(^|(?<=[.!?]\s)|(?<=[.!?]\"\s)|(?<=[.!?]'\s))"
    r"(" + "|".join(re.escape(p) for p in _ADVERBIAL_LEADS) + r")"
    r"\s+([A-Z])"
)


def comma_after_adverbial(text: str) -> str:
    if not text:
        return text
    return _ADVERBIAL_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}, {m.group(3)}", text)


# ---------------------------------------------------------------------------
# Pass 4 — comma outside the closing quote
# ---------------------------------------------------------------------------

# 'product-minded engineers,' -> 'product-minded engineers',
# Apply for both straight ' and " (curly already normalized in pass 2).
_COMMA_INSIDE_QUOTE_RE = re.compile(r"([,;:])(['\"])")


def comma_outside_quote(text: str) -> str:
    if not text:
        return text

    def repl(m: re.Match[str]) -> str:
        punct, quote = m.group(1), m.group(2)
        return f"{quote}{punct}"

    # Only flip when the quote character actually closes a quoted span.
    # Heuristic: a preceding open quote of the same kind exists earlier
    # in the same sentence.  Without true parsing this is good enough —
    # we run only when ``,'`` or ``,"`` appears after an alphanumeric
    # (so we don't touch ``foo,'bar`` style code).
    out_chars: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in ",;:" and i + 1 < n and text[i + 1] in ("'", '"'):
            quote = text[i + 1]
            # Look back for matching open quote in same sentence/paragraph
            j = i - 1
            sentence_start = max(
                text.rfind(". ", 0, i),
                text.rfind("! ", 0, i),
                text.rfind("? ", 0, i),
                text.rfind("\n", 0, i),
            )
            if sentence_start < 0:
                sentence_start = 0
            window = text[sentence_start:i]
            # Count only standalone instances of the quote in the window.
            # A ``'`` whose previous char is a letter (e.g. ``Hoskins'``,
            # ``don't``, ``O'Reilly``) is a possessive / contraction, not a
            # quote delimiter — skip it regardless of what follows. Opening
            # quotes are always preceded by whitespace / start-of-string /
            # punctuation, never by a letter.
            qcount = 0
            for k in range(len(window)):
                if window[k] != quote:
                    continue
                prev_c = window[k - 1] if k - 1 >= 0 else ""
                if quote == "'" and prev_c.isalpha():
                    continue
                qcount += 1
            if qcount % 2 == 1 and i > 0 and text[i - 1].isalnum():
                # Flip
                out_chars.append(quote)
                out_chars.append(ch)
                i += 2
                continue
        out_chars.append(ch)
        i += 1
    return "".join(out_chars)


# ---------------------------------------------------------------------------
# Pass 5 — whitespace
# ---------------------------------------------------------------------------

def collapse_whitespace(text: str) -> str:
    if not text:
        return text
    return re.sub(r"[ \t]{2,}", " ", text).strip()


# ---------------------------------------------------------------------------
# Pass 6 — sentence-final punctuation
# ---------------------------------------------------------------------------

def fix_sentence_punctuation(text: str) -> str:
    if not text:
        return text
    out = re.sub(r"\.{2,}", ".", text)
    out = re.sub(r",\.", ".", out)
    out = re.sub(r"\s+\.", ".", out)
    out = re.sub(r"\s+,", ",", out)
    out = re.sub(r"\s+;", ";", out)
    out = re.sub(r"\s+:", ":", out)
    return out


# ---------------------------------------------------------------------------
# Pass 7 — duplicated articles / common short words
# ---------------------------------------------------------------------------

_DUP_WORDS = ("the", "a", "an", "is", "to", "of", "and", "in", "on", "for")
_DUP_RE = re.compile(
    r"\b(" + "|".join(_DUP_WORDS) + r")\s+\1\b",
    re.IGNORECASE,
)


def dedupe_articles(text: str) -> str:
    if not text:
        return text
    return _DUP_RE.sub(lambda m: m.group(1), text)


# ---------------------------------------------------------------------------
# Pass 8 — trailing dangling preposition
# ---------------------------------------------------------------------------

_DANGLING_RE = re.compile(
    r"\s+\b(in|the|a|an|of|to|with|for|on|as|and|but)\b\.\s*$",
    re.IGNORECASE,
)


def strip_dangling_preposition(text: str) -> str:
    if not text:
        return text
    return _DANGLING_RE.sub(".", text).rstrip()


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def polish(text: str) -> str:
    """Run the full deterministic polish stack on a single text fragment."""
    if not isinstance(text, str) or not text:
        return text or ""
    out = strip_caveats(text)
    out = normalize_apostrophes(out)
    out = comma_after_adverbial(out)
    out = comma_outside_quote(out)
    out = collapse_whitespace(out)
    out = fix_sentence_punctuation(out)
    out = dedupe_articles(out)
    out = strip_dangling_preposition(out)
    return out


def _polish_list(items: Any) -> Any:
    if not isinstance(items, list):
        return items
    out: list[Any] = []
    for it in items:
        if isinstance(it, str):
            if is_caveat_only_line(it):
                continue
            polished = polish(it)
            if polished:
                out.append(polished)
        else:
            out.append(_polish_value(it))
    return out


def _polish_value(value: Any) -> Any:
    if isinstance(value, str):
        return polish(value)
    if isinstance(value, list):
        return _polish_list(value)
    if isinstance(value, dict):
        return {k: _polish_value(v) for k, v in value.items()}
    return value


def polish_envelope(envelope: dict) -> dict:
    """Walk a canonical summary envelope and polish every text leaf.

    Mutates a copy — the input is not modified.  Strips caveat-only bullets
    from any ``bullets`` list under ``detailed_summary``.
    """
    if not isinstance(envelope, dict):
        return envelope
    out: dict[str, Any] = dict(envelope)
    if "mini_title" in out:
        out["mini_title"] = polish(out.get("mini_title") or "")
    if "brief_summary" in out:
        out["brief_summary"] = polish(out.get("brief_summary") or "")
    if "closing_remarks" in out:
        out["closing_remarks"] = polish(out.get("closing_remarks") or "")
    detailed = out.get("detailed_summary")
    if isinstance(detailed, list):
        out["detailed_summary"] = [_polish_section(s) for s in detailed]
    return out


def _polish_section(section: Any) -> Any:
    if not isinstance(section, dict):
        return section
    out: dict[str, Any] = dict(section)
    if "heading" in out and isinstance(out["heading"], str):
        out["heading"] = polish(out["heading"])
    if "bullets" in out and isinstance(out["bullets"], list):
        cleaned: list[str] = []
        for b in out["bullets"]:
            if isinstance(b, str):
                if is_caveat_only_line(b):
                    continue
                p = polish(b)
                if p:
                    cleaned.append(p)
            else:
                cleaned.append(b)
        out["bullets"] = cleaned
    if "sub_sections" in out and isinstance(out["sub_sections"], dict):
        new_subs: dict[str, Any] = {}
        for k, v in out["sub_sections"].items():
            if isinstance(v, list):
                sub_cleaned: list[str] = []
                for it in v:
                    if isinstance(it, str):
                        if is_caveat_only_line(it):
                            continue
                        p = polish(it)
                        if p:
                            sub_cleaned.append(p)
                    else:
                        sub_cleaned.append(it)
                new_subs[polish(k) if isinstance(k, str) else k] = sub_cleaned
            else:
                new_subs[polish(k) if isinstance(k, str) else k] = _polish_value(v)
        out["sub_sections"] = new_subs
    return out


# ---------------------------------------------------------------------------
# Tag rewrites (Reddit r-foo -> r/foo)
# ---------------------------------------------------------------------------

_REDDIT_TAG_RE = re.compile(r"^r-([a-z0-9_]+)$", re.IGNORECASE)


def rewrite_reddit_tag(tag: str) -> str:
    """Rewrite ``r-foo`` to ``r/foo`` for display.  Idempotent."""
    if not isinstance(tag, str):
        return tag
    m = _REDDIT_TAG_RE.match(tag.strip())
    if not m:
        return tag
    return f"r/{m.group(1).lower()}"


def rewrite_tags(tags: Any) -> Any:
    if not isinstance(tags, list):
        return tags
    return [rewrite_reddit_tag(t) if isinstance(t, str) else t for t in tags]
