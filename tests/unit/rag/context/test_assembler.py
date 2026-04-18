from uuid import uuid4

import pytest

from website.features.rag_pipeline.context.assembler import ContextAssembler, _is_stub_passage
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
        _candidate("node-1", "One", "First passage with enough substance to pass the stub filter.", 0.9),
        _candidate("node-2", "Two", "Second passage likewise long enough to count as real content.", 0.8),
        _candidate("node-3", "Three", "Third passage with plenty of characters to clear the filter.", 0.7),
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
    candidate = _candidate(
        "node-1",
        "A < B",
        "Inequality 5 > 3 & 2 < 4 shows up in formal reasoning and requires XML escaping.",
        0.9,
    )
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
        "node-low",
        "Low",
        "Concise summary about the query topic with enough substance to clear the stub filter.",
        0.4,
        chunk_idx=0,
        kind=ChunkKind.SUMMARY,
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


def test_is_stub_passage_flags_placeholders_and_short_bodies() -> None:
    # Extraction failures masquerading as chunks
    assert _is_stub_passage("## Transcript\n\n(Transcript not available for this video)")
    assert _is_stub_passage("[deleted]")
    assert _is_stub_passage("Content unavailable")
    # Empty / whitespace-only
    assert _is_stub_passage("")
    assert _is_stub_passage("   \n\t ")
    assert _is_stub_passage(None)  # defensive: pydantic sometimes gives None
    # Very short fragments carry no grounding signal
    assert _is_stub_passage("yes")
    # Real content survives
    assert not _is_stub_passage("Transformer attention scales better on long sequences because self-attention sidesteps recurrence.")


@pytest.mark.asyncio
async def test_stub_passages_are_dropped_before_assembly() -> None:
    """A YouTube chunk with 'Transcript not available' text must never appear
    in the rendered context — otherwise the model sees noise and may cite a
    zettel that actually has no grounding content."""
    assembler = ContextAssembler()
    real = _candidate(
        "node-real",
        "Real zettel",
        "Transformer self-attention replaces recurrence and scales with sequence length via parallel token interactions.",
        0.9,
    )
    stub = _candidate(
        "node-stub",
        "Stub zettel",
        "## Transcript\n\n(Transcript not available for this video)",
        0.8,
    )

    xml, used = await assembler.build(
        candidates=[real, stub], quality="fast", user_query="query",
    )

    assert 'id="node-real"' in xml
    assert 'id="node-stub"' not in xml
    assert [c.node_id for c in used] == ["node-real"]


@pytest.mark.asyncio
async def test_empty_context_when_every_candidate_is_a_stub() -> None:
    assembler = ContextAssembler()
    stubs = [
        _candidate("n1", "a", "[deleted]", 0.9),
        _candidate("n2", "b", "", 0.8),
        _candidate("n3", "c", "No content available", 0.7),
    ]

    xml, used = await assembler.build(
        candidates=stubs, quality="fast", user_query="query",
    )

    assert "no relevant Zettels found" in xml
    assert used == []


@pytest.mark.asyncio
async def test_stub_chunk_in_group_removed_but_real_siblings_kept() -> None:
    """Mixed group: one stub chunk + one real chunk for the same node. The
    stub is dropped at filter time so the group still renders with its real
    passage and isn't treated as an empty-group drop."""
    assembler = ContextAssembler()
    real_chunk = _candidate(
        "node-mixed",
        "Mixed",
        "Detailed explanation of the transformer architecture and self-attention mechanism.",
        0.9,
        chunk_idx=0,
    )
    stub_chunk = _candidate(
        "node-mixed", "Mixed", "[removed]", 0.9, chunk_idx=1,
    )

    xml, used = await assembler.build(
        candidates=[real_chunk, stub_chunk], quality="fast", user_query="query",
    )

    assert 'id="node-mixed"' in xml
    # Only the real chunk should have been marked used
    assert len(used) == 1
    assert used[0].chunk_idx == 0


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

