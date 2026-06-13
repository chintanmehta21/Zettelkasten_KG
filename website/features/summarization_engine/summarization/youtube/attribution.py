"""Confidence-gated, idempotent, format-verb-aware lead-sentence composition
for YouTube briefs (Wave 1B). Pure + deterministic — NO model call.

Three defects this module fixes in youtube/schema.py::_compose_structured_brief:
  1. DOUBLING — prepended "{speaker} argues that {thesis}" with no idempotence
     guard, so a thesis already opening with an attribution clause doubled it.
  2. FABRICATED SUBJECT — "The speaker" was injected as a grammatical subject
     even when attribution_confidence == "missing" (no source supported it).
  3. FIXED VERB — always "argues", over-attributing stance for non-argumentative
     formats (La Trobe stance taxonomy; AnthroScore arXiv:2402.02056).
"""
from __future__ import annotations

import re
import unicodedata

from website.features.summarization_engine.summarization.youtube.schema import (
    _is_geographic_entity,
    _is_non_human_speaker_entity,
    _is_placeholder_speaker,
)

_SENTINEL_SPEAKER = "the speaker"


def reconcile_attribution_confidence(speakers: list[str]) -> str:
    """Derive attribution_confidence ('high'|'low'|'missing') from a speaker list.

    Single source of truth reused by the schema validator AND the
    speaker_detector override seam (summarizer.py) so the two can never desync.
    MUST be called on the ORIGINAL (pre-filter/pre-coercion) speaker list so
    placeholder-presence is preserved. Mirrors _sanitize_speakers's usable-name
    filter exactly (placeholder / geographic / non-human-entity / sentinel):
      - any usable name present: 'high' if NO unusable token was also present,
        else 'low' (mixed real + placeholder/entity)
      - no usable name at all: 'missing' (all placeholder, or coerced-from-entity)
    """
    cleaned = [s.strip() for s in (speakers or []) if isinstance(s, str) and s.strip()]
    real = [
        s for s in cleaned
        if not _is_placeholder_speaker(s)
        and not _is_geographic_entity(s)
        and not _is_non_human_speaker_entity(s)
        and s.lower() != _SENTINEL_SPEAKER
    ]
    if not real:
        return "missing"
    had_unusable = any(
        _is_placeholder_speaker(s)
        or _is_geographic_entity(s)
        or _is_non_human_speaker_entity(s)
        or s.lower() == _SENTINEL_SPEAKER
        for s in cleaned
    )
    return "low" if had_unusable else "high"


# Wave 1B: fold BOTH the YouTubeDetailedPayload.format Literal AND
# format_classifier.FORMAT_LABELS onto one closed key set the verb map covers.
# validate_assignment is OFF, so classifier labels (documentary/explainer) leak
# into detailed_summary.format unvalidated — without this fold the verb map
# would silently miss them. Keys: lecture|explainer|commentary|documentary|
# news|interview|unknown.
_FORMAT_FOLD: dict[str, str] = {
    "lecture": "lecture", "talk": "lecture",
    "explainer": "explainer", "tutorial": "explainer", "walkthrough": "explainer",
    "how-to": "explainer", "howto": "explainer", "demo": "explainer", "guide": "explainer",
    "commentary": "commentary", "opinion": "commentary", "essay": "commentary",
    "review": "commentary", "reaction": "commentary", "debate": "commentary", "vlog": "commentary",
    "documentary": "documentary", "docuseries": "documentary",
    "news": "news", "report": "news", "recap": "news",
    "interview": "interview", "discussion": "interview", "podcast": "interview",
    "q&a": "interview", "conversation": "interview",
}
_CANONICAL_KEYS = frozenset(_FORMAT_FOLD.values()) | {"unknown"}


def canonical_format(label: str | None) -> str:
    """Fold any Literal/classifier format label to a canonical verb-map key.

    Unrecognised / empty / "other" -> "unknown" (agentless framing, no guessed
    verb). Closed mapping: the verb map can never miss.
    """
    return _FORMAT_FOLD.get((label or "").strip().lower(), "unknown")


