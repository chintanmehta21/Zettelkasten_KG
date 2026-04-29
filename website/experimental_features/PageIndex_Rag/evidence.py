from __future__ import annotations

from .pageindex_adapter import PageIndexAdapter
from .types import CandidateDocument, EvidenceItem, ZettelRecord


def _line_range_from_tree(tree: list[dict], query: str) -> str:
    if not tree:
        return "1"
    return str(tree[0].get("line_num") or 1)


def retrieve_evidence(
    *,
    adapter: PageIndexAdapter,
    candidates: list[CandidateDocument],
    zettels_by_id: dict[str, ZettelRecord],
    query: str,
) -> list[EvidenceItem]:
    evidence: list[EvidenceItem] = []
    for candidate in candidates:
        tree = adapter.get_document_structure(candidate.doc_id)
        pages = _line_range_from_tree(tree, query)
        chunks = adapter.get_page_content(candidate.doc_id, pages)
        zettel = zettels_by_id[candidate.node_id]
        text = "\n\n".join(str(item.get("content") or "") for item in chunks).strip()
        if not text:
            continue
        evidence.append(
            EvidenceItem(
                node_id=candidate.node_id,
                doc_id=candidate.doc_id,
                title=candidate.title,
                source_url=zettel.url,
                section=str(tree[0].get("title") if tree else candidate.title),
                line_range=pages,
                text=text,
                score=candidate.score,
            )
        )
    return evidence
