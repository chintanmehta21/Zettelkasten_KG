"""Test the source_ingest auto-discovery registry."""
from datetime import datetime, timezone

import pytest

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.source_ingest import (
    get_ingestor,
    list_ingestors,
    register_ingestor,
)
from website.features.summarization_engine.source_ingest.base import BaseIngestor


class _FakeIngestor(BaseIngestor):
    source_type = SourceType.WEB

    async def ingest(self, url: str, *, config: dict) -> IngestResult:
        return IngestResult(
            source_type=SourceType.WEB,
            url=url,
            original_url=url,
            raw_text="x",
            extraction_confidence="high",
            confidence_reason="fake",
            fetched_at=datetime.now(timezone.utc),
        )


def test_register_and_get():
    register_ingestor(_FakeIngestor)
    assert get_ingestor(SourceType.WEB) is _FakeIngestor


def test_get_unknown_raises():
    from website.features.summarization_engine.core.errors import RoutingError

    with pytest.raises((RoutingError, ValueError)):
        get_ingestor("nonexistent-source")


def test_list_ingestors_returns_dict():
    register_ingestor(_FakeIngestor)
    mapping = list_ingestors()
    assert SourceType.WEB in mapping
