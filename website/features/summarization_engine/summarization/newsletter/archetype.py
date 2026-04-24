"""Local-heuristic newsletter archetype classifier.

The 3-call per-zettel budget for NewsletterSummarizer is already spent on
DenseVerifier, StructuredExtractor, and the optional template-artifact
repair. A fourth LLM call just to label the archetype would be wasteful —
the signals that distinguish engineering essays from news roundups (URL
path, TOC-like bullet density, pronoun usage, numeric-claim density,
hyperlink density) are all local and deterministic.

This module therefore pattern-matches on the structured payload + surface
text to emit one of the ``VALID_ARCHETYPES`` labels. The classifier is
deterministic, fast, and side-effect free. On ambiguous inputs it falls
back to ``"engineering_essay"`` (the dominant Substack/Beehiiv default in
our eval corpus) — tests assert this explicitly so the fallback does not
drift.

Taxonomy:
    engineering_essay: long-form technical arg (frameworks, code, design)
    business_analysis: markets, companies, strategy, financials
    career_advice:     job/career guidance, interviews, hiring
    tutorial:          how-to / walkthrough with ordered steps
    news_roundup:      bundle of short items, heavy "this week" framing
    opinion_piece:     first-person argumentative stance (not tech-heavy)
    personal_essay:    narrative / memoir / life reflection
    other:             explicit escape hatch for unclassifiable payloads
"""
from __future__ import annotations

import re
from collections.abc import Iterable

VALID_ARCHETYPES: tuple[str, ...] = (
    "engineering_essay",
    "business_analysis",
    "career_advice",
    "tutorial",
    "news_roundup",
    "opinion_piece",
    "personal_essay",
    "other",
)

# Default when nothing matches. Our newsletter eval corpus is dominated by
# Substack/Beehiiv engineering writing (Pragmatic Engineer, Platformer,
# Organic Synthesis), so this is the least surprising fallback.
_DEFAULT_ARCHETYPE = "engineering_essay"

# Keyword sets scored against the combined corpus (title + brief + all
# bullets). Each keyword appearance contributes +1 to the archetype's
# score; the highest-scoring archetype wins. Ties break toward the
# earlier-listed archetype below (since dict iteration order is stable).
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "tutorial": (
        r"\bstep[-\s]by[-\s]step\b",
        r"\bwalkthrough\b",
        r"\bhow to\b",
        r"\btutorial\b",
        r"\bhands[-\s]on\b",
        r"\bgetting started\b",
    ),
    "news_roundup": (
        r"\bthis week\b",
        r"\broundup\b",
        r"\bdigest\b",
        r"\bweekly\b",
        r"\bnewsletter #\d+\b",
        r"\bissue #\d+\b",
        r"\bin the news\b",
        r"\bheadlines\b",
    ),
    "career_advice": (
        r"\binterview\b",
        r"\bhiring\b",
        r"\bcareer\b",
        r"\bresume\b",
        r"\bmanager\b",
        r"\bpromot(?:e|ion|ed)\b",
        r"\bpromoted\b",
        r"\bengineer(?:ing)? ladder\b",
        r"\bjob offer\b",
    ),
    "business_analysis": (
        r"\brevenue\b",
        r"\bvaluation\b",
        r"\bmarket cap\b",
        r"\bearnings\b",
        r"\bacquisition\b",
        r"\bstrategy\b",
        r"\bmargins?\b",
        r"\bbusiness model\b",
        r"\bcompetit(?:or|ion|ive)\b",
        r"\binvestors?\b",
    ),
    "engineering_essay": (
        r"\barchitecture\b",
        r"\blatency\b",
        r"\bthroughput\b",
        r"\bdatabase\b",
        r"\balgorithm\b",
        r"\bmicroservice\b",
        r"\bscaling\b",
        r"\bdistributed\b",
        r"\bperformance\b",
        r"\bcode\b",
        r"\bapi\b",
        r"\bkernel\b",
        r"\bprotocol\b",
    ),
    "opinion_piece": (
        r"\bi think\b",
        r"\bi believe\b",
        r"\bin my opinion\b",
        r"\bimo\b",
        r"\bhot take\b",
        r"\bmanifesto\b",
        r"\bshould\b",
        r"\bmust\b",
    ),
    "personal_essay": (
        r"\bmy story\b",
        r"\bgrew up\b",
        r"\bwhen i was\b",
        r"\breflections?\b",
        r"\bmemoir\b",
        r"\bjourney\b",
        r"\blooking back\b",
    ),
}


def _join_corpus(
    *,
    title: str,
    brief_summary: str,
    detailed_bullets: Iterable[str],
) -> str:
    parts = [title or "", brief_summary or "", *[b or "" for b in detailed_bullets]]
    return " \n".join(p.strip() for p in parts if p and p.strip()).lower()


def _score_keywords(corpus: str) -> dict[str, int]:
    scores: dict[str, int] = {a: 0 for a in VALID_ARCHETYPES}
    for archetype, patterns in _KEYWORDS.items():
        for pat in patterns:
            scores[archetype] += len(re.findall(pat, corpus, flags=re.IGNORECASE))
    return scores


def _url_hints(url: str) -> list[str]:
    url_low = (url or "").lower()
    hints: list[str] = []
    if not url_low:
        return hints
    if any(tok in url_low for tok in ("/career", "/interview", "/hiring")):
        hints.append("career_advice")
    if any(
        tok in url_low
        for tok in ("/weekly", "/digest", "/roundup", "thisweek", "this-week")
    ):
        hints.append("news_roundup")
    if any(tok in url_low for tok in ("/tutorial", "/how-to", "howto")):
        hints.append("tutorial")
    return hints


def archetype_from_signals(
    *,
    title: str,
    brief_summary: str,
    detailed_bullets: Iterable[str] | None = None,
    url: str = "",
) -> str:
    """Return one of ``VALID_ARCHETYPES`` based on local text signals only.

    Deterministic: identical inputs always produce the same label. Never
    raises; an empty-text input returns ``_DEFAULT_ARCHETYPE``. No LLM
    calls.
    """
    bullets = list(detailed_bullets or [])
    corpus = _join_corpus(
        title=title, brief_summary=brief_summary, detailed_bullets=bullets
    )
    if not corpus.strip():
        return _DEFAULT_ARCHETYPE

    scores = _score_keywords(corpus)
    for hint in _url_hints(url):
        # URL hints add +2 so they tip close ties but don't override a
        # strong body-text signal (which tends to score 3+).
        scores[hint] = scores.get(hint, 0) + 2

    best = max(scores.items(), key=lambda kv: kv[1])
    if best[1] <= 0:
        return _DEFAULT_ARCHETYPE
    return best[0]


__all__ = ["archetype_from_signals", "VALID_ARCHETYPES"]
