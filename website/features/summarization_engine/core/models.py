"""Core Pydantic models for the summarization engine."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    """All supported content source types."""

    GITHUB = "github"
    NEWSLETTER = "newsletter"
    REDDIT = "reddit"
    YOUTUBE = "youtube"
    HACKERNEWS = "hackernews"
    LINKEDIN = "linkedin"
    ARXIV = "arxiv"
    PODCAST = "podcast"
    TWITTER = "twitter"
    WEB = "web"


ConfidenceLevel = Literal["high", "medium", "low"]


class IngestResult(BaseModel):
    """Canonical output from a source ingestor."""

    source_type: SourceType
    url: str
    original_url: str
    raw_text: str
    sections: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    extraction_confidence: ConfidenceLevel
    confidence_reason: str
    fetched_at: datetime
    ingestor_version: str = "2.0.0"


class DetailedSummarySection(BaseModel):
    """One top-level detailed summary section."""

    heading: str
    bullets: list[str]
    sub_sections: dict[str, list[str]] = Field(default_factory=dict)


class SummaryMetadata(BaseModel):
    """Metadata attached to every SummaryResult."""

    source_type: SourceType
    url: str
    author: str | None = None
    date: datetime | None = None
    extraction_confidence: ConfidenceLevel
    confidence_reason: str
    total_tokens_used: int
    gemini_pro_tokens: int = 0
    gemini_flash_tokens: int = 0
    total_latency_ms: int
    cod_iterations_used: int = 0
    self_check_missing_count: int = 0
    patch_applied: bool = False
    engine_version: str = "2.0.0"
    structured_payload: dict[str, Any] | None = None
    is_schema_fallback: bool = False
    # Per-role Gemini call trace so downstream consumers (eval harness,
    # manual review) can see silent pro→flash-lite downgrades. Each entry:
    # ``{"role": "summarizer"|"patch"|"cod_refine"|"dense_verify", "model": str,
    #   "starting_model": str, "fallback_reason": str | None}``. None when the
    #  summarizer did not opt in to telemetry collection.
    model_used: list[dict[str, Any]] | None = None
    # Convenience top-level fallback reason: non-None when ANY call on the
    # critical path (summarizer or patch) incurred a downgrade. Set to the
    # first non-None call reason so regressions are visible at a glance.
    fallback_reason: str | None = None


class SummaryResult(BaseModel):
    """Base SummaryResult - caps enforced by model_factory.build_summary_result_model(cfg).

    This class exists for type-hint compatibility only. Instances must be built
    via the factory so Pydantic Field caps match config.yaml.
    """

    mini_title: str
    brief_summary: str
    tags: list[str]
    detailed_summary: list[DetailedSummarySection]
    metadata: SummaryMetadata


class BatchRunStatus(str, Enum):
    """Lifecycle state for a batch run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BatchRun(BaseModel):
    """A batch processing run."""

    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    status: BatchRunStatus = BatchRunStatus.PENDING
    input_filename: str | None = None
    input_format: Literal["csv", "json"] | None = None
    mode: Literal["realtime", "batch_api"] = "realtime"
    total_urls: int = 0
    processed_count: int = 0
    success_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    error_message: str | None = None
    config_snapshot: dict[str, Any] = Field(default_factory=dict)


BatchItemStatus = Literal[
    "pending",
    "ingesting",
    "summarizing",
    "writing",
    "succeeded",
    "failed",
    "skipped",
]


class BatchItem(BaseModel):
    """One URL's processing state within a BatchRun."""

    id: UUID
    run_id: UUID
    user_id: UUID
    url: str
    source_type: SourceType | None = None
    status: BatchItemStatus
    node_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    tokens_used: int | None = None
    latency_ms: int | None = None
    user_tags: list[str] = Field(default_factory=list)
    user_note: str | None = None
