"""Unit tests for the ``ask_kasten`` module runner (new_apis_1a).

Fully mocked — NO live Supabase, NO real Gemini. Patches:

* ``get_rag_runtime`` → mock runtime with ``orchestrator.answer/.answer_stream``.
* ``RAGRepository`` → mock with ``get_kasten`` for BOLA gate.
* ``require_entitlement`` → no-op (pricing-module-authority rule: tests
  never seed entitlements; this no-op bypass is the established pattern).

Covers: validation, happy path flatten, BOLA gate, streaming, scope_filter
mapping, ``quality`` normalization.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from website.api.module_runners import ask_kasten as ak
from website.api.module_runners.ask_kasten import (
    KastenNotFoundError,
    run_ask_kasten_once,
    stream_ask_kasten,
)

NARUTO = uuid.UUID("f2105544-b73d-4946-8329-096d82f070d3")
WS_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
KASTEN_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _mock_runtime(workspace_id=WS_ID):
    runtime = MagicMock()
    runtime.workspace_id = workspace_id
    runtime.orchestrator = MagicMock()
    return runtime


def _mock_answer_turn(content: str = "Hello world.") -> MagicMock:
    turn = MagicMock()
    turn.content = content
    turn.citations = []
    turn.query_class = "lookup"
    turn.critic_verdict = "supported"
    turn.critic_notes = None
    turn.trace_id = "trace-1"
    turn.latency_ms = 1234
    turn.token_counts = {"prompt": 100, "completion": 50}
    turn.llm_model = "gemini-2.5-flash"
    turn.retrieved_node_ids = ["nid-1"]
    turn.retrieved_chunk_ids = [uuid.uuid4()]
    return turn


@pytest.fixture
def _stub_entitlement(monkeypatch):
    async def _noop(*_a, **_kw):
        return None

    monkeypatch.setattr(
        "website.features.user_pricing.entitlements.require_entitlement",
        _noop,
    )


@pytest.mark.asyncio
async def test_validation_empty_content_rejected(_stub_entitlement):
    with pytest.raises(ValueError, match="content is required"):
        await run_ask_kasten_once(
            content="   ",
            user={"sub": str(NARUTO)},
            effective_user_id=NARUTO,
            client_action_id="ask-1",
        )


@pytest.mark.asyncio
async def test_validation_oversize_content_rejected(_stub_entitlement):
    with pytest.raises(ValueError, match="too long"):
        await run_ask_kasten_once(
            content="x" * 5001,
            user={"sub": str(NARUTO)},
            effective_user_id=NARUTO,
            client_action_id="ask-2",
        )


@pytest.mark.asyncio
async def test_validation_invalid_quality_rejected(_stub_entitlement):
    with pytest.raises(ValueError, match="quality must be fast or high"):
        await run_ask_kasten_once(
            content="What is X?",
            user={"sub": str(NARUTO)},
            effective_user_id=NARUTO,
            client_action_id="ask-3",
            quality="slow",  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_happy_path_flattens_answer_turn(_stub_entitlement):
    runtime = _mock_runtime()
    runtime.orchestrator.answer = AsyncMock(return_value=_mock_answer_turn())

    with patch(
        "website.features.rag_pipeline.service.get_rag_runtime",
        return_value=runtime,
    ):
        result = await run_ask_kasten_once(
            content="What is RAG?",
            user={"sub": str(NARUTO)},
            effective_user_id=NARUTO,
            client_action_id="ask-happy",
        )

    assert result["status"] == "succeeded"
    assert result["operation_id"] == "ask-happy"
    assert result["content"] == "Hello world."
    assert result["query_class"] == "lookup"
    assert result["critic_verdict"] == "supported"
    assert result["latency_ms"] == 1234
    assert result["retrieved_node_ids"] == ["nid-1"]
    # Orchestrator was called with the right ChatQuery shape.
    call_args = runtime.orchestrator.answer.call_args
    query = call_args.kwargs["query"]
    assert query.content == "What is RAG?"
    assert query.stream is False
    assert query.quality == "fast"
    assert query.sandbox_id is None  # No kasten_id supplied.


@pytest.mark.asyncio
async def test_bola_gate_rejects_cross_tenant_kasten(_stub_entitlement):
    """``kasten_id`` not owned by caller's workspace → KastenNotFoundError."""
    runtime = _mock_runtime()
    rag_repo = MagicMock()
    rag_repo.get_kasten.return_value = None  # cross-tenant or missing

    with patch(
        "website.features.rag_pipeline.service.get_rag_runtime",
        return_value=runtime,
    ), patch(
        "website.core.supabase_v2.repositories.rag_repository.RAGRepository",
        return_value=rag_repo,
    ):
        with pytest.raises(KastenNotFoundError) as excinfo:
            await run_ask_kasten_once(
                content="What is X?",
                user={"sub": str(NARUTO)},
                effective_user_id=NARUTO,
                client_action_id="ask-bola",
                kasten_id=KASTEN_ID,
            )
        assert excinfo.value.kasten_id == str(KASTEN_ID)
    # The orchestrator was NOT called — BOLA gate fires BEFORE the LLM call.
    runtime.orchestrator.answer.assert_not_called()


