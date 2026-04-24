"""Positive-evidence speaker detection for YouTube captures.

The predecessor module rejected hallucinated speakers (``_is_geographic_entity``)
but relied on the LLM to *propose* candidates. When the model emitted something
like ``"Strait of Hormuz"`` and the transcript echoed the phrase, the reject
list worked but the fallback chain produced the generic ``"The speaker"``.

This module inverts the approach: it **proves** speakers from three independent
signals and only accepts a candidate that scores on ≥2 of them. No new LLM
call — all three signals use data already gathered during extraction.

Signals
    A. Title patterns — "<Name>", "<A> with <B>", "<A> interviews <B>",
       "<Podcast>: <Guest>", "<Name> on <Topic>", etc.
    B. Uploader/channel metadata — yt-dlp ``uploader`` / ``channel``, if it
       looks like a person name rather than an org.
    C. Transcript self-introduction + sustained presence — "I'm X",
       "my name is X", "joining me today is X", with X appearing ≥3 times
       across the transcript and at least once in the first 20% and last 20%.

For non-YouTube sources this module is not used. Reddit uses the post
``author`` (OP). GitHub uses ``owner.login``. Newsletter uses the byline
author. These identity fields come from the source API and need no heuristic.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable


_CAPITALIZED_NAME = re.compile(
    r"\b([A-Z][a-z]+(?:\s+(?:van|de|del|da|di|von|le|la|du|bin|ibn|al|el))?(?:\s+[A-Z][a-z]+){1,2})\b"
)

_TITLE_PATTERNS = [
    # "A with B", "A and B", "A & B"
    re.compile(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s+(?:with|and|&|x)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})"),
    # "A interviews B"
    re.compile(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s+interviews\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})"),
    # "A on <Topic>"
    re.compile(r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s+on\s+"),
    # "<Podcast>: <Guest>" or "- <Guest>"
    re.compile(r"[:—\-]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s*$"),
]

_SELF_INTRO = re.compile(
    r"(?:I'?m|I am|my name is|this is|you're watching .*?,?\s*I'?m|welcome to [^,]+,\s*I'?m)\s+"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})",
    re.IGNORECASE,
)
_GUEST_INTRO = re.compile(
    r"(?:joining me (?:today|now)|today (?:we have|I'?m joined by|our guest is)|please welcome)\s+"
    r"(?:is\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})",
    re.IGNORECASE,
)

_ORG_MARKERS = (
    "inc", "inc.", "llc", "ltd", "tv", "media", "network", "official",
    "channel", "studios", "productions", "entertainment", "news", "magazine",
    "press", "radio", "podcast",
)

_ORG_TOKENS = {"ted", "cnn", "bbc", "nbc", "abc", "pbs", "mit", "stanford",
               "youtube", "netflix", "hbo", "wwe", "ufc", "fifa", "uefa"}


def _looks_like_person(name: str) -> bool:
    """Heuristic: 2–3 capitalized tokens, no org marker, not all-caps, not a single word."""
    cleaned = (name or "").strip()
    if not cleaned or len(cleaned) < 3:
        return False
    tokens = cleaned.split()
    if len(tokens) < 2 or len(tokens) > 4:
        return False
    if all(t.isupper() for t in tokens):
        return False
    lower_tokens = [t.lower().strip(".,") for t in tokens]
    if any(t in _ORG_MARKERS for t in lower_tokens):
        return False
    if any(t in _ORG_TOKENS for t in lower_tokens):
        return False
    capitalized = sum(1 for t in tokens if t[:1].isupper())
    return capitalized >= 2


def _candidates_from_title(title: str) -> list[str]:
    if not title:
        return []
    out: list[str] = []
    for pat in _TITLE_PATTERNS:
        for m in pat.finditer(title):
            for g in m.groups():
                if g and _looks_like_person(g):
                    out.append(g.strip())
    # Free-form capitalized name as fallback
    for m in _CAPITALIZED_NAME.finditer(title):
        name = m.group(1)
        if _looks_like_person(name):
            out.append(name.strip())
    return _dedupe_ordered(out)


def _candidate_from_uploader(uploader: str | None) -> str | None:
    if not uploader:
        return None
    cleaned = uploader.strip()
    # Strip common channel suffixes
    for suffix in (" Official", " - Topic", " TV", " Media", " Network", " Channel"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].strip()
    return cleaned if _looks_like_person(cleaned) else None


def _candidates_from_transcript(transcript: str) -> list[tuple[str, str]]:
    """Return ``[(name, role)]`` where role is ``"host"`` or ``"guest"``."""
    if not transcript:
        return []
    out: list[tuple[str, str]] = []
    for m in _SELF_INTRO.finditer(transcript):
        name = m.group(1)
        if _looks_like_person(name):
            out.append((name.strip(), "host"))
    for m in _GUEST_INTRO.finditer(transcript):
        name = m.group(1)
        if _looks_like_person(name):
            out.append((name.strip(), "guest"))
    # Dedupe preserving first role seen
    seen: dict[str, str] = {}
    for name, role in out:
        seen.setdefault(name, role)
    return [(n, r) for n, r in seen.items()]


def _has_sustained_presence(name: str, transcript: str) -> bool:
    """Require ≥3 mentions AND at least one mention in the first and last
    20% of the transcript. Proxy for "speaks throughout most of the video"
    without running diarization.
    """
    if not name or not transcript:
        return False
    lowered = transcript.lower()
    name_l = name.lower()
    mentions = [i for i in _find_all(lowered, name_l)]
    if len(mentions) < 3:
        return False
    length = len(lowered)
    first_cutoff = int(length * 0.2)
    last_cutoff = int(length * 0.8)
    has_early = any(m < first_cutoff for m in mentions)
    has_late = any(m > last_cutoff for m in mentions)
    return has_early and has_late


def _find_all(haystack: str, needle: str) -> Iterable[int]:
    start = 0
    while True:
        i = haystack.find(needle, start)
        if i == -1:
            return
        yield i
        start = i + max(1, len(needle))


def _dedupe_ordered(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        k = x.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


def detect_youtube_speakers(
    *,
    title: str,
    uploader: str | None,
    transcript: str,
) -> list[str]:
    """Return a list of confirmed speakers, or ``["The speaker"]`` if none.

    Acceptance rule: each candidate needs evidence from ≥2 of
    {title, uploader, transcript}. Sustained-presence check is applied to
    transcript-derived candidates. Multiple speakers allowed (podcasts).
    """
    title_candidates = _candidates_from_title(title or "")
    uploader_candidate = _candidate_from_uploader(uploader)
    transcript_candidates = _candidates_from_transcript(transcript or "")

    # Build score map: candidate → set of signals
    scores: dict[str, set[str]] = {}
    for c in title_candidates:
        scores.setdefault(c.lower(), set()).add("title")
    if uploader_candidate:
        scores.setdefault(uploader_candidate.lower(), set()).add("uploader")
    for name, _role in transcript_candidates:
        if _has_sustained_presence(name, transcript or ""):
            scores.setdefault(name.lower(), set()).add("transcript")

    # Normalize casing: prefer the longest original form seen across sources
    casing: dict[str, str] = {}
    for src_list in (title_candidates, [uploader_candidate] if uploader_candidate else [],
                     [n for n, _ in transcript_candidates]):
        for original in src_list:
            if not original:
                continue
            k = original.lower()
            if k not in casing or len(original) > len(casing[k]):
                casing[k] = original

    confirmed = [casing[k] for k, sigs in scores.items() if len(sigs) >= 2]

    # If uploader looks like a person and transcript confirms sustained
    # presence, that's also 2 signals even without title match.
    # (already captured above via scores logic)

    # Single-candidate fallback: if exactly one candidate has a transcript
    # self-intro hit AND sustained presence, accept it as sole speaker even
    # without title/uploader corroboration — the model's own words are
    # stronger than the geographic-phrase false positives we're guarding
    # against.
    if not confirmed:
        for name, role in transcript_candidates:
            if role == "host" and _has_sustained_presence(name, transcript or ""):
                confirmed.append(casing.get(name.lower(), name))
                break

    if not confirmed:
        return ["The speaker"]
    return _dedupe_ordered(confirmed)


__all__ = ["detect_youtube_speakers"]
