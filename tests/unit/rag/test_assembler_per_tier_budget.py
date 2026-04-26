"""T17: per-LLM-tier dynamic budget in :class:`ContextAssembler`.

The assembler accepts an optional ``model`` hint and resolves it through a
tier table. When the hint is ``None`` or unknown, the legacy quality-based
budget applies — this guarantees pre-T17 callers see no behaviour change.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from website.features.rag_pipeline.context import assembler as assembler_mod
from website.features.rag_pipeline.context.assembler import (
    ContextAssembler,
    _BUDGET_BY_LLM_TIER,
    _BUDGET_BY_QUALITY,
    _resolve_budget,
)
from website.features.rag_pipeline.types import ChunkKind, RetrievalCandidate, SourceType


def _candidate(node_id: str = "n", content: str = "x" * 200) -> RetrievalCandidate:
    return RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id=node_id,
        chunk_id=uuid4(),
        chunk_idx=0,
        name=node_id,
        source_type=SourceType.WEB,
        url=f"https://example.com/{node_id}",
        content=content,
        rrf_score=0.6,
        rerank_score=0.6,
        final_score=0.6,
    )


def test_resolve_budget_known_tiers_match_table() -> None:
    for model, expected in _BUDGET_BY_LLM_TIER.items():
        assert _resolve_budget(quality="fast", model=model) == expected


def test_resolve_budget_substring_match_handles_backend_prefix() -> None:
    # Backends sometimes return prefixed names like "models/gemini-2.5-pro"
    # — the substring match must still resolve to the pro tier.
    assert _resolve_budget(quality="fast", model="models/gemini-2.5-pro") == _BUDGET_BY_LLM_TIER["gemini-2.5-pro"]


def test_resolve_budget_flash_lite_does_not_collide_with_flash() -> None:
    # "gemini-2.5-flash-lite" must resolve to the lite tier even though
    # "gemini-2.5-flash" is also a substring of it.
    assert (
        _resolve_budget(quality="fast", model="gemini-2.5-flash-lite")
        == _BUDGET_BY_LLM_TIER["gemini-2.5-flash-lite"]
    )


def test_resolve_budget_unknown_model_falls_back_to_quality() -> None:
    assert _resolve_budget(quality="fast", model="claude-opus-4") == _BUDGET_BY_QUALITY["fast"]
    assert _resolve_budget(quality="high", model="claude-opus-4") == _BUDGET_BY_QUALITY["high"]


def test_resolve_budget_none_model_falls_back_to_quality() -> None:
    assert _resolve_budget(quality="fast", model=None) == _BUDGET_BY_QUALITY["fast"]
    assert _resolve_budget(quality="high", model=None) == _BUDGET_BY_QUALITY["high"]


@pytest.mark.asyncio
async def test_assembler_passes_resolved_budget_to_compressor(monkeypatch: pytest.MonkeyPatch) -> None:
    """When a compressor is wired and the candidate stack overflows the
    resolved budget, the assembler must invoke ``compressor.compress`` with
    the *tier-derived* ``target_budget_tokens``."""

    class _StubCompressor:
        def __init__(self) -> None:
            self.calls: list[int] = []

        async def compress(self, *, user_query, grouped, target_budget_tokens):
            self.calls.append(target_budget_tokens)
            return grouped

    compressor = _StubCompressor()
    asm = ContextAssembler(compressor=compressor)

    # Build candidates with enough volume to exceed even the largest tier
    # budget so the compressor branch fires deterministically. Each chunk
    # estimates at len(content)//4 tokens; 60 chunks * 800 chars / 4 = 12000
    # tokens, larger than every tier budget.
    candidates = [
        _candidate(node_id=f"n{i}", content="x" * 800) for i in range(60)
    ]

    # flash-lite tier (4000 tokens) — the lowest budget
    await asm.build(
        candidates=list(candidates),
        quality="fast",
        user_query="q",
        model="gemini-2.5-flash-lite",
    )
    assert compressor.calls[-1] == _BUDGET_BY_LLM_TIER["gemini-2.5-flash-lite"]

    # pro tier (8000 tokens)
    await asm.build(
        candidates=list(candidates),
        quality="fast",
        user_query="q",
        model="gemini-2.5-pro",
    )
    assert compressor.calls[-1] == _BUDGET_BY_LLM_TIER["gemini-2.5-pro"]

    # No model -> falls back to quality budget (fast=6000)
    await asm.build(
        candidates=list(candidates),
        quality="fast",
        user_query="q",
    )
    assert compressor.calls[-1] == _BUDGET_BY_QUALITY["fast"]
