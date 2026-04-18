"""Top-level RAG orchestration."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

try:
    from langfuse import get_client, observe
except Exception:  # pragma: no cover - optional dependency fallback
    def observe(*args, **kwargs):
        def _decorator(func):
            return func

        return _decorator

    class _DummyLangfuse:
        def get_current_trace_id(self):
            return None

    def get_client():
        return _DummyLangfuse()

from website.features.rag_pipeline.errors import EmptyScopeError
from website.features.rag_pipeline.generation.prompts import SYSTEM_PROMPT, USER_TEMPLATE
from website.features.rag_pipeline.generation.sanitize import sanitize_answer
from website.features.rag_pipeline.observability import record_generation_cost, trace_stage, track_latency
from website.features.rag_pipeline.types import AnswerTurn, Citation, QueryClass

langfuse = get_client()


@dataclass(slots=True)
class _PreparedQuery:
    session_id: object
    trace_id: str
    standalone: str
    query_class: QueryClass
    variants: list[str]


@dataclass(slots=True)
class _RetrievedContext:
    context_xml: str
    used_candidates: list


@dataclass(slots=True)
class _GeneratedAnswer:
    content: str
    model: str
    token_counts: dict
    finish_reason: str


@dataclass(slots=True)
class _PipelineResult:
    turn: AnswerTurn
    replaced_text: str | None = None


class RAGOrchestrator:
    def __init__(
        self,
        *,
        rewriter,
        router,
        transformer,
        retriever,
        graph_scorer,
        reranker,
        assembler,
        llm,
        critic,
        sessions,
    ):
        self._rewriter = rewriter
        self._router = router
        self._transformer = transformer
        self._retriever = retriever
        self._graph = graph_scorer
        self._reranker = reranker
        self._assembler = assembler
        self._llm = llm
        self._critic = critic
        self._sessions = sessions

    @observe(name="rag.answer")
    async def answer(self, *, query, user_id):
        prepared = await self._prepare_query(query=query, user_id=user_id)
        result = await self._run_nonstream(query=query, user_id=user_id, prepared=prepared)
        return result.turn

    @observe(name="rag.answer_stream")
    async def answer_stream(self, *, query, user_id):
        prepared = await self._prepare_query(query=query, user_id=user_id)
        yield {"type": "status", "stage": "retrieving"}

        try:
            context = await self._retrieve_context(
                query=query,
                user_id=user_id,
                query_variants=prepared.variants,
                query_class=prepared.query_class,
            )
        except EmptyScopeError:
            yield {
                "type": "error",
                "code": "empty_scope",
                "message": "This sandbox has no Zettels in the selected scope.",
            }
            return

        yield {
            "type": "citations",
            "citations": [citation.model_dump() for citation in self._build_citations(context.used_candidates)],
        }

        generation = None
        async for event in self._generate_streaming(query=query, context_xml=context.context_xml):
            if event["type"] == "token":
                yield event
                continue
            generation = event["answer"]

        if generation is None:
            generation = _GeneratedAnswer(content="", model="", token_counts={}, finish_reason="")

        result = await self._finalize_answer(
            query=query,
            user_id=user_id,
            prepared=prepared,
            context=context,
            generation=generation,
        )

        if result.replaced_text is not None:
            yield {"type": "replace", "content": result.replaced_text}

        yield {"type": "done", "turn": result.turn.model_dump()}

    @trace_stage("prepare_query")
    async def _prepare_query(self, *, query, user_id) -> _PreparedQuery:
        trace_id = getattr(langfuse, "get_current_trace_id", lambda: None)() or str(uuid4())

        session_id = query.session_id
        if session_id is None:
            session_id = await self._sessions.create_session(
                user_id=user_id,
                sandbox_id=query.sandbox_id,
                quality_mode=query.quality,
            )

        await self._sessions.append_user_message(
            session_id=session_id,
            user_id=user_id,
            content=query.content,
        )

        history = await self._sessions.load_recent_turns(session_id, user_id)
        history_payload = [
            turn.model_dump() if hasattr(turn, "model_dump") else turn
            for turn in history
        ]
        standalone = await self._rewriter.rewrite(query.content, history_payload)
        query_class = await self._router.classify(standalone)
        variants = await self._transformer.transform(standalone, query_class)

        return _PreparedQuery(
            session_id=session_id,
            trace_id=trace_id,
            standalone=standalone,
            query_class=query_class,
            variants=variants,
        )

    async def _run_nonstream(self, *, query, user_id, prepared: _PreparedQuery) -> _PipelineResult:
        context = await self._retrieve_context(
            query=query,
            user_id=user_id,
            query_variants=prepared.variants,
            query_class=prepared.query_class,
        )
        generation = await self._generate_once(query=query, context_xml=context.context_xml)
        return await self._finalize_answer(
            query=query,
            user_id=user_id,
            prepared=prepared,
            context=context,
            generation=generation,
        )

    @trace_stage("retrieve_context")
    async def _retrieve_context(
        self,
        *,
        query,
        user_id,
        query_variants,
        query_class: QueryClass,
    ) -> _RetrievedContext:
        async with track_latency("retrieve_context"):
            candidates = await self._retriever.retrieve(
                user_id=user_id,
                query_variants=query_variants,
                sandbox_id=query.sandbox_id,
                scope_filter=query.scope_filter,
                query_class=query_class,
                limit=30 if query.quality == "fast" else 50,
            )
            await self._graph.score(user_id=user_id, candidates=candidates)
            ranked = await self._reranker.rerank(
                query.content,
                candidates,
                top_k=8 if query.quality == "fast" else 12,
                query_class=query_class,
            )
            context_xml, used_candidates = await self._assembler.build(
                candidates=ranked,
                quality=query.quality,
                user_query=query.content,
            )
        return _RetrievedContext(context_xml=context_xml, used_candidates=used_candidates)

    @trace_stage("generate_once")
    async def _generate_once(self, *, query, context_xml: str) -> _GeneratedAnswer:
        user_prompt = USER_TEMPLATE.format(
            context_xml=context_xml,
            user_query=query.content,
        )
        async with track_latency("generate_once"):
            generation = await self._llm.generate(
                query=query,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )
        result = _GeneratedAnswer(
            content=generation.content,
            model=getattr(generation, "model", ""),
            token_counts=getattr(generation, "token_counts", {}),
            finish_reason=getattr(generation, "finish_reason", ""),
        )
        record_generation_cost(model=result.model, token_counts=result.token_counts)
        return result

    @trace_stage("generate_streaming")
    async def _generate_streaming(self, *, query, context_xml: str) -> AsyncIterator[dict]:
        user_prompt = USER_TEMPLATE.format(
            context_xml=context_xml,
            user_query=query.content,
        )
        parts = []
        final_meta = {"model": "", "token_counts": {}, "finish_reason": ""}
        async with track_latency("generate_streaming"):
            async for token, meta in self._llm.generate_stream(
                query=query,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
            ):
                parts.append(token)
                final_meta = meta or final_meta
                yield {"type": "token", "content": token}

        answer = _GeneratedAnswer(
            content="".join(parts),
            model=final_meta.get("model", ""),
            token_counts=final_meta.get("token_counts", {}),
            finish_reason=final_meta.get("finish_reason", ""),
        )
        record_generation_cost(
            model=answer.model,
            token_counts=answer.token_counts,
        )
        yield {"type": "complete", "answer": answer}

    @trace_stage("finalize_answer")
    async def _finalize_answer(
        self,
        *,
        query,
        user_id,
        prepared: _PreparedQuery,
        context: _RetrievedContext,
        generation: _GeneratedAnswer,
    ) -> _PipelineResult:
        t0 = time.monotonic()
        answer_text = sanitize_answer(generation.content)
        verdict, details = await self._critic.verify(
            answer_text=answer_text,
            context_xml=context.context_xml,
            context_candidates=context.used_candidates,
        )

        replaced_text = None
        used_candidates = context.used_candidates
        active_generation = generation

        if verdict == "unsupported":
            retry_context, retry_generation, retry_verdict, retry_details = await self._retry_with_thematic_context(
                query=query,
                user_id=user_id,
                prepared=prepared,
            )
            used_candidates = retry_context.used_candidates
            active_generation = retry_generation

            if retry_verdict == "supported":
                verdict = "retried_supported"
                details = retry_details
                answer_text = sanitize_answer(retry_generation.content)
                replaced_text = answer_text
            else:
                verdict = "retried_still_bad"
                details = retry_details
                answer_text = "Warning: low confidence.\n\n" + sanitize_answer(retry_generation.content)
                replaced_text = answer_text

        turn = AnswerTurn(
            content=answer_text,
            citations=self._build_citations(used_candidates),
            query_class=prepared.query_class,
            critic_verdict=verdict,
            critic_notes=details.get("critic_error") if isinstance(details, dict) else None,
            trace_id=prepared.trace_id,
            latency_ms=int((time.monotonic() - t0) * 1000),
            token_counts=active_generation.token_counts,
            llm_model=active_generation.model,
            retrieved_node_ids=[candidate.node_id for candidate in used_candidates],
            retrieved_chunk_ids=[candidate.chunk_id for candidate in used_candidates if candidate.chunk_id],
        )
        await self._sessions.append_assistant_message(
            session_id=prepared.session_id,
            user_id=user_id,
            turn=turn,
        )

        return _PipelineResult(turn=turn, replaced_text=replaced_text)

    async def _retry_with_thematic_context(self, *, query, user_id, prepared: _PreparedQuery):
        retry_variants = await self._transformer.transform(prepared.standalone, QueryClass.THEMATIC)
        retry_context = await self._retrieve_context(
            query=query,
            user_id=user_id,
            query_variants=retry_variants,
            query_class=QueryClass.THEMATIC,
        )
        retry_generation = await self._generate_once(query=query, context_xml=retry_context.context_xml)
        retry_verdict, retry_details = await self._critic.verify(
            answer_text=retry_generation.content,
            context_xml=retry_context.context_xml,
            context_candidates=retry_context.used_candidates,
        )
        return retry_context, retry_generation, retry_verdict, retry_details

    def _build_citations(self, candidates) -> list[Citation]:
        by_node = {}
        for candidate in candidates:
            current = by_node.get(candidate.node_id)
            candidate_score = candidate.rerank_score if candidate.rerank_score is not None else candidate.rrf_score
            if current is None:
                by_node[candidate.node_id] = candidate
                continue

            current_score = current.rerank_score if current.rerank_score is not None else current.rrf_score
            if candidate_score > current_score:
                by_node[candidate.node_id] = candidate

        ranked_candidates = sorted(
            by_node.values(),
            key=lambda candidate: candidate.rerank_score if candidate.rerank_score is not None else candidate.rrf_score,
            reverse=True,
        )
        return [
            Citation(
                id=candidate.node_id,
                node_id=candidate.node_id,
                title=candidate.name,
                source_type=candidate.source_type,
                url=candidate.url,
                snippet=candidate.content[:400],
                timestamp=str(candidate.metadata.get("timestamp")) if candidate.metadata.get("timestamp") else None,
                rerank_score=float(candidate.rerank_score or 0.0),
            )
            for candidate in ranked_candidates
        ]