# Wave 1B: reporting-verb stance taxonomy (La Trobe; over-attribution
# AnthroScore arXiv:2402.02056). neutral=explains/demonstrates/reports,
# strong=argues, tentative=suggests. interview/documentary/unknown -> agentless
# (a host/narrator/unknown source is not a single arguer). Returns None for the
# agentless case; the caller then uses topic-fronted framing.
_VERB_AGENTED: dict[str, dict[str, str]] = {
    "lecture":    {"high": "explains that",    "low": "suggests that"},
    "explainer":  {"high": "demonstrates how", "low": "walks through how"},
    "commentary": {"high": "argues that",      "low": "suggests that"},
    "news":       {"high": "reports that",     "low": "reports that"},
    # documentary / interview / unknown deliberately absent -> always agentless.
}


def reporting_verb_phrase(canonical_key: str, confidence: str) -> str | None:
    """Return the agented reporting-verb phrase (e.g. 'argues that'), or None
    when the lead sentence must be agentless (missing confidence, or a format
    whose 'speaker' is not a single arguer: interview/documentary/unknown).
    """
    if confidence == "missing":
        return None
    table = _VERB_AGENTED.get(canonical_key)
    if not table:
        return None
    return table.get(confidence) or table.get("high")


# Wave 1B — ReDoS-safe anchored leading-attribution detector.
# Requires the WHOLE leading clause: optional "In this <fmt>, " frame +
# subject (1-4 capitalised-ish tokens OR a role phrase) + reporting verb +
# "that"/"how". Anchored at ^, literal prefixes, BOUNDED ranges (\w{1,40},
# \s{1,3}), NO nested quantifiers -> linear time on CPython's backtracking
# engine (Snyk ReDoS guidance). Only fires on a LEADING clause, so a thesis
# that merely *contains* "argues" elsewhere is untouched.
_REPORTING_VERBS = (
    "argues", "explains", "demonstrates", "reports", "suggests", "contends",
    "describes", "shows", "claims", "examines", "discusses", "covers",
)
_LEADING_ATTRIBUTION_RE = re.compile(
    r"^\s{0,3}"
    r"(?:in\s{1,3}this\s{1,3}\w{1,40}\s{0,3},\s{0,3})?"   # optional "In this <fmt>,"
    r"(?:the\s{1,3})?"                                      # optional leading "the"
    r"\w{1,40}(?:\s{1,3}\w{1,40}){0,3}"                    # subject: 1-4 tokens (bounded)
    r"\s{1,3}(?:" + "|".join(_REPORTING_VERBS) + r")"      # reporting verb
    r"\s{1,3}(?:that|how)\b",                               # complementiser
    re.IGNORECASE,
)


def _canon(text: str) -> str:
    """NFC + collapse whitespace (incl. NBSP) for stable anchored compare.
    UAX#15: NFC is idempotent, so canonicalising twice == once."""
    nfc = unicodedata.normalize("NFC", text or "")
    return re.sub(r"\s+", " ", nfc.replace(" ", " ")).strip()


def has_leading_attribution(thesis: str) -> bool:
    """True iff ``thesis`` opens with a full attribution clause."""
    return bool(_LEADING_ATTRIBUTION_RE.match(_canon(thesis)))


