"""2026-08-01: a critic OUTAGE must not be laundered into a refusal verdict.

``AnswerCritic.verify`` fails closed — it catches every exception and returns
``("unsupported", {"critic_error": ...})``. That verdict becomes
``unsupported_no_retry``, which ``_build_citations`` treats as "the user is
being shown a refusal, so a citation chip would be misleading" and returns
``[]``.

That conflation is the leading explanation for the 2026-08-01T04:08Z deploy
smoke failure: HTTP 200, an answer present, and ZERO citations, self-healing on
the next container. Retrieval was almost certainly fine — a transient Gemini
error on the LAST of ~6 generative calls stripped the evidence off a good answer.

Suppression is correct when the model genuinely refused. It is wrong when our
own critic call fell over: the answer and its citations are still good, and
silently dropping the evidence turns an infrastructure blip into what looks
like a retrieval collapse.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from website.features.rag_pipeline.orchestrator import RAGOrchestrator
from website.features.rag_pipeline.types import ChunkKind, RetrievalCandidate, SourceType


def _candidate(node_id: str = "chunk-1", name: str = "TheEconomist/big-mac-data"):
    return RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id=node_id,
        chunk_idx=0,
        name=name,
        source_type=SourceType.GITHUB,
        url="https://github.com/TheEconomist/big-mac-data",
        content="The Big Mac index data and R code.",
        rrf_score=0.9,
        rerank_score=0.99,
    )


@pytest.fixture
def orch() -> RAGOrchestrator:
    return RAGOrchestrator.__new__(RAGOrchestrator)


def test_genuine_refusal_still_suppresses_citations(orch):
    """The original iter-08 behaviour must be preserved."""
    cits = orch._build_citations(
        [_candidate()], verdict="unsupported_no_retry", refused=True
    )
    assert cits == []


def test_unsupported_no_retry_without_critic_error_still_suppresses(orch):
    """A real 'unsupported' judgement (critic ran, said no) keeps suppressing."""
    cits = orch._build_citations(
        [_candidate()], verdict="unsupported_no_retry", details={}
    )
    assert cits == []


def test_critic_outage_does_not_strip_citations(orch):
    """THE FIX: when the verdict came from a critic EXCEPTION, keep citations."""
    cits = orch._build_citations(
        [_candidate()],
        verdict="unsupported_no_retry",
        details={"critic_error": "ClientError: 429 RESOURCE_EXHAUSTED"},
    )
    assert len(cits) == 1
    assert cits[0].title == "TheEconomist/big-mac-data"


def test_critic_outage_with_explicit_refusal_still_suppresses(orch):
    """An explicit refusal flag outranks the critic-outage exemption.

    ``refused=True`` means the synthesiser itself produced the canonical
    refusal phrase — there is no answer to attach citations to, regardless of
    what the critic did afterwards.
    """
    cits = orch._build_citations(
        [_candidate()],
        verdict="unsupported_no_retry",
        refused=True,
        details={"critic_error": "timeout"},
    )
    assert cits == []


def test_healthy_answer_is_unaffected(orch):
    cits = orch._build_citations([_candidate()], verdict="supported", details={})
    assert len(cits) == 1


def test_details_none_is_safe(orch):
    """``details`` is optional; a None must not raise."""
    cits = orch._build_citations([_candidate()], verdict="supported", details=None)
    assert len(cits) == 1


def test_non_dict_details_is_safe(orch):
    """The orchestrator guards ``isinstance(details, dict)`` elsewhere; match it."""
    cits = orch._build_citations(
        [_candidate()], verdict="unsupported_no_retry", details=MagicMock()
    )
    assert cits == []
