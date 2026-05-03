"""iter-08 Phase 5 — cite-hygiene filter inside ``_build_citations``.

The filter narrows the citation list to ids the LLM actually emitted in the
answer body (``[id="..."]`` tags). This tightens the eval-flow ``contexts``
list (rag_eval_loop.py:122 sources contexts from citations), which directly
improves RAGAS context_precision.

Default OFF — dark canary deploy. Tests use ``monkeypatch.setattr`` to flip
the module-level flag (env vars are evaluated at import time, mirroring the
existing Fix B test pattern in ``test_orchestrator_iter08_fixes.py``).
"""
from __future__ import annotations

from types import SimpleNamespace

from website.features.rag_pipeline import orchestrator
from website.features.rag_pipeline.orchestrator import (
    RAGOrchestrator,
    _extract_cited_ids,
)


def _orch() -> RAGOrchestrator:
    return RAGOrchestrator(
        rewriter=None,
        router=None,
        transformer=None,
        retriever=None,
        graph_scorer=None,
        reranker=None,
        assembler=None,
        llm=None,
        critic=None,
        sessions=None,
    )


def _cand(node_id: str, rerank: float = 0.8):
    return SimpleNamespace(
        node_id=node_id,
        rerank_score=rerank,
        rrf_score=rerank,
        name=f"Title {node_id}",
        source_type="web",
        url=f"https://example.com/{node_id}",
        content="snippet body",
        metadata={"timestamp": "2026-01-01T00:00:00Z"},
        chunk_id=f"{node_id}_c0",
    )


# ---------------------------------------------------------------------------
# _extract_cited_ids — pure parser
# ---------------------------------------------------------------------------


def test_extract_cited_ids_canonical():
    ans = 'Steve Jobs spoke at Stanford [id="yt-steve-jobs-2005-stanford"].'
    assert _extract_cited_ids(ans) == {"yt-steve-jobs-2005-stanford"}


def test_extract_cited_ids_chained():
    ans = 'Two zettels: [id="a"][id="b"] support this.'
    assert _extract_cited_ids(ans) == {"a", "b"}


def test_extract_cited_ids_empty_or_none():
    assert _extract_cited_ids("") == set()
    assert _extract_cited_ids(None) == set()  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _build_citations cite-hygiene branch (gated)
# ---------------------------------------------------------------------------


def test_cite_hygiene_filters_to_llm_cited(monkeypatch):
    monkeypatch.setattr(orchestrator, "_CITE_HYGIENE_ENABLED", True)
    orch = _orch()
    cands = [_cand("a", 0.9), _cand("b", 0.7), _cand("c", 0.5)]
    answer = 'Only A matters [id="a"].'
    cites = orch._build_citations(cands, answer_text=answer)
    assert [c.node_id for c in cites] == ["a"]


def test_cite_hygiene_fallback_top_k_when_only_fabricated(monkeypatch):
    """LLM cited only an unknown id → fall back to top-K=3."""
    monkeypatch.setattr(orchestrator, "_CITE_HYGIENE_ENABLED", True)
    orch = _orch()
    cands = [_cand("a", 0.9), _cand("b", 0.7), _cand("c", 0.5), _cand("d", 0.3)]
    answer = 'Cited unknown [id="x_fabricated"].'
    cites = orch._build_citations(cands, answer_text=answer)
    assert [c.node_id for c in cites] == ["a", "b", "c"]


def test_cite_hygiene_keeps_all_when_no_inline_cites(monkeypatch):
    """LLM cited nothing inline → keep ranked_candidates as-is (no regression)."""
    monkeypatch.setattr(orchestrator, "_CITE_HYGIENE_ENABLED", True)
    orch = _orch()
    cands = [_cand("a", 0.9), _cand("b", 0.7)]
    answer = "No inline cites at all."
    cites = orch._build_citations(cands, answer_text=answer)
    assert [c.node_id for c in cites] == ["a", "b"]


def test_cite_hygiene_disabled_keeps_all(monkeypatch):
    monkeypatch.setattr(orchestrator, "_CITE_HYGIENE_ENABLED", False)
    orch = _orch()
    cands = [_cand("a", 0.9), _cand("b", 0.7)]
    answer = 'Only A [id="a"].'
    cites = orch._build_citations(cands, answer_text=answer)
    assert [c.node_id for c in cites] == ["a", "b"]


def test_cite_hygiene_default_off_no_answer_text(monkeypatch):
    """Backward compat: callers that omit answer_text must not change."""
    orch = _orch()
    cands = [_cand("a", 0.9), _cand("b", 0.7)]
    cites = orch._build_citations(cands)
    assert [c.node_id for c in cites] == ["a", "b"]
