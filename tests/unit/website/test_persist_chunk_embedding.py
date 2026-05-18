"""DEFECT coverage: canonical chunk MUST persist its 768-d embedding.

Live evidence (Naruto, profile f2105544-...): all 25 canonical_chunks rows
had embedding IS NULL but embedding_model_version='gemini-001-mrl-768' set.
content.search_chunks filters `cc.embedding IS NOT NULL`, so the dense
retrieval channel had zero vectors and gold@1 collapsed.

These tests:
- reproduce the NULL-with-model_version bug then prove it's fixed (the chunk
  the persist path hands the repo now carries a 768-float embedding);
- prove an embedding-generation FAILURE does NOT yield a silent
  NULL-embedding + model_version row (no chunk is written at all; the zettel
  still persists);
- pin the embedded vector dimensionality (768) and the model-version stamp.

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
    """Repo stub that captures the chunks handed to upsert_canonical_zettel."""

    def __init__(self) -> None:
        self.chunks = None

    def upsert_canonical_zettel(self, zettel, *, workspace=None, chunks=None):
        self.chunks = chunks
        return CanonicalUpsertResult(
            canonical_zettel_id=_CANON,
            workspace_zettel_id=_WZID,
            was_new=True,
        )


def _payload() -> dict:
    return {
        "source_url": "https://example.com/post",
        "source_type": "web",
        "title": "Naruto Uzumaki",
        "summary": "Naruto is the protagonist who becomes Hokage.",
        "tags": ["anime"],
        "metadata": {},
    }


@pytest.mark.asyncio
async def test_chunk_persisted_with_768d_embedding(monkeypatch) -> None:
    """FIXED behavior: every chunk handed to the repo carries a 768-d vector
    and the matching model-version stamp.

    CONTRACT CHANGE (old -> new): pre-fix this asserted EXACTLY ONE chunk
    whose text equalled the summary verbatim (the single-monolithic-chunk
    root-cause bug). Post-fix the persist path segments the source via the
    real chunker; a short body yields >=1 chunk but each must still carry the
    embedding + stamp. The single batch-embed call covers every chunk text.
    Multi-chunk segmentation of long bodies is pinned in
    test_persist_multichunk.py.
    """
    fake_vec = [0.01] * 768
    embed_calls = {"n": 0}

    async def _fake_embed(texts):
        embed_calls["n"] += 1
        assert texts and all(isinstance(t, str) and t for t in texts)
        return [fake_vec for _ in texts]

    monkeypatch.setattr(persist, "embed_chunk_texts", _fake_embed)
    monkeypatch.setattr(persist, "_schedule_kg_population", lambda **_k: None)

    repo = _CaptureRepo()
    await persist._persist_supabase_v2_zettel(
        payload=_payload(),
        repo=repo,
        workspace_id=_WORKSPACE,
        captured_on=date.today(),
        detailed_summary="Naruto is the protagonist who becomes Hokage.",
    )

    assert repo.chunks is not None and len(repo.chunks) >= 1
    assert embed_calls["n"] == 1  # single batch embed for all chunks
    for chunk in repo.chunks:
        assert chunk.embedding is not None
        assert len(chunk.embedding) == 768
        assert chunk.embedding == fake_vec
        assert chunk.embedding_model_version == persist._CHUNK_EMBED_MODEL_VERSION
        assert chunk.embedding_model_version == "gemini-001-mrl-768"


@pytest.mark.asyncio
async def test_embed_failure_writes_no_chunk_row(monkeypatch) -> None:
    """An embedding failure must NOT produce a NULL-embedding chunk with a
    model_version implying success — the exact live defect. No chunk row is
    written at all; the canonical zettel still persists."""

    async def _fail_embed(texts):
        return None  # embed_chunk_texts signals failure with None

    monkeypatch.setattr(persist, "embed_chunk_texts", _fail_embed)

    repo = _CaptureRepo()
    node_id, saved, _dup = await persist._persist_supabase_v2_zettel(
        payload=_payload(),
        repo=repo,
        workspace_id=_WORKSPACE,
        captured_on=date.today(),
        detailed_summary="Naruto is the protagonist who becomes Hokage.",
    )

    # No chunk written -> no silent NULL-embedding+model_version row.
    assert repo.chunks == []
    # The zettel itself still persisted (defect recovery via backfill).
    assert saved is True
    assert node_id == str(_WZID)


@pytest.mark.asyncio
async def test_no_chunk_text_no_embed_call(monkeypatch) -> None:
    """CONTRACT CHANGE (old -> new): pre-fix an empty body+summary produced
    ZERO chunks. Post-fix the persist path mirrors the chunker's own
    source-selection convention (the previously-dead ingest/hook.py path),
    which SYNTHESIZES a minimal searchable body from title/tags so a
    transcript-less / paywalled node is still retrievable instead of
    invisible. So with a real title we now expect exactly one synthesized
    fallback chunk (embedded once). The truly-empty case (no title either)
    is covered by ``test_truly_empty_payload_yields_zero_chunks`` below."""
    called = {"n": 0}

    async def _spy(texts):
        called["n"] += 1
        return [[0.0] * 768 for _ in texts]

    monkeypatch.setattr(persist, "embed_chunk_texts", _spy)
    monkeypatch.setattr(persist, "_schedule_kg_population", lambda **_k: None)

    repo = _CaptureRepo()
    payload = _payload()
    payload["summary"] = ""
    await persist._persist_supabase_v2_zettel(
        payload=payload,
        repo=repo,
        workspace_id=_WORKSPACE,
        captured_on=date.today(),
        detailed_summary="",  # body + summary empty -> title/tag fallback
    )
    assert repo.chunks is not None and len(repo.chunks) == 1
    assert called["n"] == 1
    assert "Naruto Uzumaki" in repo.chunks[0].content


@pytest.mark.asyncio
async def test_truly_empty_payload_yields_zero_chunks(monkeypatch) -> None:
    """No body, no summary, no title, no tags, no url -> the synthesized
    fallback is empty too, so ZERO chunks and ZERO embed calls (the
    embed-or-skip contract still holds at the floor)."""
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
    )
    assert repo.chunks == []
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_embed_chunk_texts_wrong_dim_is_failure(monkeypatch) -> None:
    """embed_chunk_texts returns None when the embedder yields a wrong-dim
    vector (so the caller never persists a mis-typed halfvec)."""

    class _BadEmbedder:
        def __init__(self, *a, **k):
            pass

        async def embed(self, texts):
            return [[0.0] * 512 for _ in texts]  # wrong dim (want 768)

    import website.features.rag_pipeline.ingest.embedder as emb_mod

    monkeypatch.setattr(emb_mod, "ChunkEmbedder", _BadEmbedder)
    monkeypatch.setattr(
        "website.features.rag_pipeline.adapters.pool_factory."
        "get_embedding_pool",
        lambda: object(),
    )
    out = await persist.embed_chunk_texts(["hello"])
    assert out is None


@pytest.mark.asyncio
async def test_embed_chunk_texts_exception_is_failure(monkeypatch) -> None:
    """A raised embedder error degrades to None (no crash, no NULL row)."""

    class _BoomEmbedder:
        def __init__(self, *a, **k):
            pass

        async def embed(self, texts):
            raise RuntimeError("gemini 429 exhausted")

    import website.features.rag_pipeline.ingest.embedder as emb_mod

    monkeypatch.setattr(emb_mod, "ChunkEmbedder", _BoomEmbedder)
    monkeypatch.setattr(
        "website.features.rag_pipeline.adapters.pool_factory."
        "get_embedding_pool",
        lambda: object(),
    )
    assert await persist.embed_chunk_texts(["hello"]) is None


@pytest.mark.asyncio
async def test_embed_chunk_texts_empty_input() -> None:
    assert await persist.embed_chunk_texts([]) == []
