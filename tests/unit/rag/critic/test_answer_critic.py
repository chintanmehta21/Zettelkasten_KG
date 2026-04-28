from uuid import uuid4

import pytest

from website.features.rag_pipeline.critic import answer_critic as critic_module
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


def test_critic_prompt_contains_semantic_equivalence_leniency() -> None:
    """Spec 2A.1 / iter-03 plan §3.6 prong 1: prompt must instruct the verifier
    to accept paraphrase / summarization / generalization as 'supported'."""
    prompt = critic_module._CRITIC_PROMPT
    lower = prompt.lower()
    assert "lenient" in lower
    assert "paraphras" in lower or "paraphrase" in lower
    assert "semantically support" in lower
    # 'unsupported' must remain reserved for no-support / contradiction.
    assert "only if" in lower
    assert "contradict" in lower


@pytest.mark.asyncio
async def test_critic_sends_leniency_prompt_to_pool() -> None:
    """The prompt actually shipped to the LLM must contain the leniency clause
    (regression: ensures format() preserves the new wording)."""
    captured = {}

    class _Pool:
        async def generate_content(self, contents, **kwargs):
            captured["prompt"] = contents
            return '{"verdict":"supported","unsupported_claims":[],"bad_citations":[]}'

    await AnswerCritic(pool=_Pool()).verify(
        answer_text="Answer [node-1]",
        context_xml="<context></context>",
        context_candidates=[_candidate("node-1")],
    )
    assert "lenient" in captured["prompt"].lower()
    assert "semantically support" in captured["prompt"].lower()


@pytest.mark.asyncio
async def test_critic_accepts_paraphrase_supported_verdict_from_judge() -> None:
    """Smoke: when the judge returns 'supported' for a paraphrased answer (the
    spec q3/q8 over-refusal scenario), the critic propagates that verdict and
    does not silently downgrade. Pool is stubbed — no LLM call."""
    class _Pool:
        async def generate_content(self, contents, **kwargs):
            # Verifier returns 'supported' on a paraphrase.
            return '{"verdict":"supported","unsupported_claims":[],"bad_citations":[]}'

    verdict, _details = await AnswerCritic(pool=_Pool()).verify(
        answer_text=(
            "The Pragmatic Engineer recommends building a personal wiki "
            "with Obsidian for offline-first markdown notes. [node-1]"
        ),
        context_xml=(
            "<context><c id='node-1'>To build a personal wiki, use Obsidian "
            "for offline-first markdown notes.</c></context>"
        ),
        context_candidates=[_candidate("node-1")],
    )
    assert verdict == "supported"


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

