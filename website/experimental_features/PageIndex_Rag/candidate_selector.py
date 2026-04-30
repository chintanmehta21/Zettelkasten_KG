from __future__ import annotations

import re

from .types import CandidateDocument, PageIndexDocument, ZettelRecord


STOPWORDS = {
    "about",
    "according",
    "and",
    "are",
    "both",
    "come",
    "does",
    "for",
    "from",
    "how",
    "into",
    "only",
    "says",
    "than",
    "that",
    "the",
    "their",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
}


def _tokens(text: str) -> set[str]:
    return {
        token[:-1] if token.endswith("s") and len(token) > 4 else token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in STOPWORDS
    }


def select_candidates(
    *,
    query: str,
    zettels: list[ZettelRecord],
    documents: dict[str, PageIndexDocument],
    limit: int,
) -> list[CandidateDocument]:
    q = _tokens(query)
    scored: list[CandidateDocument] = []
    for zettel in zettels:
        haystack = " ".join([zettel.title, zettel.summary, " ".join(zettel.tags), zettel.source_type])
        title_tokens = _tokens(zettel.title)
        tag_tokens = _tokens(" ".join(zettel.tags))
        title_overlap = len(q & title_tokens)
        overlap = len(q & _tokens(haystack))
        title_bonus = title_overlap * 3.0
        if title_tokens and title_tokens <= q:
            title_bonus += 4.0
        tag_bonus = len(q & tag_tokens) * 1.25
        score = float(overlap) + title_bonus + tag_bonus
        if score <= 0 and len(zettels) <= limit:
            score = 0.1
        doc = documents[zettel.node_id]
        scored.append(CandidateDocument(zettel.node_id, doc.doc_id, zettel.title, score, ("metadata_overlap",)))
    return sorted(scored, key=lambda item: item.score, reverse=True)[:limit]
