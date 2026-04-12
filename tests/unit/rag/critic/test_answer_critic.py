from uuid import uuid4

import pytest

from website.features.rag_pipeline.critic.answer_critic import AnswerCritic
from website.features.rag_pipeline.types import ChunkKind, RetrievalCandidate, SourceType


def _candidate(node_id: str) -> RetrievalCandidate:
    return RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id=node_id,
        chunk_id=uuid4(),
        chunk_idx=0,
        name=node_id,
        source_type=SourceType.WEB,
        url=f"https://example.com/{node_id}",
        content="content",
        rrf_score=0.5,
    )


@pytest.mark.asyncio
async def test_critic_returns_supported_for_grounded_answer() -> None:
    class _Pool:
        async def generate_content(self, contents, **kwargs):
            return '{"verdict":"supported","unsupported_claims":[],"bad_citations":[]}'

    verdict, details = await AnswerCritic(pool=_Pool()).verify(
        answer_text="Grounded answer [node-1]",
        context_xml="<context></context>",
        context_candidates=[_candidate("node-1")],
    )
    assert verdict == "supported"
    assert details["bad_citations"] == []


@pytest.mark.asyncio
async def test_critic_returns_partial_when_llm_judge_says_partial() -> None:
    class _Pool:
        async def generate_content(self, contents, **kwargs):
            return '{"verdict":"partial","unsupported_claims":[],"bad_citations":[]}'

    verdict, _details = await AnswerCritic(pool=_Pool()).verify(
        answer_text="Answer [node-1]",
        context_xml="<context></context>",
        context_candidates=[_candidate("node-1")],
    )
    assert verdict == "partial"


def test_bad_citation_detector_flags_ids_not_in_context() -> None:
    critic = AnswerCritic(pool=None)
    bad = critic._find_bad_citations("Answer [node-1, node-2]", [_candidate("node-1")])
    assert bad == ["node-2"]


@pytest.mark.asyncio
async def test_critic_failure_defaults_to_supported_with_error_note() -> None:
    class _Pool:
        async def generate_content(self, contents, **kwargs):
            raise RuntimeError("boom")

    verdict, details = await AnswerCritic(pool=_Pool()).verify(
        answer_text="Answer",
        context_xml="<context></context>",
        context_candidates=[_candidate("node-1")],
    )
    assert verdict == "supported"
    assert "critic_error" in details


@pytest.mark.asyncio
async def test_llm_supported_downgraded_to_partial_if_bad_citations_found() -> None:
    class _Pool:
        async def generate_content(self, contents, **kwargs):
            return '{"verdict":"supported","unsupported_claims":[],"bad_citations":[]}'

    verdict, details = await AnswerCritic(pool=_Pool()).verify(
        answer_text="Answer [node-2]",
        context_xml="<context></context>",
        context_candidates=[_candidate("node-1")],
    )
    assert verdict == "partial"
    assert details["bad_citations"] == ["node-2"]

