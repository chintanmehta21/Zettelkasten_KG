from uuid import uuid4

import pytest

from website.features.rag_pipeline.context.assembler import ContextAssembler
from website.features.rag_pipeline.types import ChunkKind, RetrievalCandidate, SourceType


def _candidate(node_id: str, name: str, content: str, score: float, chunk_idx: int = 0) -> RetrievalCandidate:
    candidate = RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id=node_id,
        chunk_id=uuid4(),
        chunk_idx=chunk_idx,
        name=name,
        source_type=SourceType.WEB,
        url=f"https://example.com/{node_id}",
        content=content,
        tags=["ai"],
        rrf_score=score,
    )
    candidate.final_score = score
    return candidate


@pytest.mark.asyncio
async def test_build_returns_empty_xml_for_no_candidates() -> None:
    xml, used = await ContextAssembler().build(candidates=[], quality="fast", user_query="query")
    assert "no relevant Zettels found" in xml
    assert used == []


@pytest.mark.asyncio
async def test_sandwich_places_best_first_and_second_last() -> None:
    assembler = ContextAssembler()
    candidates = [
        _candidate("node-1", "One", "content-1", 0.9),
        _candidate("node-2", "Two", "content-2", 0.8),
        _candidate("node-3", "Three", "content-3", 0.7),
    ]
    xml, _ = await assembler.build(candidates=candidates, quality="fast", user_query="query")
    assert xml.index('id="node-1"') < xml.index('id="node-3"') < xml.index('id="node-2"')


@pytest.mark.asyncio
async def test_budget_truncates_groups_by_rank() -> None:
    assembler = ContextAssembler()
    candidates = [
        _candidate("node-1", "One", "a" * 16000, 0.9),
        _candidate("node-2", "Two", "b" * 16000, 0.8),
    ]
    xml, used = await assembler.build(candidates=candidates, quality="fast", user_query="query")
    assert 'id="node-1"' in xml
    assert len({candidate.node_id for candidate in used}) == 1


@pytest.mark.asyncio
async def test_render_xml_escapes_special_chars() -> None:
    assembler = ContextAssembler()
    candidate = _candidate("node-1", "A < B", "5 > 3 & 2 < 4", 0.9)
    xml, _ = await assembler.build(candidates=[candidate], quality="fast", user_query="query")
    assert "A &lt; B" in xml
    assert "5 &gt; 3 &amp; 2 &lt; 4" in xml

