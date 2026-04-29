from __future__ import annotations

import re

from .types import CandidateDocument, PageIndexDocument, ZettelRecord


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 2}


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
        overlap = len(q & _tokens(haystack))
        title_bonus = 2.0 if q & _tokens(zettel.title) else 0.0
        tag_bonus = 1.0 if q & _tokens(" ".join(zettel.tags)) else 0.0
        score = float(overlap) + title_bonus + tag_bonus
        if score <= 0 and len(zettels) <= limit:
            score = 0.1
        doc = documents[zettel.node_id]
        scored.append(CandidateDocument(zettel.node_id, doc.doc_id, zettel.title, score, ("metadata_overlap",)))
    return sorted(scored, key=lambda item: item.score, reverse=True)[:limit]
