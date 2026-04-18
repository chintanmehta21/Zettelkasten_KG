from uuid import uuid4

import pytest

from website.features.rag_pipeline.context.assembler import ContextAssembler
from website.features.rag_pipeline.types import ChunkKind, RetrievalCandidate, SourceType


def _candidate(
    node_id: str,
    name: str,
    content: str,
    score: float,
    chunk_idx: int = 0,
    kind: ChunkKind = ChunkKind.CHUNK,
) -> RetrievalCandidate:
    candidate = RetrievalCandidate(
        kind=kind,
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


@pytest.mark.asyncio
async def test_partial_group_inclusion_keeps_summary_from_lower_ranked_group() -> None:
    """A large top-ranked group shouldn't starve a lower-ranked group's
    summary from entering the context. The summary is the highest-signal item
    and should land even when the rest of its group can't fit."""
    assembler = ContextAssembler()
    fast_budget = 6000
    # Top group eats ~4000 tokens (still leaves room for one summary).
    top_chunk = _candidate("node-top", "Top", "a" * 16000, 0.9)
    # Lower group has a short summary + a huge chunk. Under the old logic,
    # the whole group was dropped if the huge chunk pushed it over budget.
    lower_summary = _candidate(
        "node-low", "Low", "short summary about the query topic", 0.4,
        chunk_idx=0, kind=ChunkKind.SUMMARY,
    )
    lower_chunk = _candidate(
        "node-low", "Low", "b" * 16000, 0.4, chunk_idx=1,
    )

    xml, used = await assembler.build(
        candidates=[top_chunk, lower_summary, lower_chunk],
        quality="fast",
        user_query="query",
    )

    assert 'id="node-top"' in xml
    assert 'id="node-low"' in xml
    used_ids = {(c.node_id, c.kind) for c in used}
    assert ("node-low", ChunkKind.SUMMARY) in used_ids
    assert ("node-low", ChunkKind.CHUNK) not in used_ids
    del fast_budget


@pytest.mark.asyncio
async def test_first_group_kept_whole_even_when_it_overflows_budget() -> None:
    """Minimum-coverage guarantee: the top-ranked group is never truncated
    even if it alone exceeds the budget — otherwise a single fat zettel gives
    the model nothing to ground against."""
    assembler = ContextAssembler()
    big_a = _candidate("node-only", "Only", "a" * 40000, 0.9, chunk_idx=0)
    big_b = _candidate("node-only", "Only", "b" * 40000, 0.9, chunk_idx=1)

    xml, used = await assembler.build(
        candidates=[big_a, big_b], quality="fast", user_query="query",
    )

    assert 'id="node-only"' in xml
    assert len(used) == 2


@pytest.mark.asyncio
async def test_skips_group_that_cannot_contribute_any_item() -> None:
    """A later group with no item that fits the remaining budget must not
    appear in the rendered XML at all (no empty <zettel> shells)."""
    assembler = ContextAssembler()
    top = _candidate("node-top", "Top", "a" * 40000, 0.9)  # overflows budget
    lower = _candidate("node-low", "Low", "b" * 40000, 0.4)  # can't fit anything

    xml, used = await assembler.build(
        candidates=[top, lower], quality="fast", user_query="query",
    )

    assert 'id="node-top"' in xml
    assert 'id="node-low"' not in xml
    assert {c.node_id for c in used} == {"node-top"}

