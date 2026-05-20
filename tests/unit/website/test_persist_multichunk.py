"""Multi-chunk contract — PR #39 Wave-3 lazy-enrichment rewrite.

Original ROOT CAUSE this file pinned: ``_persist_supabase_v2_zettel`` built
exactly ONE ``CanonicalChunkCreate`` regardless of body length, starving
RAG passage granularity. The corrected contract — segment into multiple
chunks with monotonic chunk_idx, single batch embed, embed-or-skip on
batch-embed failure, content-hash determinism, chunk-count cap — is now
enforced by ``persist.build_canonical_chunks`` (the shared core also
called by the lazy enrichment handler ``chunk_embed.handle`` and the
``backfill_rechunk_v2.py`` script).

These tests therefore target ``build_canonical_chunks`` directly. The
prior end-to-end `_persist_supabase_v2_zettel` tests are superseded by:
  * ``tests/unit/summarization_engine/test_lazy_enrichment.py`` for the
    enqueue + worker + handler dispatch.
  * ``test_content_hash_unchanged_vs_prefix`` below for the dedup hash
    invariant (still tested via the inline canonical zettel write).
"""
from __future__ import annotations

import hashlib
from datetime import date
from uuid import UUID

import pytest

from website.core import persist
from website.core.supabase_v2.models import CanonicalUpsertResult


_PROFILE = UUID("00000000-0000-0000-0000-000000000001")
_WORKSPACE = UUID("00000000-0000-0000-0000-000000000002")
_WZID = UUID("00000000-0000-0000-0000-000000000222")
_CANON = UUID("00000000-0000-0000-0000-000000000111")


class _CaptureRepo:
    """Minimal repo stub: captures whichever chunks the persist path
    passes to upsert_canonical_zettel. Post-Wave-3 this is always []
    (the inline persist no longer builds chunks); pre-Wave-3 it captured
    the inline chunk list."""

    def __init__(self) -> None:
        self.chunks = None
        self.zettel = None

    def upsert_canonical_zettel(self, zettel, *, workspace=None, chunks=None):
        self.zettel = zettel
        self.chunks = chunks
        return CanonicalUpsertResult(
            canonical_zettel_id=_CANON,
            workspace_zettel_id=_WZID,
            was_new=True,
        )


def _long_body(paragraphs: int = 40) -> str:
    sent = (
        "Naruto Uzumaki trains relentlessly to master the Rasengan and "
        "earn the village's respect on his path to becoming Hokage. "
    )
    return "\n\n".join(f"Paragraph {i}. {sent * 3}" for i in range(paragraphs))


def _payload(*, raw_text: str | None = None, summary: str = "S") -> dict:
    p = {
        "source_url": "https://example.com/post",
        "source_type": "web",
        "title": "Naruto Uzumaki",
        "summary": summary,
        "tags": ["anime"],
        "metadata": {},
    }
    if raw_text is not None:
        p["raw_text"] = raw_text
    return p


# ---------------------------------------------------------------------------
# build_canonical_chunks (the shared chunker+embed core)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_long_body_segments_into_many_chunks_single_batch_embed(monkeypatch):
    """R1 contract: a long SUMMARY is segmented into MULTIPLE chunks via a
    SINGLE batch embed call. Each chunk well-formed with monotonic idx."""
    long_summary = _long_body()
    embed_calls = {"n": 0, "batch_sizes": []}

    async def _fake_embed(texts):
        embed_calls["n"] += 1
        embed_calls["batch_sizes"].append(len(texts))
        return [[0.01] * 768 for _ in texts]

    monkeypatch.setattr(persist, "embed_chunk_texts", _fake_embed)

    chunks = await persist.build_canonical_chunks(
        payload=_payload(raw_text="A short raw body that must NOT be chunked under R1."),
        detailed_summary=long_summary,
    )

    assert len(chunks) > 1, "long summary must produce multiple chunks"
    assert embed_calls["n"] == 1
    assert embed_calls["batch_sizes"][0] == len(chunks)
    for i, ch in enumerate(chunks):
        assert ch.chunk_idx == i
        assert ch.token_count and ch.token_count > 0
        assert ch.embedding is not None and len(ch.embedding) == 768
        assert ch.embedding_model_version == persist._CHUNK_EMBED_MODEL_VERSION
        assert ch.content
    joined = " ".join(c.content for c in chunks)
    assert "Paragraph 0" in joined


@pytest.mark.asyncio
async def test_short_body_still_produces_at_least_one_chunk(monkeypatch):
    async def _fake_embed(texts):
        return [[0.02] * 768 for _ in texts]

    monkeypatch.setattr(persist, "embed_chunk_texts", _fake_embed)

    chunks = await persist.build_canonical_chunks(
        payload=_payload(raw_text="Short but real body about Naruto."),
        detailed_summary="Naruto becomes Hokage.",
    )
    assert len(chunks) >= 1
    assert chunks[0].embedding is not None


@pytest.mark.asyncio
async def test_batch_embed_failure_yields_zero_chunks(monkeypatch):
    """Embed-or-skip contract: a batch embed failure returns [], so the
    handler persists nothing and backfill_rechunk_v2.py recovers later."""

    async def _fail(texts):
        return None

    monkeypatch.setattr(persist, "embed_chunk_texts", _fail)

    chunks = await persist.build_canonical_chunks(
        payload=_payload(raw_text=_long_body()),
        detailed_summary="summary",
    )
    assert chunks == []


