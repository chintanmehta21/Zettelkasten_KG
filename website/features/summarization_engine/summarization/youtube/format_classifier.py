"""Confidence-scored YouTube format classifier.

Replaces the binary ``other``-fallback behaviour of the previous format
normaliser. The classifier scores five canonical labels against lexical
and metadata signals and always returns a label with a floor-confidence
of ``0.2`` so downstream code never sees ``"other"``.

The labels are deliberately narrow and mutually intelligible; broader
categories like ``review`` / ``reaction`` / ``vlog`` are intentionally
mapped onto ``commentary`` upstream to avoid label sprawl.
"""
from __future__ import annotations

import re

FORMAT_LABELS: tuple[str, ...] = (
    "documentary",
    "commentary",
    "lecture",
    "explainer",
    "interview",
)

_DEFAULT_LABEL = "commentary"
_CONFIDENCE_FLOOR = 0.2

# Keyword weights per label. Weights are small integers; the final
# confidence is a softmax-ish ratio of the winning score over the total.
_KEYWORDS: dict[str, tuple[tuple[str, int], ...]] = {
    "documentary": (
        ("narrator", 3), ("narration", 2), ("archival footage", 4),
        ("archival", 2), ("documentary", 4), ("docuseries", 3),
        ("investigation", 2), ("true story", 2), ("untold", 2),
        ("chronicle", 2), ("b-roll", 2),
    ),
    "commentary": (
        ("opinion", 3), ("reaction", 3), ("hot take", 3), ("my take", 2),
        ("commentary", 4), ("rant", 2), ("review", 2), ("thoughts on", 2),
        ("vlog", 2), ("verdict", 2), ("response to", 2),
    ),
    "lecture": (
        ("professor", 3), ("lecture", 4), ("slides", 3), ("chapter", 2),
        ("course", 3), ("seminar", 3), ("university", 2), ("lesson", 2),
        ("syllabus", 3), ("theorem", 2), ("whiteboard", 2),
    ),
    "explainer": (
        ("how it works", 3), ("how does", 2), ("tutorial", 3),
        ("step-by-step", 3), ("step by step", 3), ("walkthrough", 3),
        ("how to", 3), ("explained", 3), ("explainer", 4), ("demo", 2),
        ("guide", 2), ("beginner", 2),
    ),
    "interview": (
        ("q&a", 4), ("q & a", 3), ("guest", 3), ("interview", 4),
        ("podcast", 3), ("conversation with", 3), ("sit down with", 3),
        ("joins us", 2), ("in conversation", 3), ("fireside", 2),
    ),
}


def _score_text(text: str) -> dict[str, int]:
    scores = {label: 0 for label in FORMAT_LABELS}
    if not text:
        return scores
    lowered = text.lower()
    for label, kws in _KEYWORDS.items():
        for needle, weight in kws:
            # use word-ish boundary when needle is a single alnum token
            if re.search(r"[^a-z0-9]", needle):
                if needle in lowered:
                    scores[label] += weight
            else:
                if re.search(rf"\b{re.escape(needle)}\b", lowered):
                    scores[label] += weight
    return scores


def classify_format(
    title: str,
    description: str,
    chapter_titles: list[str],
    speakers: list[str],
) -> tuple[str, float]:
    """Pick a label in :data:`FORMAT_LABELS` and a confidence in ``[0.2, 1.0]``.

    Never returns ``"other"``: if no lexical signal fires, falls back to
    ``"commentary"`` at the ``_CONFIDENCE_FLOOR`` so downstream callers
    always get a concrete, rubric-compatible label.
    """
    title = title or ""
    description = description or ""
    chapter_titles = [t for t in (chapter_titles or []) if isinstance(t, str) and t.strip()]
    speakers = [s for s in (speakers or []) if isinstance(s, str) and s.strip()]

    combined = " ".join([title, description, " ".join(chapter_titles)]).strip()
    scores = _score_text(combined)

    # Metadata boosts independent of free-text keyword scan.
    # Two or more distinct speakers is a strong interview signal.
    unique_speakers = {s.strip().lower() for s in speakers}
    if len(unique_speakers) >= 2:
        scores["interview"] += 4
    # Numbered / timestamped chapter titles boost lecture.
    if chapter_titles:
        timestamped = sum(
            1 for t in chapter_titles if re.search(r"^\s*(?:\d{1,2}:\d{2}|chapter\s*\d+|\d+\.)", t, re.IGNORECASE)
        )
        if timestamped >= max(2, len(chapter_titles) // 2):
            scores["lecture"] += 3

    top_label, top_score = max(scores.items(), key=lambda kv: kv[1])
    total = sum(max(v, 0) for v in scores.values())

    if top_score <= 0 or total <= 0:
        return _DEFAULT_LABEL, _CONFIDENCE_FLOOR

    # On a tie between labels, prefer the order in FORMAT_LABELS for
    # determinism (max() is first-wins, but dict order is insertion order).
    tied = [lbl for lbl, sc in scores.items() if sc == top_score]
    if len(tied) > 1:
        top_label = next(lbl for lbl in FORMAT_LABELS if lbl in tied)

    confidence = top_score / total
    # Dampen over-confidence from a single strong keyword.
    if top_score < 4:
        confidence = min(confidence, 0.6)
    return top_label, max(_CONFIDENCE_FLOOR, min(1.0, confidence))


__all__ = ["FORMAT_LABELS", "classify_format"]
