"""Tests for the ingest-side metadata enricher.

The enricher decorates each chunk row at write-time with structured metadata
derived from chunk content (domains, time_span, optional entities). It MUST
be safe to run with key_pool=None (deterministic-only pass) and never raise
on missing/empty fields.
"""
from __future__ import annotations

import json

import pytest

from website.features.rag_pipeline.ingest.metadata_enricher import MetadataEnricher


@pytest.mark.asyncio
async def test_enrich_extracts_domain_and_time():
    """Plan-spec test: deterministic pass extracts domain + time_span."""
    enricher = MetadataEnricher(key_pool=None)
    out = await enricher.enrich_chunks(
        [
            {
                "id": "c1",
                "content": "Posted on October 12, 2023 at karpathy.com about transformers",
            }
        ]
    )
    md = out[0]["metadata"]
    assert "karpathy.com" in md.get("domains", [])
    assert md.get("time_span", {}).get("end") is not None


@pytest.mark.asyncio
async def test_enrich_handles_empty_content_gracefully():
    """Empty / missing content must not raise; metadata still populated."""
    enricher = MetadataEnricher(key_pool=None)
    out = await enricher.enrich_chunks(
        [
            {"id": "c1", "content": ""},
            {"id": "c2"},  # no content key
        ]
    )
    assert len(out) == 2
    for chunk in out:
        md = chunk["metadata"]
        assert isinstance(md.get("domains"), list)
        # No date should be inferred from empty content
        assert md.get("time_span", {}).get("end") in (None, "") or "time_span" not in md


@pytest.mark.asyncio
async def test_enrich_extracts_multiple_domains():
    """Multiple domains in content should each appear in the domains list."""
    enricher = MetadataEnricher(key_pool=None)
    out = await enricher.enrich_chunks(
        [
            {
                "id": "c1",
                "content": "See github.com/foo/bar and also arxiv.org/abs/1234.5678 for details.",
            }
        ]
    )
    md = out[0]["metadata"]
    domains = md.get("domains", [])
    assert "github.com" in domains
    assert "arxiv.org" in domains


@pytest.mark.asyncio
async def test_enrich_preserves_existing_metadata():
    """Pre-existing metadata fields on the chunk must be preserved."""
    enricher = MetadataEnricher(key_pool=None)
    out = await enricher.enrich_chunks(
        [
            {
                "id": "c1",
                "content": "Plain content with example.com",
                "metadata": {"source_type": "youtube", "node_id": "yt-abc"},
            }
        ]
    )
    md = out[0]["metadata"]
    assert md["source_type"] == "youtube"
    assert md["node_id"] == "yt-abc"
    assert "example.com" in md.get("domains", [])


@pytest.mark.asyncio
async def test_enrich_output_is_json_serializable():
    """The metadata dict on each chunk MUST be JSON-serializable for jsonb insert."""
    enricher = MetadataEnricher(key_pool=None)
    out = await enricher.enrich_chunks(
        [
            {
                "id": "c1",
                "content": "Posted on October 12, 2023 at karpathy.com about transformers",
            }
        ]
    )
    # Should not raise
    serialized = json.dumps(out[0]["metadata"])
    assert isinstance(serialized, str)
    # Round-trip
    assert json.loads(serialized) == out[0]["metadata"]


@pytest.mark.asyncio
async def test_enrich_returns_empty_list_for_empty_input():
    enricher = MetadataEnricher(key_pool=None)
    out = await enricher.enrich_chunks([])
    assert out == []


@pytest.mark.asyncio
async def test_enrich_skips_garbage_pseudo_domains():
    """Tokens like 'foo.qq' (invalid TLD) must be ignored by tldextract suffix check."""
    enricher = MetadataEnricher(key_pool=None)
    out = await enricher.enrich_chunks(
        [{"id": "c1", "content": "see ref.notatld and bogus.zz here"}]
    )
    md = out[0]["metadata"]
    # Neither should land in domains
    domains = md.get("domains", [])
    assert "ref.notatld" not in domains
    assert "bogus.zz" not in domains
