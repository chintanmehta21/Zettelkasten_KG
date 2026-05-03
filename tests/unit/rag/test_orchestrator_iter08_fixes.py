"""iter-08 surgical orchestrator fixes — Fix A (retry guard for partial+gold)
and Fix B (suppress citations on refusal).

Both fixes are gated behind env flags and default-on. The tests exercise the
helper functions directly (the full async pipeline is covered in
``test_orchestrator.py``); these are targeted unit checks for the new
behaviour.
"""

from __future__ import annotations

from types import SimpleNamespace

from website.features.rag_pipeline import orchestrator
from website.features.rag_pipeline.orchestrator import (
    RAGOrchestrator,
    _should_skip_retry,
)
from website.features.rag_pipeline.query.metadata import QueryMetadata
from website.features.rag_pipeline.types import QueryClass


def _candidate(rerank_score: float):
    """Minimal rerank candidate stub used by ``_top_candidate_score``."""
    return SimpleNamespace(rerank_score=rerank_score, rrf_score=0.0)


# ---------------------------------------------------------------------------
# Fix A — retry guard when first verdict is partial AND we have a gold chunk
# ---------------------------------------------------------------------------


def test_fix_a_partial_with_gold_skips_retry() -> None:
    skip, reason = _should_skip_retry(
        answer_text="Best draft with [id=node-1].",
        used_candidates=[_candidate(0.62)],
        query_class=QueryClass.LOOKUP,
        metadata=QueryMetadata(),
        first_verdict="partial",
    )
    assert skip is True
    assert reason == "partial_with_gold_skip"


def test_fix_a_partial_without_gold_does_not_short_circuit_for_this_reason() -> None:
    """Top score below the 0.5 floor must NOT trigger partial_with_gold_skip
    (the lower-score path may still skip via evaluator_low_score)."""
    skip, reason = _should_skip_retry(
        answer_text="Best draft with [id=node-1].",
        used_candidates=[_candidate(0.4)],
        query_class=QueryClass.LOOKUP,
        metadata=QueryMetadata(),
        first_verdict="partial",
    )
    assert reason != "partial_with_gold_skip"


def test_fix_a_unsupported_first_verdict_falls_through() -> None:
    """When the first verdict was already 'unsupported' (not 'partial'), the
    new clause must NOT fire — existing behaviour wins."""
    skip, reason = _should_skip_retry(
        answer_text="Some grounded answer.",
        used_candidates=[_candidate(0.9)],
        query_class=QueryClass.LOOKUP,
        metadata=QueryMetadata(),
        first_verdict="unsupported",
    )
    assert reason != "partial_with_gold_skip"


def test_fix_a_env_disable_restores_old_behaviour(monkeypatch) -> None:
    """RAG_PARTIAL_NO_RETRY_ENABLED=false must disable the new clause."""
    monkeypatch.setattr(orchestrator, "_PARTIAL_NO_RETRY_ENABLED", False)
    skip, reason = _should_skip_retry(
        answer_text="Best draft with [id=node-1].",
        used_candidates=[_candidate(0.9)],
        query_class=QueryClass.LOOKUP,
        metadata=QueryMetadata(),
        first_verdict="partial",
    )
    assert reason != "partial_with_gold_skip"


# ---------------------------------------------------------------------------
# Fix B — suppress citations on refusal-shaped answers
# ---------------------------------------------------------------------------


def _orch() -> RAGOrchestrator:
    """A bare orchestrator for poking at ``_build_citations`` directly. None
    of the constructor dependencies are touched by the citation builder."""
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


def _citation_candidate(node_id: str = "node-1"):
    """Stub matching the real RetrievalCandidate surface used by
    ``_build_citations``."""
    return SimpleNamespace(
        node_id=node_id,
        rerank_score=0.8,
        rrf_score=0.5,
        name="Title",
        source_type="web",
        url="https://example.com",
        content="snippet body" * 5,
        metadata={"timestamp": "2026-01-01T00:00:00Z"},
        chunk_id=None,
    )


def test_fix_b_unsupported_no_retry_returns_empty_citations() -> None:
    orch = _orch()
    citations = orch._build_citations(
        [_citation_candidate()],
        verdict="unsupported_no_retry",
        refused=False,
    )
    assert citations == []


def test_fix_b_refused_flag_returns_empty_citations() -> None:
    orch = _orch()
    citations = orch._build_citations(
        [_citation_candidate()],
        verdict="supported",
        refused=True,
    )
    assert citations == []


def test_fix_b_supported_verdict_keeps_citations() -> None:
    """Sanity: the suppression must NOT fire on healthy verdicts."""
    orch = _orch()
    citations = orch._build_citations(
        [_citation_candidate()],
        verdict="supported",
        refused=False,
    )
    assert len(citations) == 1
    assert citations[0].node_id == "node-1"


def test_fix_b_default_kwargs_keep_existing_callers_working() -> None:
    """Backward compat: callers that don't pass verdict/refused still get
    citations (e.g. the streaming path which emits citations early)."""
    orch = _orch()
    citations = orch._build_citations([_citation_candidate()])
    assert len(citations) == 1


def test_fix_b_env_disable_restores_old_behaviour(monkeypatch) -> None:
    """RAG_SUPPRESS_CITATIONS_ON_REFUSAL=false must let citations through
    even on refusal verdicts."""
    monkeypatch.setattr(orchestrator, "_SUPPRESS_CITATIONS_ON_REFUSAL", False)
    orch = _orch()
    citations = orch._build_citations(
        [_citation_candidate()],
        verdict="unsupported_no_retry",
        refused=True,
    )
    assert len(citations) == 1
