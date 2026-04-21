"""Unit tests for ops/scripts/backfill_chunks.py.

Focus: the source-type mapping that routes kg_nodes.source_type strings to
website SourceType enum values and the refetch logic's fallback behaviour.
Network calls are fully mocked — these tests do not talk to Supabase, GitHub,
or any external service.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_MODULE_PATH = _PROJECT_ROOT / "ops" / "scripts" / "backfill_chunks.py"


@pytest.fixture(scope="module")
def backfill():
    """Import ops/scripts/backfill_chunks.py as a module for direct testing."""
    spec = importlib.util.spec_from_file_location(
        "_backfill_chunks_under_test", _MODULE_PATH
    )
    if spec is None or spec.loader is None:
        pytest.skip(f"Cannot load backfill_chunks module from {_MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_backfill_chunks_under_test"] = module
    spec.loader.exec_module(module)
    return module


def test_map_source_type_recognizes_known_aliases(backfill):
    from website.features.summarization_engine.core.models import SourceType

    assert backfill._map_source_type("youtube", "https://example.com") == SourceType.YOUTUBE
    assert backfill._map_source_type("github", "https://example.com") == SourceType.GITHUB
    assert backfill._map_source_type("reddit", "https://example.com") == SourceType.REDDIT
    assert backfill._map_source_type("newsletter", "https://example.com") == SourceType.NEWSLETTER
    assert backfill._map_source_type("substack", "https://example.com") == SourceType.NEWSLETTER
    assert backfill._map_source_type("medium", "https://example.com") == SourceType.NEWSLETTER
    assert backfill._map_source_type("hackernews", "https://example.com") == SourceType.HACKERNEWS
    assert backfill._map_source_type("web", "https://example.com") == SourceType.WEB
    assert backfill._map_source_type("generic", "https://example.com") == SourceType.WEB


def test_map_source_type_unknown_falls_back_to_url_router(backfill):
    """When the stored source_type is unknown, the router should pick by URL."""
    from website.features.summarization_engine.core.models import SourceType

    # Unknown source_type + YouTube URL → router picks YOUTUBE
    result = backfill._map_source_type(
        "unknown-legacy-tag", "https://www.youtube.com/watch?v=abc123"
    )
    assert result == SourceType.YOUTUBE

    # Unknown source_type + plain URL → WEB
    result = backfill._map_source_type("", "https://example.com/post")
    assert result == SourceType.WEB


def test_map_source_type_empty_string_uses_router(backfill):
    """An empty source_type should not raise; the URL drives selection."""
    from website.features.summarization_engine.core.models import SourceType

    assert (
        backfill._map_source_type("", "https://github.com/foo/bar")
        == SourceType.GITHUB
    )


@pytest.mark.asyncio
async def test_refetch_content_skips_when_url_missing(backfill):
    """Nodes without a URL cannot be re-extracted; the function returns None."""
    result = await backfill._refetch_content({"id": "n1", "url": "", "source_type": "web"})
    assert result is None


@pytest.mark.asyncio
async def test_refetch_content_returns_body_from_ingestor(backfill):
    """Happy path: the website ingestor produces an IngestResult, we convert it."""
    from website.features.summarization_engine.core.models import IngestResult, SourceType
    from datetime import datetime, timezone

    fake_result = IngestResult(
        source_type=SourceType.WEB,
        url="https://example.com",
        original_url="https://example.com",
        raw_text="full extracted body " * 50,
        sections={"Article": "full extracted body " * 50},
        metadata={"title": "Example Article"},
        extraction_confidence="high",
        confidence_reason="HTML article text extracted",
        fetched_at=datetime.now(timezone.utc),
    )

    class _StubIngestor:
        async def ingest(self, url, *, config):
            return fake_result

    with patch.object(backfill, "_refetch_content", wraps=backfill._refetch_content):
        with patch(
            "website.features.summarization_engine.source_ingest.get_ingestor",
            return_value=_StubIngestor,
        ):
            out = await backfill._refetch_content(
                {"id": "n1", "url": "https://example.com", "source_type": "web"}
            )

    assert out is not None
    assert out.body.startswith("full extracted body")
    assert out.title == "Example Article"


@pytest.mark.asyncio
async def test_refetch_content_returns_none_when_ingestor_raises(backfill):
    """Any extractor exception must be swallowed so the caller falls back to summary."""

    class _BrokenIngestor:
        async def ingest(self, url, *, config):
            raise RuntimeError("simulated extractor failure")

    with patch(
        "website.features.summarization_engine.source_ingest.get_ingestor",
        return_value=_BrokenIngestor,
    ):
        out = await backfill._refetch_content(
            {"id": "n1", "url": "https://example.com", "source_type": "web"}
        )

    assert out is None
