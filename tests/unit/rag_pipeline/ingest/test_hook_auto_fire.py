"""Bug 1 regression: Add Zettel persistence must auto-trigger ingest_node_chunks.

Iter-06 production observation: rag_chunks_enabled=False default + Dockerfile
not bundling ops/config.yaml meant the hook never fired in prod. The fix is
to flip the in-code default to True so a fresh container ingests chunks even
without an env override.
"""
from __future__ import annotations

from unittest.mock import MagicMock
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
async def test_persist_builds_multichunk_inline_not_via_dead_hook(monkeypatch):
    """CONTRACT CHANGE (old -> new): the old test drove the now-DELETED
    ``persist._schedule_rag_chunks`` (a dead fire-and-forget scheduler with
    zero production callers and a node_id-keyed signature mismatch — the
    RAG+KG root-cause defect). Chunking is now INLINE on the persist path via
    the shared ``build_canonical_chunks`` core, segmenting the source body
    into many chunks handed straight to ``upsert_canonical_zettel``. This
    test pins the new wiring: ``_schedule_rag_chunks`` is gone and a real
    body produces multiple embedded chunks synchronously."""
    from datetime import date

    from website.core import persist as persist_mod
    from website.core.supabase_v2.models import CanonicalUpsertResult

    assert not hasattr(persist_mod, "_schedule_rag_chunks"), (
        "dead RAG-chunk scheduler must be purged"
    )

    async def _fake_embed(texts):
        assert texts and all(isinstance(t, str) and t for t in texts)
        return [[0.01] * 768 for _ in texts]

    monkeypatch.setattr(persist_mod, "embed_chunk_texts", _fake_embed)
    monkeypatch.setattr(persist_mod, "_schedule_kg_population", lambda **_k: None)

    captured = {}

    class _Repo:
        def upsert_canonical_zettel(self, zettel, *, workspace=None, chunks=None):
            captured["chunks"] = chunks
            return CanonicalUpsertResult(
                canonical_zettel_id=uuid4(),
                workspace_zettel_id=uuid4(),
                was_new=True,
            )

    # OLD->NEW (R1): pre-R1 a long RAW body was the chunk source. Post-R1
    # the SUMMARY is the primary chunk source, so a long summary must
    # segment into many chunks (the short raw body is now irrelevant).
    long_summary = "\n\n".join(
        f"Paragraph {i}. Naruto trains to master the Rasengan and become "
        f"Hokage, earning the village's hard-won respect over many arcs. " * 3
        for i in range(40)
    )
    await persist_mod._persist_supabase_v2_zettel(
        payload={
            "title": "Test Node",
            "summary": long_summary,
            "raw_text": "A short raw body, not the chunk source under R1.",
            "source_type": "web",
            "source_url": "https://example.com",
            "tags": [],
            "metadata": {},
        },
        repo=_Repo(),
        workspace_id=uuid4(),
        captured_on=date.today(),
        detailed_summary=long_summary,
    )

    assert captured["chunks"] is not None
    assert len(captured["chunks"]) > 1, "long summary must segment into many chunks"
    for i, ch in enumerate(captured["chunks"]):
        assert ch.chunk_idx == i
        assert ch.embedding is not None and len(ch.embedding) == 768
