import asyncio
from uuid import uuid4

import pytest

from website.features.rag_pipeline.errors import EmptyScopeError, LLMUnavailable
from website.features.rag_pipeline.orchestrator import RAGOrchestrator
from website.features.rag_pipeline.types import ChatQuery, QueryClass, RetrievalCandidate, ChunkKind, SourceType


class _Rewriter:
    async def rewrite(self, query, history):
        return query


class _Router:
    async def classify(self, standalone):
        return QueryClass.LOOKUP


class _Transformer:
    async def transform(self, standalone, query_class):
        return [standalone]


class _Retriever:
    def __init__(self, *, error=None, candidates=None):
        self.error = error
        self.calls = 0
        self.candidates = candidates or []

    async def retrieve(self, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return list(self.candidates)


class _Graph:
    async def score(self, *, user_id, candidates):
        for candidate in candidates:
            candidate.graph_score = 0.2


class _Reranker:
    async def rerank(self, query, candidates, top_k=8):
        for idx, candidate in enumerate(candidates):
            candidate.rerank_score = 0.9 - idx * 0.1
            candidate.final_score = candidate.rerank_score
        return candidates[:top_k]


class _Assembler:
    async def build(self, *, candidates, quality, user_query):
        return "<context><zettel id=\"node-1\"/></context>", candidates


class _LLM:
    def __init__(self, *, content="Grounded answer [node-1]", stream_tokens=None, error=None):
        self.content = content
        self.stream_tokens = stream_tokens or [content]
        self.error = error

    async def generate(self, *, query, system_prompt, user_prompt):
        if self.error:
            raise self.error
        return type("Result", (), {"content": self.content, "model": "gemini-2.5-flash", "token_counts": {"total": 12}, "finish_reason": "STOP"})()

    async def generate_stream(self, *, query, system_prompt, user_prompt):
        if self.error:
            raise self.error
        for token in self.stream_tokens:
            yield token, {"model": "gemini-2.5-flash", "token_counts": {"total": 12}, "finish_reason": "STOP"}


class _BlockingStreamLLM:
    def __init__(self):
        self.first_token_emitted = asyncio.Event()
        self.allow_completion = asyncio.Event()

    async def generate(self, *, query, system_prompt, user_prompt):
        del query, system_prompt, user_prompt
        return type("Result", (), {"content": "unused", "model": "gemini-2.5-flash", "token_counts": {"total": 12}, "finish_reason": "STOP"})()

    async def generate_stream(self, *, query, system_prompt, user_prompt):
        del query, system_prompt, user_prompt
        self.first_token_emitted.set()
        yield "Hello", {"model": "gemini-2.5-flash", "token_counts": {"total": 5}, "finish_reason": ""}
        await self.allow_completion.wait()
        yield " world", {"model": "gemini-2.5-flash", "token_counts": {"total": 12}, "finish_reason": "STOP"}


class _Critic:
    def __init__(self, verdicts):
        self._verdicts = list(verdicts)

    async def verify(self, **kwargs):
        verdict = self._verdicts.pop(0)
        return verdict, {}


class _Sessions:
    def __init__(self):
        self.created = []
        self.user_messages = []
        self.assistant_messages = []

    async def create_session(self, **kwargs):
        session_id = uuid4()
        self.created.append(session_id)
        return session_id

    async def append_user_message(self, **kwargs):
        self.user_messages.append(kwargs)

    async def load_recent_turns(self, session_id, user_id):
        return []

    async def append_assistant_message(self, **kwargs):
        self.assistant_messages.append(kwargs)


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


@pytest.mark.asyncio
async def test_answer_happy_path_returns_grounded_answer_with_citations() -> None:
    sessions = _Sessions()
    orchestrator = RAGOrchestrator(
        rewriter=_Rewriter(),
        router=_Router(),
        transformer=_Transformer(),
        retriever=_Retriever(candidates=[_candidate()]),
        graph_scorer=_Graph(),
        reranker=_Reranker(),
        assembler=_Assembler(),
        llm=_LLM(),
        critic=_Critic(["supported"]),
        sessions=sessions,
    )

    turn = await orchestrator.answer(query=ChatQuery(content="What is this about?"), user_id=uuid4())

    assert turn.content.startswith("Grounded answer")
    assert turn.citations[0].node_id == "node-1"
    assert sessions.assistant_messages


@pytest.mark.asyncio
async def test_empty_scope_raises_empty_scope_error() -> None:
    orchestrator = RAGOrchestrator(
        rewriter=_Rewriter(),
        router=_Router(),
        transformer=_Transformer(),
        retriever=_Retriever(error=EmptyScopeError("empty")),
        graph_scorer=_Graph(),
        reranker=_Reranker(),
        assembler=_Assembler(),
        llm=_LLM(),
        critic=_Critic(["supported"]),
        sessions=_Sessions(),
    )

    with pytest.raises(EmptyScopeError):
        await orchestrator.answer(query=ChatQuery(content="What is this about?"), user_id=uuid4())


@pytest.mark.asyncio
async def test_llm_unavailable_propagates() -> None:
    orchestrator = RAGOrchestrator(
        rewriter=_Rewriter(),
        router=_Router(),
        transformer=_Transformer(),
        retriever=_Retriever(candidates=[_candidate()]),
        graph_scorer=_Graph(),
        reranker=_Reranker(),
        assembler=_Assembler(),
        llm=_LLM(error=LLMUnavailable("down")),
        critic=_Critic(["supported"]),
        sessions=_Sessions(),
    )

    with pytest.raises(LLMUnavailable):
        await orchestrator.answer(query=ChatQuery(content="What is this about?"), user_id=uuid4())


@pytest.mark.asyncio
async def test_unsupported_verdict_triggers_multi_query_retry() -> None:
    retriever = _Retriever(candidates=[_candidate()])
    orchestrator = RAGOrchestrator(
        rewriter=_Rewriter(),
        router=_Router(),
        transformer=_Transformer(),
        retriever=retriever,
        graph_scorer=_Graph(),
        reranker=_Reranker(),
        assembler=_Assembler(),
        llm=_LLM(content="Retry answer [node-1]"),
        critic=_Critic(["unsupported", "supported"]),
        sessions=_Sessions(),
    )

    turn = await orchestrator.answer(query=ChatQuery(content="What is this about?"), user_id=uuid4())

    assert turn.critic_verdict == "retried_supported"
    assert retriever.calls == 2


@pytest.mark.asyncio
async def test_answer_stream_yields_status_citations_tokens_done() -> None:
    orchestrator = RAGOrchestrator(
        rewriter=_Rewriter(),
        router=_Router(),
        transformer=_Transformer(),
        retriever=_Retriever(candidates=[_candidate()]),
        graph_scorer=_Graph(),
        reranker=_Reranker(),
        assembler=_Assembler(),
        llm=_LLM(stream_tokens=["Hello", " world"]),
        critic=_Critic(["supported"]),
        sessions=_Sessions(),
    )

    events = []
    async for event in orchestrator.answer_stream(query=ChatQuery(content="What is this about?"), user_id=uuid4()):
        events.append(event)

    assert [event["type"] for event in events] == ["status", "citations", "token", "token", "done"]


@pytest.mark.asyncio
async def test_answer_stream_emits_error_on_empty_scope() -> None:
    orchestrator = RAGOrchestrator(
        rewriter=_Rewriter(),
        router=_Router(),
        transformer=_Transformer(),
        retriever=_Retriever(error=EmptyScopeError("empty")),
        graph_scorer=_Graph(),
        reranker=_Reranker(),
        assembler=_Assembler(),
        llm=_LLM(),
        critic=_Critic(["supported"]),
        sessions=_Sessions(),
    )

    events = []
    async for event in orchestrator.answer_stream(query=ChatQuery(content="What is this about?"), user_id=uuid4()):
        events.append(event)

    assert events[-1]["type"] == "error"


@pytest.mark.asyncio
async def test_answer_stream_yields_first_token_before_generation_completes() -> None:
    llm = _BlockingStreamLLM()
    orchestrator = RAGOrchestrator(
        rewriter=_Rewriter(),
        router=_Router(),
        transformer=_Transformer(),
        retriever=_Retriever(candidates=[_candidate()]),
        graph_scorer=_Graph(),
        reranker=_Reranker(),
        assembler=_Assembler(),
        llm=llm,
        critic=_Critic(["supported"]),
        sessions=_Sessions(),
    )

    stream = orchestrator.answer_stream(query=ChatQuery(content="What is this about?"), user_id=uuid4())

    assert (await anext(stream))["type"] == "status"
    assert (await anext(stream))["type"] == "citations"

    next_token_task = asyncio.create_task(anext(stream))
    await asyncio.wait_for(llm.first_token_emitted.wait(), timeout=1.0)
    # Give the event loop enough cycles to propagate the token
    for _ in range(10):
        await asyncio.sleep(0)
        if next_token_task.done():
            break

    result = await asyncio.wait_for(next_token_task, timeout=2.0)
    assert result == {"type": "token", "content": "Hello"}

    llm.allow_completion.set()
    remaining = [event async for event in stream]
    assert [event["type"] for event in remaining] == ["token", "done"]