@pytest.mark.asyncio
async def test_truly_empty_source_no_embed_no_chunks(monkeypatch):
    """No body/summary/title/tags -> the chunker's synthesized fallback is
    also empty -> ZERO chunks, ZERO embed calls."""
    called = {"n": 0}

    async def _spy(texts):
        called["n"] += 1
        return [[0.0] * 768 for _ in texts]

    monkeypatch.setattr(persist, "embed_chunk_texts", _spy)

    chunks = await persist.build_canonical_chunks(
        payload={
            "source_url": "https://example.com/post",
            "source_type": "web",
            "title": "",
            "summary": "",
            "tags": [],
            "metadata": {},
        },
        detailed_summary="",
    )
    assert chunks == []
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_chunk_count_safety_cap_enforced(monkeypatch):
    """Pathological body cannot explode chunk count past the cap."""

    async def _fake_embed(texts):
        return [[0.0] * 768 for _ in texts]

    monkeypatch.setattr(persist, "embed_chunk_texts", _fake_embed)
    monkeypatch.setattr(persist, "_MAX_CHUNKS_PER_ZETTEL", 5)

    huge = _long_body(paragraphs=400)
    chunks = await persist.build_canonical_chunks(
        payload=_payload(raw_text="short raw"),
        detailed_summary=huge,
    )
    assert len(chunks) <= 5


# ---------------------------------------------------------------------------
# Whole-pipeline invariants still relevant after Wave-3
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_content_hash_unchanged_vs_prefix(monkeypatch):
    """P1-7 regression: rewiring chunking must NOT change the dedup hash
    for the same input. The hash derives only from URL + fingerprint."""
    monkeypatch.setattr(persist, "_schedule_kg_population", lambda **_k: None)
    # PR #39 Wave-3: persist no longer chunks inline, so embed mock is
    # unused — but persist now enqueues a chunk_embed job; stub the
    # enqueue so the test doesn't hit Supabase.
    from website.features.summarization_engine.lazy_enrichment import (
        repo as enrichment_repo,
    )
    monkeypatch.setattr(
        enrichment_repo, "enqueue_chunk_embed", lambda **_k: (None, False)
    )

    repo = _CaptureRepo()
    payload = _payload(raw_text="RAW SOURCE TEXT")
    payload["source_fingerprint_text"] = "RAW SOURCE TEXT"
    await persist._persist_supabase_v2_zettel(
        payload=payload,
        repo=repo,
        workspace_id=_WORKSPACE,
        captured_on=date.today(),
        detailed_summary="some llm wording",
        profile_id=_PROFILE,
    )
    expected = hashlib.sha256(
        "https://example.com/post\x00RAW SOURCE TEXT".encode("utf-8")
    ).digest()
    assert repo.zettel.content_hash == expected
    # PR #39 / Wave-3: persist passes [] for chunks (chunk+embed moved
    # to the lazy enrichment job).
    assert repo.chunks == []


def test_schedule_rag_chunks_symbol_removed():
    """The dead RAG-chunk scheduler must be purged (no caller, signature
    mismatch). Its removal is part of this fix."""
    assert not hasattr(persist, "_schedule_rag_chunks")


def test_build_canonical_chunks_helper_exists():
    """Shared chunk+embed core — still reachable from both the lazy
    enrichment handler and backfill_rechunk_v2.py."""
    assert hasattr(persist, "build_canonical_chunks")


@pytest.mark.asyncio
async def test_persist_enqueues_chunk_embed_after_canonical_write(monkeypatch):
    """PR #39 Wave-3 invariant: after persist writes the canonical zettel,
    it enqueues exactly ONE chunk_embed job carrying the source fingerprint
    + summary, so the in-process worker can finalize the lazy chunking."""
    monkeypatch.setattr(persist, "_schedule_kg_population", lambda **_k: None)

    from website.features.summarization_engine.lazy_enrichment import (
        repo as enrichment_repo,
    )

    enqueued: list[dict] = []

    def _capture(**kw):
        enqueued.append(kw)
        return (str(_CANON), True)

    monkeypatch.setattr(enrichment_repo, "enqueue_chunk_embed", _capture)

    repo = _CaptureRepo()
    await persist._persist_supabase_v2_zettel(
        payload=_payload(raw_text="Real body."),
        repo=repo,
        workspace_id=_WORKSPACE,
        captured_on=date.today(),
        detailed_summary="A meaningful summary about Naruto.",
        profile_id=_PROFILE,
    )

    assert len(enqueued) == 1
    payload_out = enqueued[0]["payload"]
    assert payload_out["canonical_zettel_id"] == str(_CANON)
    assert payload_out["workspace_zettel_id"] == str(_WZID)
    assert payload_out["detailed_summary"].startswith("A meaningful summary")
    # The summarized_payload must carry source_url + tags + raw_text so the
    # handler's build_canonical_chunks reproduces the exact chunk source.
    sp = payload_out["summarized_payload"]
    assert sp["source_url"] == "https://example.com/post"
    assert sp["tags"] == ["anime"]
    assert sp["raw_text"] == "Real body."
