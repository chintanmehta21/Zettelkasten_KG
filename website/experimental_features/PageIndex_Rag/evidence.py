from __future__ import annotations

import re

from .pageindex_adapter import PageIndexAdapter
from .types import CandidateDocument, EvidenceItem, ZettelRecord


STOPWORDS = {
    "about",
    "according",
    "and",
    "are",
    "does",
    "for",
    "from",
    "how",
    "the",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
}


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9+_-]*", text.lower())
        if len(token) > 2 and token not in STOPWORDS
    }


def _node_text(node: dict) -> str:
    return " ".join(
        str(node.get(key) or "")
        for key in ("title", "summary", "text", "content")
    )


def _line_value(node: dict) -> int:
    return int(node.get("line_num") or node.get("start_index") or node.get("page_index") or 1)


def plan_retrieval_nodes(tree: list[dict], query: str, *, limit: int = 2) -> list[dict]:
    if not tree:
        return [{"title": "Document", "line_num": 1, "node_id": "0001"}]
    query_tokens = _tokens(query)
    scored = []
    for node in tree:
        title = str(node.get("title") or "")
        node_tokens = _tokens(_node_text(node))
        score = len(query_tokens & node_tokens)
        lowered_title = title.lower()
        if "captured content" in lowered_title:
            score += 3
        if "summary" in lowered_title:
            score += 2
        if "metadata" in lowered_title:
            score -= 2
        level = int(node.get("level") or 1)
        if level == 1 and len(tree) > 1:
            score -= 1
        scored.append((score, _line_value(node), node))
    selected = [node for score, _, node in sorted(scored, key=lambda item: (-item[0], item[1])) if score > -2][:limit]
    if not selected:
        selected = sorted(tree, key=_line_value)[:limit]
    selected_titles = {str(node.get("title") or "").lower() for node in selected}
    for preferred in ("Captured Content", "Summary"):
        if any(preferred.lower() == title for title in selected_titles):
            continue
        for node in tree:
            if str(node.get("title") or "").lower() == preferred.lower():
                selected.append(node)
                break
    return sorted(selected[:limit], key=lambda node: (0 if "captured content" in str(node.get("title") or "").lower() else 1, _line_value(node)))


def _line_range_from_tree(tree: list[dict], query: str) -> str:
    return ",".join(str(_line_value(node)) for node in sorted(plan_retrieval_nodes(tree, query), key=_line_value))


def _candidate_subtree(tree: list[dict], candidate: CandidateDocument) -> list[dict]:
    roots = [
        node
        for node in tree
        if int(node.get("level") or 1) <= 2
        and str(node.get("title") or "").strip().lower() == candidate.title.strip().lower()
    ]
    if not roots:
        return tree
    root = roots[0]
    start = _line_value(root)
    root_level = int(root.get("level") or 1)
    end: int | None = None
    for node in sorted(tree, key=_line_value):
        line = _line_value(node)
        if line <= start:
            continue
        level = int(node.get("level") or 1)
        if level <= root_level:
            end = line
            break
    return [node for node in tree if _line_value(node) >= start and (end is None or _line_value(node) < end)]


def _fallback_zettel_content(zettel: ZettelRecord, *, full: bool) -> str:
    if full:
        return "\n\n".join(
            part for part in (f"Summary:\n{zettel.summary}", f"Captured Content:\n{zettel.content}") if part.strip()
        ).strip()
    return f"Summary:\n{zettel.summary}".strip()


def retrieve_evidence(
    *,
    adapter: PageIndexAdapter,
    candidates: list[CandidateDocument],
    zettels_by_id: dict[str, ZettelRecord],
    query: str,
) -> list[EvidenceItem]:
    evidence: list[EvidenceItem] = []
    for index, candidate in enumerate(candidates):
        tree = adapter.get_document_structure(candidate.doc_id)
        candidate_tree = _candidate_subtree(tree, candidate)
        pages = _line_range_from_tree(candidate_tree, query)
        chunks = adapter.get_page_content(candidate.doc_id, pages)
        zettel = zettels_by_id[candidate.node_id]
        text = "\n\n".join(str(item.get("content") or "") for item in chunks).strip()
        fallback = _fallback_zettel_content(zettel, full=index == 0)
        if fallback and (len(text) < 400 or not (_tokens(query) & _tokens(text))):
            text = "\n\n".join(part for part in (text, fallback) if part).strip()
        if index > 0 and len(text) > 1800:
            text = text[:1800].rsplit(" ", 1)[0].strip()
        if not text:
            continue
        selected_nodes = plan_retrieval_nodes(candidate_tree, query)
        evidence.append(
            EvidenceItem(
                node_id=candidate.node_id,
                doc_id=candidate.doc_id,
                title=candidate.title,
                source_url=zettel.url,
                section=", ".join(str(node.get("title") or candidate.title) for node in selected_nodes),
                line_range=pages,
                text=text,
                score=candidate.score,
            )
        )
    return evidence
