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

from website.features.summarization_engine.summarization.youtube.schema import (
    _is_geographic_entity,
    _is_placeholder_speaker,
)

_SENTINEL_SPEAKER = "the speaker"


def reconcile_attribution_confidence(speakers: list[str]) -> str:
    """Derive attribution_confidence ('high'|'low'|'missing') from a speaker list.

    Single source of truth reused by the schema validator AND the
    speaker_detector override seam (summarizer.py) so the two can never desync.
    Mirrors the prior inline logic in _sanitize_speakers exactly:
      - any real (non-placeholder, non-geographic, non-sentinel) name present:
        'high' if NO placeholder/geographic was also present, else 'low'
      - no real name at all: 'missing'
    """
    cleaned = [s.strip() for s in (speakers or []) if isinstance(s, str) and s.strip()]
    real = [
        s for s in cleaned
        if not _is_placeholder_speaker(s)
        and not _is_geographic_entity(s)
        and s.lower() != _SENTINEL_SPEAKER
    ]
    if not real:
        return "missing"
    had_placeholder = any(
        _is_placeholder_speaker(s) or _is_geographic_entity(s) or s.lower() == _SENTINEL_SPEAKER
        for s in cleaned
    )
    return "low" if had_placeholder else "high"


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


__all__ = ["reconcile_attribution_confidence", "canonical_format"]
