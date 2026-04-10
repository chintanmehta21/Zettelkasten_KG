"""Tests for batch input and markdown writer helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from website.features.summarization_engine.batch.input_loader import load_batch_input
from website.features.summarization_engine.core.models import (
    DetailedSummarySection,
    SourceType,
    SummaryMetadata,
    SummaryResult,
)
from website.features.summarization_engine.writers.markdown import render_markdown
from website.features.summarization_engine.writers.obsidian import ObsidianWriter


def test_load_batch_input_csv():
    items = load_batch_input(input_bytes=b"url,tags,note\nhttps://example.com,\"a,b\",hello\n", filename="x.csv")
    assert items[0].url == "https://example.com"
    assert items[0].user_tags == ["a", "b"]
    assert items[0].user_note == "hello"


def test_load_batch_input_json():
    items = load_batch_input(input_bytes=b'{"urls":[{"url":"https://x.test","tags":["x"]}]}', filename="x.json")
    assert items[0].url == "https://x.test"
    assert items[0].user_tags == ["x"]


@pytest.mark.asyncio
async def test_obsidian_writer_writes_markdown(tmp_path):
    result = _summary_result()
    output = await ObsidianWriter(tmp_path).write(result, user_id=UUID("00000000-0000-0000-0000-000000000001"))
    assert output["path"].endswith("test-note.md")
    assert "## Detailed Summary" in (tmp_path / "test-note.md").read_text(encoding="utf-8")


def test_render_markdown_contains_frontmatter():
    rendered = render_markdown(_summary_result())
    assert "source_type: web" in rendered
    assert "# Test note" in rendered


def _summary_result() -> SummaryResult:
    return SummaryResult(
        mini_title="Test note",
        brief_summary="A useful summary.",
        tags=["one", "two", "three", "four", "five", "six", "seven", "eight"],
        detailed_summary=[DetailedSummarySection(heading="Main", bullets=["Point"])],
        metadata=SummaryMetadata(
            source_type=SourceType.WEB,
            url="https://example.com",
            extraction_confidence="high",
            confidence_reason="ok",
            total_tokens_used=0,
            total_latency_ms=0,
            date=datetime.now(timezone.utc),
        ),
    )
