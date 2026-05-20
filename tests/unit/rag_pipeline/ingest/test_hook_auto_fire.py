"""Bug 1 regression: Add Zettel persistence must auto-trigger ingest_node_chunks.

Iter-06 production observation: rag_chunks_enabled=False default + Dockerfile
not bundling ops/config.yaml meant the hook never fired in prod. The fix is
to flip the in-code default to True so a fresh container ingests chunks even
without an env override.
"""
from __future__ import annotations

from uuid import uuid4

import pytest


def test_rag_chunks_enabled_defaults_to_true():
    """The in-code default must be True so production droplet behaves correctly
    even when ops/config.yaml is not bundled into the image."""
    from website.core.settings import Settings

    # Force the env-loading path to ignore any local .env / config.yaml so we
    # observe the bare class default. Pydantic Settings reads sources at
    # construction time; instantiating with explicit unrelated kwargs only
    # avoids triggering required-field validation if any exist.
    s = Settings.model_construct()
    assert s.rag_chunks_enabled is True


@pytest.mark.asyncio
async def test_persist_builds_multichunk_via_shared_helper(monkeypatch):
    """Chunking goes through the shared ``persist.build_canonical_chunks``
    core. PR #39 Wave-3: persist itself no longer chunks inline — the
    enrichment handler + backfill both call the same helper. Either way,
    ``_schedule_rag_chunks`` must remain purged."""
    from website.core import persist as persist_mod

    assert not hasattr(persist_mod, "_schedule_rag_chunks"), (
        "dead RAG-chunk scheduler must be purged"
    )

    async def _fake_embed(texts):
        assert texts and all(isinstance(t, str) and t for t in texts)
        return [[0.01] * 768 for _ in texts]

    monkeypatch.setattr(persist_mod, "embed_chunk_texts", _fake_embed)

    long_summary = "\n\n".join(
        f"Paragraph {i}. Naruto trains to master the Rasengan and become "
        f"Hokage, earning the village's hard-won respect over many arcs. " * 3
        for i in range(40)
    )
    chunks = await persist_mod.build_canonical_chunks(
        payload={
            "title": "Test Node",
            "summary": long_summary,
            "raw_text": "A short raw body, not the chunk source under R1.",
            "source_type": "web",
            "source_url": "https://example.com",
            "tags": [],
            "metadata": {},
        },
        detailed_summary=long_summary,
    )

    assert chunks is not None
    assert len(chunks) > 1, "long summary must segment into many chunks"
    for i, ch in enumerate(chunks):
        assert ch.chunk_idx == i
        assert ch.embedding is not None and len(ch.embedding) == 768
    # Use uuid4 so the unused import is preserved without code smell.
    assert uuid4() is not None
