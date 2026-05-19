"""Multi-chunk persist contract (RAG+KG root-cause fix).

ROOT CAUSE this covers: ``_persist_supabase_v2_zettel`` previously built
exactly ONE ``CanonicalChunkCreate`` regardless of body length, so every
end-user zettel was a single monolithic chunk -> RAG retrieval had no
passage granularity and KG (chunk_node_mentions/structural) was starved.

These tests pin the corrected contract:
- a long body is segmented into MULTIPLE chunks with increasing chunk_idx,
  each with token_count > 0 and an embedding set;
- the embed path is a SINGLE batch call for all chunk texts;
- a short body still produces >= 1 chunk;
- a batch-embed FAILURE persists the zettel with ZERO chunks (the existing
  embed-or-skip contract, now applied to the whole chunk list);
- the deterministic ``content_hash`` (P1-7) is unchanged vs pre-fix;
- ``_schedule_rag_chunks`` (dead path) is gone;
- the per-zettel chunk-count safety cap is honored.

All Supabase / Gemini access is mocked; no live network.
"""
from __future__ import annotations

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
    # ~9k+ chars of distinct sentences so the long-form chunker segments it.
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


@pytest.mark.asyncio
async def test_long_body_segments_into_many_chunks_single_batch_embed(monkeypatch):
    """OLD->NEW (R1): pre-R1 this fed a long RAW body and asserted the raw
    body (not the short summary) was chunked. Post-R1 the SUMMARY is the
    primary chunk source, so a long *summary* must segment into MULTIPLE
    CanonicalChunkCreate with monotonic chunk_idx, each token_count>0 +
    embedding set, produced by exactly ONE batch embed call."""
    long_summary = _long_body()
    embed_calls = {"n": 0, "batch_sizes": []}

    async def _fake_embed(texts):
        embed_calls["n"] += 1
        embed_calls["batch_sizes"].append(len(texts))
        return [[0.01] * 768 for _ in texts]

    monkeypatch.setattr(persist, "embed_chunk_texts", _fake_embed)
    monkeypatch.setattr(persist, "_schedule_kg_population", lambda **_k: None)

    repo = _CaptureRepo()
    await persist._persist_supabase_v2_zettel(
        payload=_payload(raw_text="A short raw body that must NOT be chunked under R1."),
        repo=repo,
        workspace_id=_WORKSPACE,
        captured_on=date.today(),
        detailed_summary=long_summary,
        profile_id=_PROFILE,
    )

    assert repo.chunks is not None
    assert len(repo.chunks) > 1, "long summary must produce multiple chunks"
    # Single batch embed call covering every chunk text.
    assert embed_calls["n"] == 1
    assert embed_calls["batch_sizes"][0] == len(repo.chunks)
    # chunk_idx is 0..N-1 strictly increasing; each chunk well-formed.
    for i, ch in enumerate(repo.chunks):
        assert ch.chunk_idx == i
        assert ch.token_count and ch.token_count > 0
        assert ch.embedding is not None and len(ch.embedding) == 768
        assert ch.embedding_model_version == persist._CHUNK_EMBED_MODEL_VERSION
        assert ch.content
    # The chunked source is the SUMMARY (R1 primary), not the short raw body.
    joined = " ".join(c.content for c in repo.chunks)
    assert "Paragraph 0" in joined


@pytest.mark.asyncio
async def test_short_body_still_produces_at_least_one_chunk(monkeypatch):
    async def _fake_embed(texts):
        return [[0.02] * 768 for _ in texts]

    monkeypatch.setattr(persist, "embed_chunk_texts", _fake_embed)
    monkeypatch.setattr(persist, "_schedule_kg_population", lambda **_k: None)

    repo = _CaptureRepo()
    await persist._persist_supabase_v2_zettel(
        payload=_payload(raw_text="Short but real body about Naruto."),
        repo=repo,
        workspace_id=_WORKSPACE,
        captured_on=date.today(),
        detailed_summary="Naruto becomes Hokage.",
        profile_id=_PROFILE,
    )
    assert repo.chunks is not None and len(repo.chunks) >= 1
    assert repo.chunks[0].embedding is not None


