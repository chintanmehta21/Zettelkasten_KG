"""Shared fakes for per-class regression tests.

Stubs the entire RAG pipeline (rewriter, router, retriever, graph scorer,
reranker, assembler, LLM, critic, sessions) so the orchestrator can be driven
end-to-end without touching the network. Mirrors the fake classes in
tests/unit/rag/test_orchestrator.py — kept local to make per-class fixtures
self-contained and so the canned-refusal regression behaves identically across
QueryClass values.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from website.features.rag_pipeline.orchestrator import RAGOrchestrator
from website.features.rag_pipeline.types import (
    ChunkKind,
    QueryClass,
    RetrievalCandidate,
    SourceType,
)


class _Rewriter:
    async def rewrite(self, query, history):
        return query


class _Router:
    def __init__(self, query_class: QueryClass):
        self._cls = query_class

    async def classify(self, standalone):
        return self._cls


class _Transformer:
    async def transform(self, standalone, query_class):
        return [standalone]


class _Retriever:
    def __init__(self, candidates):
        self._candidates = candidates

    async def retrieve(self, **kwargs):
        return list(self._candidates)


class _Graph:
    async def score(self, *, user_id, candidates, query_class=None):
        for c in candidates:
            c.graph_score = 0.2


class _Reranker:
    async def rerank(self, query, candidates, top_k=8, query_class=None, graph_weight_override=None):
        for idx, c in enumerate(candidates):
            c.rerank_score = 0.9 - 0.1 * idx
            c.final_score = c.rerank_score
        return candidates[:top_k]


class _Assembler:
    async def build(self, *, candidates, quality, user_query, model=None):
        return "<context><zettel id=\"node-1\"/></context>", candidates


class _LLM:
    def __init__(self, content: str):
        self.content = content

    async def generate(self, *, query, system_prompt, user_prompt):
        return type(
            "Result",
            (),
            {
                "content": self.content,
                "model": "gemini-2.5-flash",
                "token_counts": {"total": 12},
                "finish_reason": "STOP",
            },
        )()

    async def generate_stream(self, *, query, system_prompt, user_prompt):
        yield self.content, {
            "model": "gemini-2.5-flash",
            "token_counts": {"total": 12},
            "finish_reason": "STOP",
        }


class _Critic:
    def __init__(self, verdicts):
        self._verdicts = list(verdicts)

    async def verify(self, **kwargs):
        return self._verdicts.pop(0), {}


class _Sessions:
    async def create_session(self, **kwargs):
        return uuid4()

    async def append_user_message(self, **kwargs):
        pass

    async def load_recent_turns(self, session_id, user_id):
        return []

    async def append_assistant_message(self, **kwargs):
        pass


def _candidate(node_id="node-1") -> RetrievalCandidate:
    return RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id=node_id,
        chunk_id=uuid4(),
        chunk_idx=0,
        name=node_id,
        source_type=SourceType.WEB,
        url=f"https://example.com/{node_id}",
        content="snippet",
        rrf_score=0.4,
    )


def build_orchestrator(
    *,
    query_class: QueryClass,
    answer_text: str,
    critic_verdicts: list[str],
) -> RAGOrchestrator:
    """Build a fake-wired RAGOrchestrator for per-class regression tests."""
    return RAGOrchestrator(
        rewriter=_Rewriter(),
        router=_Router(query_class),
        transformer=_Transformer(),
        retriever=_Retriever(candidates=[_candidate()]),
        graph_scorer=_Graph(),
        reranker=_Reranker(),
        assembler=_Assembler(),
        llm=_LLM(content=answer_text),
        critic=_Critic(critic_verdicts),
        sessions=_Sessions(),
    )


# Spec 2A.3: phrases that must NEVER appear in a non-refusal answer. q3/q8
# in iter-02/scores.md surfaced "I can't find" / "no Zettels" as the smoking
# gun for synth over-refusal. Any future regression that re-introduces a
# canned refusal for valid grounded answers will trip these assertions.
CANNED_REFUSAL_FRAGMENTS = (
    "i can't find",
    "no zettels",
    "i couldn't find",
    "no relevant zettels",
)


def assert_no_canned_refusal(answer: str) -> None:
    lower = (answer or "").lower()
    for fragment in CANNED_REFUSAL_FRAGMENTS:
        assert fragment not in lower, (
            f"canned-refusal fragment {fragment!r} leaked into answer: {answer!r}"
        )


@pytest.fixture
def grounded_answer_text() -> str:
    return 'Grounded paraphrase of cited content. [id="node-1"]'