@pytest.mark.asyncio
async def test_bola_gate_rejects_when_workspace_id_missing(_stub_entitlement):
    """A user without ``runtime.workspace_id`` cannot prove kasten ownership."""
    runtime = _mock_runtime(workspace_id=None)

    with patch(
        "website.features.rag_pipeline.service.get_rag_runtime",
        return_value=runtime,
    ):
        with pytest.raises(KastenNotFoundError):
            await run_ask_kasten_once(
                content="What is X?",
                user={"sub": str(NARUTO)},
                effective_user_id=NARUTO,
                client_action_id="ask-no-ws",
                kasten_id=KASTEN_ID,
            )


@pytest.mark.asyncio
async def test_kasten_id_flows_into_chat_query_as_sandbox_id(_stub_entitlement):
    """ChatQuery.sandbox_id IS the kasten_id (orchestrator joins server-side)."""
    runtime = _mock_runtime()
    runtime.orchestrator.answer = AsyncMock(return_value=_mock_answer_turn())
    rag_repo = MagicMock()
    rag_repo.get_kasten.return_value = {"id": str(KASTEN_ID)}  # owned

    with patch(
        "website.features.rag_pipeline.service.get_rag_runtime",
        return_value=runtime,
    ), patch(
        "website.core.supabase_v2.repositories.rag_repository.RAGRepository",
        return_value=rag_repo,
    ):
        await run_ask_kasten_once(
            content="What is X?",
            user={"sub": str(NARUTO)},
            effective_user_id=NARUTO,
            client_action_id="ask-k",
            kasten_id=KASTEN_ID,
        )

    query = runtime.orchestrator.answer.call_args.kwargs["query"]
    assert query.sandbox_id == KASTEN_ID


@pytest.mark.asyncio
async def test_scope_filter_dict_constructs_scope_filter(_stub_entitlement):
    """``scope_filter`` dict is fed through ScopeFilter(**...)."""
    runtime = _mock_runtime()
    runtime.orchestrator.answer = AsyncMock(return_value=_mock_answer_turn())

    with patch(
        "website.features.rag_pipeline.service.get_rag_runtime",
        return_value=runtime,
    ):
        await run_ask_kasten_once(
            content="What is X?",
            user={"sub": str(NARUTO)},
            effective_user_id=NARUTO,
            client_action_id="ask-sf",
            scope_filter={"tags": ["foo", "bar"], "tag_mode": "any"},
        )

    query = runtime.orchestrator.answer.call_args.kwargs["query"]
    assert query.scope_filter.tags == ["foo", "bar"]
    assert query.scope_filter.tag_mode == "any"


@pytest.mark.asyncio
async def test_stream_yields_raw_orchestrator_events(_stub_entitlement):
    """``stream_ask_kasten`` is a passthrough for the orchestrator events."""
    runtime = _mock_runtime()

    async def _fake_stream(*, query, user_id):
        del query, user_id
        yield {"type": "status", "stage": "queued"}
        yield {"type": "token", "text": "Hello"}
        yield {"type": "done", "turn": {"content": "Hello"}}

    runtime.orchestrator.answer_stream = _fake_stream

    with patch(
        "website.features.rag_pipeline.service.get_rag_runtime",
        return_value=runtime,
    ):
        events = []
        async for event in stream_ask_kasten(
            content="Hi",
            user={"sub": str(NARUTO)},
            effective_user_id=NARUTO,
            client_action_id="ask-stream",
        ):
            events.append(event)

    assert len(events) == 3
    assert events[0]["type"] == "status"
    assert events[1]["type"] == "token"
    assert events[2]["type"] == "done"


def test_runner_has_cli_entrypoint_and_conventions():
    """Same conventions check as the summarization + create_kasten runners."""
    source = open(
        "website/api/module_runners/ask_kasten.py", encoding="utf-8"
    ).read()
    assert "argparse.ArgumentParser" in source
    assert 'if __name__ == "__main__"' in source
    assert "asyncio.Semaphore(2)" in source
    assert ".model_dump(mode=\"json\")" in source
    # D2 — strangler-fig contract: runner is importable from both routes
    # AND CLI, and dispatches the orchestrator call.
    assert "runtime.orchestrator.answer" in source
    assert "runtime.orchestrator.answer_stream" in source
    # Pricing meter is RAG_QUESTION (NEVER invented, NEVER seeded per
    # the pricing-module-authority rule).
    assert "RAG_QUESTION" in source