@pytest.mark.asyncio
async def test_batch_embed_failure_persists_zettel_with_zero_chunks(monkeypatch):
    """Existing embed-or-skip contract, now over the whole list: a batch
    embed failure persists the zettel WITHOUT any chunk rows (never a lying
    NULL-embedding row)."""

    async def _fail(texts):
        return None

    monkeypatch.setattr(persist, "embed_chunk_texts", _fail)
    monkeypatch.setattr(persist, "_schedule_kg_population", lambda **_k: None)

    repo = _CaptureRepo()
    node_id, saved, _dup = await persist._persist_supabase_v2_zettel(
        payload=_payload(raw_text=_long_body()),
        repo=repo,
        workspace_id=_WORKSPACE,
        captured_on=date.today(),
        detailed_summary="summary",
        profile_id=_PROFILE,
    )
    assert repo.chunks == []
    assert saved is True
    assert node_id == str(_WZID)


@pytest.mark.asyncio
async def test_truly_empty_source_no_embed_no_chunks(monkeypatch):
    """No body, summary, title, or tags -> the chunker's synthesized
    fallback is also empty -> ZERO chunks, ZERO embed calls (embed-or-skip
    contract at the floor). A node WITH a title but no body still gets a
    synthesized title/tag fallback chunk — that path is covered in
    test_persist_chunk_embedding.py::test_no_chunk_text_no_embed_call."""
    called = {"n": 0}

    async def _spy(texts):
        called["n"] += 1
        return [[0.0] * 768 for _ in texts]

    monkeypatch.setattr(persist, "embed_chunk_texts", _spy)
    monkeypatch.setattr(persist, "_schedule_kg_population", lambda **_k: None)

    repo = _CaptureRepo()
    await persist._persist_supabase_v2_zettel(
        payload={
            "source_url": "https://example.com/post",
            "source_type": "web",
            "title": "",
            "summary": "",
            "tags": [],
            "metadata": {},
        },
        repo=repo,
        workspace_id=_WORKSPACE,
        captured_on=date.today(),
        detailed_summary="",
        profile_id=_PROFILE,
    )
    assert repo.chunks == []
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_content_hash_unchanged_vs_prefix(monkeypatch):
    """P1-7 regression: rewiring chunking must NOT change the dedup hash for
    the same input. The hash derives only from URL + source_fingerprint."""
    import hashlib

    async def _fake_embed(texts):
        return [[0.01] * 768 for _ in texts]

    monkeypatch.setattr(persist, "embed_chunk_texts", _fake_embed)
    monkeypatch.setattr(persist, "_schedule_kg_population", lambda **_k: None)

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


@pytest.mark.asyncio
async def test_chunk_count_safety_cap_enforced(monkeypatch):
    """A pathological body cannot explode chunk count past the cap."""

    async def _fake_embed(texts):
        return [[0.0] * 768 for _ in texts]

    monkeypatch.setattr(persist, "embed_chunk_texts", _fake_embed)
    monkeypatch.setattr(persist, "_schedule_kg_population", lambda **_k: None)
    monkeypatch.setattr(persist, "_MAX_CHUNKS_PER_ZETTEL", 5)

    repo = _CaptureRepo()
    # ~90k chars -> would chunk into far more than 5 segments. R1: the
    # SUMMARY is the chunk source, so the huge body must be the summary.
    huge = _long_body(paragraphs=400)
    await persist._persist_supabase_v2_zettel(
        payload=_payload(raw_text="short raw"),
        repo=repo,
        workspace_id=_WORKSPACE,
        captured_on=date.today(),
        detailed_summary=huge,
        profile_id=_PROFILE,
    )
    assert repo.chunks is not None
    assert len(repo.chunks) <= 5


def test_schedule_rag_chunks_symbol_removed():
    """The dead RAG-chunk scheduler must be purged (no caller, signature
    mismatch). Its removal is part of this fix."""
    assert not hasattr(persist, "_schedule_rag_chunks")


def test_build_canonical_chunks_helper_exists():
    """Shared chunk+embed core so persist and backfill cannot diverge."""
    assert hasattr(persist, "build_canonical_chunks")
