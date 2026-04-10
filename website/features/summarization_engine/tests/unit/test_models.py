"""Tests for core Pydantic models."""
from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from website.features.summarization_engine.core.models import (
    BatchItem,
    BatchRunStatus,
    DetailedSummarySection,
    IngestResult,
    SourceType,
    SummaryMetadata,
    SummaryResult,
)


def test_source_type_values():
    assert SourceType.GITHUB.value == "github"
    assert SourceType.NEWSLETTER.value == "newsletter"
    assert SourceType.HACKERNEWS.value == "hackernews"
    assert len(list(SourceType)) == 10


def test_ingest_result_minimal():
    result = IngestResult(
        source_type=SourceType.GITHUB,
        url="https://github.com/foo/bar",
        original_url="https://github.com/foo/bar",
        raw_text="body",
        extraction_confidence="high",
        confidence_reason="readme ok",
        fetched_at=datetime.now(timezone.utc),
    )

    assert result.source_type == SourceType.GITHUB
    assert result.ingestor_version == "2.0.0"
    assert result.sections == {}
    assert result.metadata == {}


def test_detailed_summary_section_nested():
    section = DetailedSummarySection(
        heading="Architecture",
        bullets=["Built on Rust", "Zero-copy serde"],
        sub_sections={"Storage": ["Uses LSM-tree", "Bloom filters"]},
    )
    assert section.heading == "Architecture"
    assert len(section.bullets) == 2
    assert "Storage" in section.sub_sections


def test_summary_result_validation():
    meta = SummaryMetadata(
        source_type=SourceType.GITHUB,
        url="https://github.com/x",
        extraction_confidence="high",
        confidence_reason="ok",
        total_tokens_used=100,
        gemini_pro_tokens=90,
        gemini_flash_tokens=10,
        total_latency_ms=1500,
        cod_iterations_used=2,
        self_check_missing_count=0,
        patch_applied=False,
    )
    result = SummaryResult(
        mini_title="Rust async runtime comparison",
        brief_summary=(
            "A benchmark of Tokio and async-std runtimes showing Tokio is "
            "2x faster on IO-bound workloads."
        ),
        tags=[
            "rust",
            "async",
            "tokio",
            "async-std",
            "benchmarks",
            "runtimes",
            "concurrency",
            "systems",
        ],
        detailed_summary=[
            DetailedSummarySection(heading="Summary", bullets=["Tokio wins"]),
        ],
        metadata=meta,
    )
    assert len(result.tags) == 8
    assert result.metadata.engine_version == "2.0.0"


def test_summary_result_rejects_too_few_tags():
    meta = SummaryMetadata(
        source_type=SourceType.WEB,
        url="x",
        extraction_confidence="high",
        confidence_reason="x",
        total_tokens_used=0,
        gemini_pro_tokens=0,
        gemini_flash_tokens=0,
        total_latency_ms=0,
        cod_iterations_used=0,
        self_check_missing_count=0,
        patch_applied=False,
    )
    with pytest.raises(ValidationError):
        SummaryResult(
            mini_title="x",
            brief_summary="x",
            tags=["only", "three", "tags"],
            detailed_summary=[DetailedSummarySection(heading="h", bullets=["b"])],
            metadata=meta,
        )


def test_batch_run_status_enum():
    assert BatchRunStatus.PENDING.value == "pending"
    assert BatchRunStatus.COMPLETED.value == "completed"


def test_batch_item_defaults():
    item = BatchItem(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        run_id=UUID("00000000-0000-0000-0000-000000000002"),
        user_id=UUID("00000000-0000-0000-0000-000000000003"),
        url="https://x",
        status="pending",
    )
    assert item.user_tags == []
    assert item.user_note is None
