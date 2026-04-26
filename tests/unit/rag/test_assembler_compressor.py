"""Wiring tests for ContextAssembler ↔ EvidenceCompressor (Task 16).

Covers four behaviours:
  1. Compressor=None: legacy path; no compression invoked.
  2. Compressor present and budget tight: compress() called once with the
     correct kwargs and its result drives downstream packing.
  3. Compressor.compress raises: assembler swallows the exception and falls
     back to the pre-T16 truncation behaviour (never propagates).
  4. Determinism: same inputs + same mock => byte-identical XML output.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from website.features.rag_pipeline.context.assembler import ContextAssembler
from website.features.rag_pipeline.types import (
    ChunkKind,
    RetrievalCandidate,
    SourceType,
)


def _cand(content: str, *, node_id: str = "n", chunk_idx: int = 0,
          score: float = 0.9) -> RetrievalCandidate:
    return RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id=node_id,
        chunk_id=uuid4(),
        chunk_idx=chunk_idx,
        name="N",
        source_type=SourceType.WEB,
        url="https://example.com",
        content=content,
        tags=[],
        metadata={},
        rrf_score=score,
        final_score=score,
    )


@pytest.mark.asyncio
async def test_no_compressor_matches_baseline_path():
    """compressor=None: assembler runs the legacy path (no compression call)."""
    asm = ContextAssembler(compressor=None)
    cands = [_cand("Short passage that fits the budget. " * 3, node_id="a")]
    xml, used = await asm.build(candidates=cands, quality="fast", user_query="q")
    assert "<context>" in xml
    assert "Short passage" in xml
    assert len(used) == 1


@pytest.mark.asyncio
async def test_compressor_invoked_when_over_budget():
    """When compressor is wired AND total tokens exceed budget, compress() is called."""
    big_text = "x" * 60000  # ~15000 tokens > 6000 fast budget
    cands = [_cand(big_text, node_id="a")]

    # Compressor returns a tiny grouped list so downstream packing is trivial.
    shrunk = _cand("compressed body.", node_id="a")
    fake = AsyncMock()
    fake.compress = AsyncMock(return_value=[[shrunk]])

    asm = ContextAssembler(compressor=fake)
    xml, used = await asm.build(candidates=cands, quality="fast", user_query="why?")

    assert fake.compress.call_count == 1
    kwargs = fake.compress.await_args.kwargs
    assert kwargs.get("user_query") == "why?"
    assert kwargs.get("target_budget_tokens") == 6000
    assert "grouped" in kwargs and isinstance(kwargs["grouped"], list)
    # The compressed content drives the rendered XML.
    assert "compressed body." in xml
    assert used and used[0].content == "compressed body."


@pytest.mark.asyncio
async def test_compressor_not_invoked_when_under_budget():
    """If candidates already fit the budget, the compressor is skipped."""
    cands = [_cand("tiny passage that easily fits.", node_id="a")]
    fake = AsyncMock()
    fake.compress = AsyncMock(return_value=[[]])
    asm = ContextAssembler(compressor=fake)
    await asm.build(candidates=cands, quality="fast", user_query="q")
    assert fake.compress.call_count == 0


@pytest.mark.asyncio
async def test_compressor_failure_falls_back_to_truncation():
    """If compressor raises, assembler logs and falls back to the legacy path."""
    big_text = "x" * 60000
    cands = [_cand(big_text, node_id="a")]
    fake = AsyncMock()
    fake.compress = AsyncMock(side_effect=RuntimeError("ce-onnx oom"))
    asm = ContextAssembler(compressor=fake)
    # Must not raise.
    xml, used = await asm.build(candidates=cands, quality="fast", user_query="q")
    assert "<context>" in xml
    # Truncation fallback still includes the (uncompressed) first group.
    assert used


@pytest.mark.asyncio
async def test_deterministic_output_with_mocked_compressor():
    """Same inputs + same mock => identical XML (no hidden non-determinism)."""
    big_text = "x" * 60000
    cands = [_cand(big_text, node_id="a")]
    shrunk = _cand("deterministic compressed body.", node_id="a")

    def _make_asm():
        fake = AsyncMock()
        fake.compress = AsyncMock(return_value=[[shrunk]])
        return ContextAssembler(compressor=fake)

    xml1, _ = await _make_asm().build(
        candidates=cands, quality="fast", user_query="q"
    )
    xml2, _ = await _make_asm().build(
        candidates=cands, quality="fast", user_query="q"
    )
    assert xml1 == xml2