# Wave 1B — connectors used by compose_lead_sentence's OWN agentless frames
# ("This {fmt} examines …", "This {fmt} sets out …", "In this {fmt}, X centers
# on …"). These are valid lead sentences but carry no complementised reporting
# clause, so has_leading_attribution does NOT match them. The composer must
# still recognise its own output and lift it verbatim, else f(f(x)) != f(x)
# (re-wrapping an already-composed agentless lead). Pure string compare on the
# canonical form — no regex, so the ReDoS guarantee is untouched.
def _opens_with_own_agentless_frame(thesis_canon: str, format_name: str) -> bool:
    """True iff ``thesis_canon`` (already _canon'd, lowercased here) opens with
    one of compose_lead_sentence's own agentless frames for ``format_name``."""
    fmt = (format_name or "").strip().lower()
    if not fmt:
        return False
    low = thesis_canon.lower()
    # "This {fmt} <connector>..." (no-thesis + missing/no-speaker frames)
    this_prefix = f"this {fmt} "
    if low.startswith(this_prefix):
        rest = low[len(this_prefix):]
        if any(rest.startswith(c) for c in ("examines ", "sets out ")):
            return True
    # "In this {fmt}, X centers on ..." (speaker + agentless-format frame)
    in_prefix = f"in this {fmt}, "
    if low.startswith(in_prefix) and " centers on " in low:
        return True
    return False


def lift_leading_attribution(thesis: str) -> str:
    """Return ``thesis`` as a finished lead sentence, preserving an existing
    leading attribution clause verbatim (just normalise whitespace + ensure a
    terminal period + leading capital). Used when the thesis is ALREADY
    attributed, so we never prepend a second clause (idempotency)."""
    cleaned = _canon(thesis)
    if not cleaned:
        return ""
    if cleaned[:1].islower():
        cleaned = cleaned[:1].upper() + cleaned[1:]
    if cleaned[-1] not in ".!?":
        cleaned = cleaned + "."
    return cleaned


def compose_lead_sentence(
    *,
    format_name: str,
    canonical_key: str,
    thesis: str,
    speakers: list[str],
    attribution_confidence: str,
) -> str:
    """Build the brief's first sentence — confidence-gated, format-verb-aware,
    idempotent. ``format_name`` is the human label for the frame ("commentary");
    ``canonical_key`` is the folded key for verb selection (Task 2)."""
    from website.features.summarization_engine.summarization.youtube.schema import (
        _first_sentence,
        _primary_speaker,
    )

    thesis_sentence = _first_sentence(thesis)
    if not thesis_sentence:
        # No thesis: agentless frame; never invent a speaker.
        return f"This {format_name} sets out its central topic."

    # IDEMPOTENCY: if the thesis already opens with an attribution clause, lift
    # it verbatim instead of prepending another (kills DOUBLING + makes f(f(x))==f(x)).
    if has_leading_attribution(thesis_sentence):
        return lift_leading_attribution(thesis_sentence)
    # IDEMPOTENCY (agentless): also lift the composer's OWN agentless frames so
    # feeding a composed agentless lead back in is not re-wrapped (f(f(x))==f(x)).
    if _opens_with_own_agentless_frame(_canon(thesis_sentence), format_name):
        return lift_leading_attribution(thesis_sentence)

    body = thesis_sentence.rstrip(".")
    verb_phrase = reporting_verb_phrase(canonical_key, attribution_confidence)
    speaker = _primary_speaker(speakers)  # "" when only placeholders/sentinel

    # M1 GATE: agented only when we have BOTH a real speaker AND an agented verb
    # for this format+confidence. Otherwise topic-fronted / agentless framing —
    # NEVER the literal "The speaker" (abstention: Rashkin 2023; Wen 2025).
    if verb_phrase and speaker:
        return f"In this {format_name}, {speaker} {verb_phrase} {body[:1].lower() + body[1:]}."
    # Agentless framings by intent:
    if attribution_confidence == "missing" or not speaker:
        return f"This {format_name} examines {body[:1].lower() + body[1:]}."
    # Have a speaker but format is agentless (interview/documentary/unknown):
    return f"In this {format_name}, {speaker} centers on {body[:1].lower() + body[1:]}."


__all__ = [
    "reconcile_attribution_confidence",
    "canonical_format",
    "reporting_verb_phrase",
    "has_leading_attribution",
    "lift_leading_attribution",
    "compose_lead_sentence",
]
