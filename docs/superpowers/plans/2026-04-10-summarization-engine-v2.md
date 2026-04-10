# Summarization Engine v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dynamic, source-aware summarization engine at `website/features/summarization_engine/` that ingests URLs from 9 content sources (GitHub, Newsletters, Reddit, YouTube, HackerNews, LinkedIn, arXiv, Podcasts, Twitter), produces structured Zettelkasten summaries via tiered Gemini 2.5 Pro + Flash, and persists to Supabase — all without touching the existing `telegram_bot/` pipeline.

**Architecture:** Pure library (returns `SummaryResult`, caller composes writers). 4-phase summarization pipeline (CoD densify → inverted-FactScore self-check → conditional patch → Flash structured extract). Auto-discovery registries for ingestors and summarizers. Extends existing `kg_nodes` Supabase schema. New endpoints `/api/v2/summarize`, `/api/v2/batch*` alongside existing `/api/summarize`.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, httpx, trafilatura 2.x, feedparser, PyMuPDF, youtube-transcript-api, yt-dlp, praw, beautifulsoup4, google-genai (Gemini 2.5 Pro + Flash), Supabase (postgrest-py), pytest + pytest-asyncio + pytest-httpx, sse-starlette.

**Spec:** `docs/superpowers/specs/2026-04-10-summarization-engine-v2-design.md`

**Phases:**
- Phase 0: Setup (dependencies, directory scaffold, conftest)
- Phase 1: Foundation (models, errors, router, gemini client, orchestrator skeleton)
- Phase 2: Ingestors Batch 1 (GitHub, HackerNews, arXiv)
- Phase 3: Ingestors Batch 2 (Newsletters, Reddit, YouTube)
- Phase 4: Ingestors Batch 3 (LinkedIn, Podcasts, Twitter)
- Phase 5: Summarization Common (CoD, self-check, patch, structured extract)
- Phase 6: Per-source summarizers
- Phase 7: Supabase schema migration
- Phase 8: Writers (Supabase, Obsidian, GitHub)
- Phase 9: Batch processor (input loader, concurrency, Gemini Batch API)
- Phase 10: API routes (`/api/v2/*`)
- Phase 11: UI (batch dashboard)
- Phase 12: Live tests + CI

---

## Phase 0: Setup

### Task 0.1: Add new dependencies to ops/requirements.txt

**Files:**
- Modify: `ops/requirements.txt`

- [ ] **Step 1: Read current requirements**

Run: `cat ops/requirements.txt | tail -20`
Verify existing deps include httpx, trafilatura, praw, google-genai, youtube-transcript-api, yt-dlp, fastapi, supabase.

- [ ] **Step 2: Append new deps**

Add the following lines to the end of `ops/requirements.txt`:

```
# Summarization engine v2
feedparser>=6.0.11
PyMuPDF>=1.24
arxiv>=2.1.0
newspaper4k>=0.9.3
python-podcastindex>=1.0.0
sse-starlette>=2.0
pytest-httpx>=0.34
```

- [ ] **Step 3: Install**

Run: `pip install -r ops/requirements.txt`
Expected: All 7 new packages install without error.

- [ ] **Step 4: Verify imports**

Run: `python -c "import feedparser, fitz, arxiv, newspaper, podcastindex, sse_starlette, pytest_httpx; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add ops/requirements.txt
git commit -m "feat(engine): add summarization engine v2 dependencies"
```

### Task 0.2: Scaffold directory structure

**Files:**
- Create: `website/features/summarization_engine/__init__.py`
- Create: `website/features/summarization_engine/About.md`
- Create: `website/features/summarization_engine/core/__init__.py`
- Create: `website/features/summarization_engine/source_ingest/__init__.py`
- Create: `website/features/summarization_engine/summarization/__init__.py`
- Create: `website/features/summarization_engine/summarization/common/__init__.py`
- Create: `website/features/summarization_engine/writers/__init__.py`
- Create: `website/features/summarization_engine/batch/__init__.py`
- Create: `website/features/summarization_engine/api/__init__.py`
- Create: `website/features/summarization_engine/tests/__init__.py`
- Create: `website/features/summarization_engine/tests/unit/__init__.py`
- Create: `website/features/summarization_engine/tests/unit/ingest/__init__.py`
- Create: `website/features/summarization_engine/tests/integration/__init__.py`
- Create: `website/features/summarization_engine/tests/live/__init__.py`

- [ ] **Step 1: Create all `__init__.py` files as empty placeholders**

Run:
```bash
mkdir -p website/features/summarization_engine/{core,source_ingest,summarization/common,writers,batch,api,tests/unit/ingest,tests/integration,tests/live,ui/css,ui/js}
touch website/features/summarization_engine/__init__.py
touch website/features/summarization_engine/core/__init__.py
touch website/features/summarization_engine/source_ingest/__init__.py
touch website/features/summarization_engine/summarization/__init__.py
touch website/features/summarization_engine/summarization/common/__init__.py
touch website/features/summarization_engine/writers/__init__.py
touch website/features/summarization_engine/batch/__init__.py
touch website/features/summarization_engine/api/__init__.py
touch website/features/summarization_engine/tests/__init__.py
touch website/features/summarization_engine/tests/unit/__init__.py
touch website/features/summarization_engine/tests/unit/ingest/__init__.py
touch website/features/summarization_engine/tests/integration/__init__.py
touch website/features/summarization_engine/tests/live/__init__.py
```

- [ ] **Step 2: Write About.md**

Create `website/features/summarization_engine/About.md`:

```markdown
# Summarization Engine v2

Pure-library summarization engine that ingests URLs from 9 content sources and produces structured Zettelkasten summaries via tiered Gemini 2.5 Pro + Flash.

## Public API
- `summarize_url(url, user_id)` — single URL, real-time
- `BatchProcessor(user_id).run(input_path | input_bytes)` — CSV/JSON batch
- Writers are composable: `SupabaseWriter`, `ObsidianWriter`, `GithubRepoWriter`

## Integration
- `/api/v2/summarize` and `/api/v2/batch*` endpoints alongside existing `/api/summarize`
- Old `telegram_bot/` pipeline untouched
- Reuses `website/features/api_key_switching/key_pool.py`

See `docs/superpowers/specs/2026-04-10-summarization-engine-v2-design.md` for full design.
```

- [ ] **Step 3: Verify package imports**

Run: `python -c "import website.features.summarization_engine; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add website/features/summarization_engine/
git commit -m "feat(engine): scaffold summarization_engine package structure"
```

### Task 0.3: Create pytest conftest with shared fixtures

**Files:**
- Create: `website/features/summarization_engine/tests/conftest.py`

- [ ] **Step 1: Write conftest.py**

Create `website/features/summarization_engine/tests/conftest.py`:

```python
"""Shared fixtures for summarization engine tests."""
from __future__ import annotations

import pytest
from pathlib import Path
from uuid import UUID
from unittest.mock import AsyncMock, MagicMock


def pytest_addoption(parser):
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="Run live tests that hit real APIs (require credentials)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip_live = pytest.mark.skip(reason="need --live flag to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture
def sample_user_id() -> UUID:
    return UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def sample_urls() -> dict[str, str]:
    return {
        "github": "https://github.com/anthropic-ai/anthropic-sdk-python",
        "reddit": "https://www.reddit.com/r/Python/comments/abc123/test_post/",
        "youtube": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "hackernews": "https://news.ycombinator.com/item?id=40123456",
        "arxiv": "https://arxiv.org/abs/2310.11511",
        "newsletter": "https://stratechery.com/2024/some-post/",
        "linkedin": "https://www.linkedin.com/posts/satyanadella_activity-1234567890-abcd",
        "podcast": "https://podcasts.apple.com/us/podcast/lex-fridman/id1434243584?i=1000123456",
        "twitter": "https://twitter.com/elonmusk/status/1234567890123456789",
    }


@pytest.fixture
def mock_gemini_client():
    """Mock TieredGeminiClient that returns canned responses."""
    client = MagicMock()
    client.generate = AsyncMock()
    return client


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
```

- [ ] **Step 2: Create fixtures directory**

Run: `mkdir -p website/features/summarization_engine/tests/fixtures`

- [ ] **Step 3: Verify pytest discovers fixtures**

Run: `pytest website/features/summarization_engine/tests/ --collect-only 2>&1 | head -20`
Expected: No errors; `conftest.py` loaded.

- [ ] **Step 4: Commit**

```bash
git add website/features/summarization_engine/tests/
git commit -m "test(engine): add pytest conftest with shared fixtures"
```

---

## Phase 1: Foundation

### Task 1.1: Define SourceType enum and errors

**Files:**
- Create: `website/features/summarization_engine/core/errors.py`
- Create: `website/features/summarization_engine/tests/unit/test_errors.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/test_errors.py`:

```python
"""Tests for typed error classes."""
import pytest

from website.features.summarization_engine.core.errors import (
    EngineError,
    RoutingError,
    ExtractionError,
    SummarizationError,
    WriterError,
    GeminiError,
    RateLimitedError,
    ExtractionConfidenceError,
)


def test_base_engine_error_is_exception():
    err = EngineError("test")
    assert isinstance(err, Exception)
    assert str(err) == "test"


def test_routing_error_has_url():
    err = RoutingError("unknown", url="https://example.com")
    assert err.url == "https://example.com"


def test_extraction_error_carries_source_type():
    err = ExtractionError("fail", source_type="github", reason="404")
    assert err.source_type == "github"
    assert err.reason == "404"


def test_rate_limited_error_has_retry_after():
    err = RateLimitedError("rate limited", retry_after_sec=60)
    assert err.retry_after_sec == 60
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest website/features/summarization_engine/tests/unit/test_errors.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement errors module**

Create `website/features/summarization_engine/core/errors.py`:

```python
"""Typed exceptions for the summarization engine."""
from __future__ import annotations


class EngineError(Exception):
    """Base class for all summarization engine errors."""


class RoutingError(EngineError):
    """Raised when a URL cannot be routed to a source type."""

    def __init__(self, message: str, *, url: str = ""):
        super().__init__(message)
        self.url = url


class ExtractionError(EngineError):
    """Raised when source ingestion fails."""

    def __init__(
        self,
        message: str,
        *,
        source_type: str = "",
        reason: str = "",
    ):
        super().__init__(message)
        self.source_type = source_type
        self.reason = reason


class ExtractionConfidenceError(ExtractionError):
    """Raised when extraction confidence is explicitly 'low' and caller rejects."""


class SummarizationError(EngineError):
    """Raised when the LLM summarization pipeline fails."""


class WriterError(EngineError):
    """Raised when a writer fails to persist a result."""

    def __init__(self, message: str, *, writer: str = ""):
        super().__init__(message)
        self.writer = writer


class GeminiError(EngineError):
    """Raised for Gemini API errors not handled by the key pool."""


class RateLimitedError(GeminiError):
    """Raised when rate-limited and pool exhausted."""

    def __init__(self, message: str, *, retry_after_sec: int = 0):
        super().__init__(message)
        self.retry_after_sec = retry_after_sec
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest website/features/summarization_engine/tests/unit/test_errors.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/core/errors.py website/features/summarization_engine/tests/unit/test_errors.py
git commit -m "feat(engine): add typed error classes"
```

### Task 1.2: Define Pydantic models (SourceType, IngestResult, SummaryResult, BatchRun)

**Files:**
- Create: `website/features/summarization_engine/core/models.py`
- Create: `website/features/summarization_engine/tests/unit/test_models.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/test_models.py`:

```python
"""Tests for core Pydantic models."""
from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from website.features.summarization_engine.core.models import (
    SourceType,
    IngestResult,
    SummaryResult,
    SummaryMetadata,
    DetailedSummarySection,
    BatchRun,
    BatchRunStatus,
    BatchItem,
)


def test_source_type_values():
    assert SourceType.GITHUB.value == "github"
    assert SourceType.NEWSLETTER.value == "newsletter"
    assert SourceType.HACKERNEWS.value == "hackernews"
    assert len(list(SourceType)) == 10  # 9 specific + web fallback


def test_ingest_result_minimal():
    r = IngestResult(
        source_type=SourceType.GITHUB,
        url="https://github.com/foo/bar",
        original_url="https://github.com/foo/bar",
        raw_text="body",
        extraction_confidence="high",
        confidence_reason="readme ok",
        fetched_at=datetime.now(timezone.utc),
    )
    assert r.source_type == SourceType.GITHUB
    assert r.ingestor_version == "2.0.0"
    assert r.sections == {}
    assert r.metadata == {}


def test_detailed_summary_section_nested():
    s = DetailedSummarySection(
        heading="Architecture",
        bullets=["Built on Rust", "Zero-copy serde"],
        sub_sections={"Storage": ["Uses LSM-tree", "Bloom filters"]},
    )
    assert s.heading == "Architecture"
    assert len(s.bullets) == 2
    assert "Storage" in s.sub_sections


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
    r = SummaryResult(
        mini_title="Rust async runtime comparison",
        brief_summary="A benchmark of Tokio and async-std runtimes showing Tokio is 2x faster on IO-bound workloads.",
        tags=["rust", "async", "tokio", "async-std", "benchmarks", "runtimes", "concurrency", "systems"],
        detailed_summary=[
            DetailedSummarySection(heading="Summary", bullets=["Tokio wins"]),
        ],
        metadata=meta,
    )
    assert len(r.tags) == 8
    assert r.metadata.engine_version == "2.0.0"


def test_summary_result_rejects_too_few_tags():
    meta = SummaryMetadata(
        source_type=SourceType.WEB, url="x",
        extraction_confidence="high", confidence_reason="x",
        total_tokens_used=0, gemini_pro_tokens=0, gemini_flash_tokens=0,
        total_latency_ms=0, cod_iterations_used=0,
        self_check_missing_count=0, patch_applied=False,
    )
    with pytest.raises(ValidationError):
        SummaryResult(
            mini_title="x", brief_summary="x",
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
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest website/features/summarization_engine/tests/unit/test_models.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement models.py**

Create `website/features/summarization_engine/core/models.py`:

```python
"""Core Pydantic models for the summarization engine."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

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
    WEB = "web"  # generic fallback


ConfidenceLevel = Literal["high", "medium", "low"]


class IngestResult(BaseModel):
    """Output of source_ingest/{source}/ingest.py -> BaseIngestor.ingest()."""

    source_type: SourceType
    url: str  # normalized, post-redirect
    original_url: str  # as provided by user
    raw_text: str  # canonical concatenated text for the LLM
    sections: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    extraction_confidence: ConfidenceLevel
    confidence_reason: str
    fetched_at: datetime
    ingestor_version: str = "2.0.0"


class DetailedSummarySection(BaseModel):
    """One top-level theme in the detailed_summary nested bullet structure."""

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


class SummaryResult(BaseModel):
    """Final Zettelkasten-ready summary returned by the summarization pipeline."""

    mini_title: str = Field(..., max_length=60)
    brief_summary: str = Field(..., max_length=400)
    tags: list[str] = Field(..., min_length=8, max_length=15)
    detailed_summary: list[DetailedSummarySection]
    metadata: SummaryMetadata


class BatchRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BatchRun(BaseModel):
    """A batch processing run."""

    id: UUID
    user_id: UUID
    status: BatchRunStatus
    input_filename: str | None = None
    input_format: Literal["csv", "json"] | None = None
    mode: Literal["realtime", "batch_api"] = "realtime"
    total_urls: int = 0
    processed_count: int = 0
    success_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    started_at: datetime
    completed_at: datetime | None = None
    error_message: str | None = None
    config_snapshot: dict[str, Any] = Field(default_factory=dict)


BatchItemStatus = Literal[
    "pending", "ingesting", "summarizing", "writing", "succeeded", "failed", "skipped"
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
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest website/features/summarization_engine/tests/unit/test_models.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/core/models.py website/features/summarization_engine/tests/unit/test_models.py
git commit -m "feat(engine): add core Pydantic models"
```

### Task 1.3: Implement URL router (detect SourceType from URL)

**Files:**
- Create: `website/features/summarization_engine/core/router.py`
- Create: `website/features/summarization_engine/tests/unit/test_router.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/test_router.py`:

```python
"""URL router tests: detect SourceType from URL."""
import pytest

from website.features.summarization_engine.core.router import detect_source_type
from website.features.summarization_engine.core.models import SourceType


@pytest.mark.parametrize("url,expected", [
    # GitHub
    ("https://github.com/foo/bar", SourceType.GITHUB),
    ("https://www.github.com/foo/bar", SourceType.GITHUB),
    ("https://github.com/foo/bar/tree/main", SourceType.GITHUB),
    # HackerNews
    ("https://news.ycombinator.com/item?id=123", SourceType.HACKERNEWS),
    # arXiv
    ("https://arxiv.org/abs/2310.11511", SourceType.ARXIV),
    ("https://arxiv.org/pdf/2310.11511", SourceType.ARXIV),
    ("https://ar5iv.labs.arxiv.org/html/2310.11511", SourceType.ARXIV),
    # Reddit
    ("https://www.reddit.com/r/Python/comments/abc/test/", SourceType.REDDIT),
    ("https://old.reddit.com/r/Python/comments/abc/test/", SourceType.REDDIT),
    ("https://redd.it/abc123", SourceType.REDDIT),
    # YouTube
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", SourceType.YOUTUBE),
    ("https://youtu.be/dQw4w9WgXcQ", SourceType.YOUTUBE),
    ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", SourceType.YOUTUBE),
    # LinkedIn
    ("https://www.linkedin.com/posts/satya_activity-1234", SourceType.LINKEDIN),
    # Newsletter (Substack, Medium)
    ("https://stratechery.substack.com/p/some-post", SourceType.NEWSLETTER),
    ("https://medium.com/@author/some-post-abc123", SourceType.NEWSLETTER),
    ("https://author.substack.com/p/post", SourceType.NEWSLETTER),
    # Podcasts
    ("https://podcasts.apple.com/us/podcast/foo/id123?i=456", SourceType.PODCAST),
    ("https://open.spotify.com/episode/abc123", SourceType.PODCAST),
    ("https://overcast.fm/+XYZ", SourceType.PODCAST),
    # Twitter / X
    ("https://twitter.com/user/status/1234567890", SourceType.TWITTER),
    ("https://x.com/user/status/1234567890", SourceType.TWITTER),
    # Generic web fallback
    ("https://example.com/article", SourceType.WEB),
    ("https://unknown-site.org/page", SourceType.WEB),
])
def test_detect_source_type(url, expected):
    assert detect_source_type(url) == expected


def test_detect_source_type_empty_returns_web():
    assert detect_source_type("") == SourceType.WEB


def test_detect_source_type_malformed_returns_web():
    assert detect_source_type("not-a-url") == SourceType.WEB
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest website/features/summarization_engine/tests/unit/test_router.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement router.py**

Create `website/features/summarization_engine/core/router.py`:

```python
"""URL → SourceType detection for the summarization engine."""
from __future__ import annotations

from urllib.parse import urlparse

from website.features.summarization_engine.core.models import SourceType

# Domain patterns for each source type.
# Order matters: checked top-to-bottom; first match wins.
_DOMAIN_RULES: list[tuple[tuple[str, ...], SourceType]] = [
    (("github.com",), SourceType.GITHUB),
    (("news.ycombinator.com",), SourceType.HACKERNEWS),
    (("arxiv.org", "ar5iv.labs.arxiv.org"), SourceType.ARXIV),
    (("reddit.com", "redd.it"), SourceType.REDDIT),
    (("youtube.com", "youtu.be"), SourceType.YOUTUBE),
    (("linkedin.com",), SourceType.LINKEDIN),
    (("twitter.com", "x.com"), SourceType.TWITTER),
    (
        (
            "podcasts.apple.com",
            "open.spotify.com",
            "overcast.fm",
            "pca.st",  # Pocket Casts
            "share.snipd.com",
            "snipd.com",
        ),
        SourceType.PODCAST,
    ),
]

# Newsletter detection: any of these domains OR substring match
_NEWSLETTER_DOMAINS: tuple[str, ...] = (
    "substack.com",
    "medium.com",
    "beehiiv.com",
    "buttondown.email",
    "mailchimp.com",
    "hackernoon.com",
    "dev.to",
    "stratechery.com",
)


def _strip_www(host: str) -> str:
    """Strip leading www./m. subdomain for matching."""
    for prefix in ("www.", "m.", "mobile."):
        if host.startswith(prefix):
            return host[len(prefix):]
    return host


def detect_source_type(url: str) -> SourceType:
    """Detect the SourceType for a URL.

    Returns SourceType.WEB for any URL that doesn't match a known pattern
    (including empty or malformed URLs).
    """
    if not url:
        return SourceType.WEB
    try:
        parsed = urlparse(url)
    except ValueError:
        return SourceType.WEB

    host = (parsed.hostname or "").lower()
    if not host:
        return SourceType.WEB

    host = _strip_www(host)

    # Check domain rules in order
    for domains, source_type in _DOMAIN_RULES:
        for d in domains:
            if host == d or host.endswith("." + d):
                return source_type

    # Newsletter: domain match OR subdomain of substack/beehiiv/etc
    for d in _NEWSLETTER_DOMAINS:
        if host == d or host.endswith("." + d):
            return SourceType.NEWSLETTER

    return SourceType.WEB
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest website/features/summarization_engine/tests/unit/test_router.py -v`
Expected: All parametrized cases pass (25+ cases).

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/core/router.py website/features/summarization_engine/tests/unit/test_router.py
git commit -m "feat(engine): implement URL source type router"
```

### Task 1.4: Load engine config from YAML

**Files:**
- Create: `website/features/summarization_engine/config.yaml`
- Create: `website/features/summarization_engine/core/config.py`
- Create: `website/features/summarization_engine/tests/unit/test_config.py`

- [ ] **Step 1: Write config.yaml**

Create `website/features/summarization_engine/config.yaml` with the full content from §7 of the spec. (Copy verbatim from `docs/superpowers/specs/2026-04-10-summarization-engine-v2-design.md` section 7, lines starting with `engine:` through the end of the code block.)

- [ ] **Step 2: Write failing test**

Create `website/features/summarization_engine/tests/unit/test_config.py`:

```python
"""Tests for engine config loading."""
from website.features.summarization_engine.core.config import load_config, EngineConfig


def test_load_default_config():
    cfg = load_config()
    assert isinstance(cfg, EngineConfig)
    assert cfg.engine.version == "2.0.0"
    assert cfg.gemini.model_chains["pro"][0] == "gemini-2.5-pro"
    assert cfg.gemini.phase_tiers["cod_densify"] == "pro"
    assert cfg.gemini.phase_tiers["structured_extract"] == "flash"
    assert cfg.chain_of_density.iterations == 2
    assert cfg.self_check.patch_threshold == 3
    assert cfg.structured_extract.tags_min == 8
    assert cfg.structured_extract.tags_max == 15
    assert cfg.batch.max_concurrency == 3


def test_config_sources_block():
    cfg = load_config()
    assert "github" in cfg.sources
    assert "twitter" in cfg.sources
    assert cfg.sources["podcast"]["audio_transcription"] is False
```

- [ ] **Step 3: Run test (expect fail)**

Run: `pytest website/features/summarization_engine/tests/unit/test_config.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 4: Implement config.py**

Create `website/features/summarization_engine/core/config.py`:

```python
"""Load and validate engine config from config.yaml."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class EngineMeta(BaseModel):
    version: str = "2.0.0"
    default_tier: str = "tiered"


class GeminiBatchConfig(BaseModel):
    enabled: bool = True
    threshold: int = 50
    poll_interval_sec: int = 60
    max_turnaround_hours: int = 24


class GeminiConfig(BaseModel):
    reuse_existing_pool: bool = True
    model_chains: dict[str, list[str]] = Field(default_factory=dict)
    phase_tiers: dict[str, str] = Field(default_factory=dict)
    temperature: float = 0.3
    max_output_tokens: int = 8192
    response_mime_type: str = "application/json"
    batch_api: GeminiBatchConfig = GeminiBatchConfig()


class ChainOfDensityConfig(BaseModel):
    enabled: bool = True
    iterations: int = 2
    early_stop_if_few_new_entities: int = 2
    pass1_word_target: int = 200


class SelfCheckConfig(BaseModel):
    enabled: bool = True
    max_atomic_claims: int = 12
    patch_threshold: int = 3
    max_patch_rounds: int = 1


class StructuredExtractConfig(BaseModel):
    validation_retries: int = 1
    mini_title_max_words: int = 5
    brief_summary_max_words: int = 50
    tags_min: int = 8
    tags_max: int = 15


class BatchConfig(BaseModel):
    max_concurrency: int = 3
    max_input_size_mb: int = 10
    supported_input_formats: list[str] = ["csv", "json"]
    progress_event_interval: int = 1


class LoggingConfig(BaseModel):
    level: str = "INFO"
    per_url_correlation_id: bool = True
    log_token_counts: bool = True


class WritersConfig(BaseModel):
    supabase: dict[str, Any] = Field(default_factory=lambda: {"enabled": True})
    obsidian: dict[str, Any] = Field(default_factory=lambda: {"enabled": False})
    github_repo: dict[str, Any] = Field(default_factory=lambda: {"enabled": False})


class EngineConfig(BaseModel):
    engine: EngineMeta = EngineMeta()
    gemini: GeminiConfig = GeminiConfig()
    chain_of_density: ChainOfDensityConfig = ChainOfDensityConfig()
    self_check: SelfCheckConfig = SelfCheckConfig()
    structured_extract: StructuredExtractConfig = StructuredExtractConfig()
    sources: dict[str, dict[str, Any]] = Field(default_factory=dict)
    batch: BatchConfig = BatchConfig()
    writers: WritersConfig = WritersConfig()
    logging: LoggingConfig = LoggingConfig()
    rate_limiting: dict[str, str] = Field(default_factory=dict)


_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


@lru_cache(maxsize=1)
def load_config(path: Path | None = None) -> EngineConfig:
    """Load the engine config from config.yaml.

    Cached after first call. Pass `path` to override in tests.
    """
    p = path or _CONFIG_PATH
    with p.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return EngineConfig(**raw)


def reset_config_cache() -> None:
    """Clear the lru_cache — useful in tests."""
    load_config.cache_clear()
```

- [ ] **Step 5: Run tests, commit**

Run: `pytest website/features/summarization_engine/tests/unit/test_config.py -v`
Expected: 2 passed.

```bash
git add website/features/summarization_engine/config.yaml website/features/summarization_engine/core/config.py website/features/summarization_engine/tests/unit/test_config.py
git commit -m "feat(engine): add config.yaml + loader with Pydantic schema"
```

### Task 1.5: Tiered Gemini client wrapping existing key pool

**Files:**
- Create: `website/features/summarization_engine/core/gemini_client.py`
- Create: `website/features/summarization_engine/tests/unit/test_gemini_client.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/test_gemini_client.py`:

```python
"""Tests for TieredGeminiClient — tier-based model fallback on top of key pool."""
from unittest.mock import AsyncMock, MagicMock
import pytest

from website.features.summarization_engine.core.gemini_client import (
    TieredGeminiClient,
    GenerateResult,
)
from website.features.summarization_engine.core.config import load_config


@pytest.fixture
def fake_pool():
    pool = MagicMock()
    pool.generate_content = AsyncMock()
    return pool


@pytest.mark.asyncio
async def test_generate_pro_tier_calls_pool(fake_pool):
    resp = MagicMock()
    resp.text = '{"ok": true}'
    resp.usage_metadata = MagicMock(
        prompt_token_count=100,
        candidates_token_count=50,
    )
    fake_pool.generate_content.return_value = (resp, "gemini-2.5-pro", 0)

    client = TieredGeminiClient(fake_pool, load_config())
    result = await client.generate("hello", tier="pro")

    assert isinstance(result, GenerateResult)
    assert result.text == '{"ok": true}'
    assert result.model_used == "gemini-2.5-pro"
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    fake_pool.generate_content.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_flash_tier_starts_with_flash(fake_pool):
    resp = MagicMock()
    resp.text = "x"
    resp.usage_metadata = MagicMock(prompt_token_count=10, candidates_token_count=5)
    fake_pool.generate_content.return_value = (resp, "gemini-2.5-flash", 0)

    client = TieredGeminiClient(fake_pool, load_config())
    await client.generate("hi", tier="flash")

    args, kwargs = fake_pool.generate_content.call_args
    assert kwargs["starting_model"] == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_generate_passes_response_schema_for_structured(fake_pool):
    from pydantic import BaseModel

    class Out(BaseModel):
        value: str

    resp = MagicMock()
    resp.text = '{"value": "x"}'
    resp.usage_metadata = MagicMock(prompt_token_count=10, candidates_token_count=5)
    fake_pool.generate_content.return_value = (resp, "gemini-2.5-flash", 0)

    client = TieredGeminiClient(fake_pool, load_config())
    await client.generate("x", tier="flash", response_schema=Out)

    args, kwargs = fake_pool.generate_content.call_args
    assert kwargs["config"]["response_mime_type"] == "application/json"
    assert kwargs["config"]["response_schema"] == Out
```

- [ ] **Step 2: Run tests (expect fail)**

Run: `pytest website/features/summarization_engine/tests/unit/test_gemini_client.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement gemini_client.py**

Create `website/features/summarization_engine/core/gemini_client.py`:

```python
"""Tiered Gemini client wrapping the existing api_key_switching key pool.

Adds Pro/Flash tier selection with per-tier model chain fallback. The underlying
GeminiKeyPool handles the 10-key rotation and 429 cooldowns.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from website.features.summarization_engine.core.config import EngineConfig
from website.features.summarization_engine.core.errors import GeminiError


Tier = Literal["pro", "flash"]


@dataclass
class GenerateResult:
    """Result of a single Gemini generate call."""

    text: str
    model_used: str
    input_tokens: int
    output_tokens: int
    key_index: int = 0


class TieredGeminiClient:
    """Wraps GeminiKeyPool to add Pro/Flash tier routing.

    For tier='pro', starts with gemini-2.5-pro and falls back within the chain
    configured in config.yaml (gemini.model_chains.pro). For tier='flash',
    starts with gemini-2.5-flash and falls back within gemini.model_chains.flash.

    The existing GeminiKeyPool handles 10-key rotation and 429 cooldowns,
    so we just pass starting_model and let the pool do the heavy lifting.
    """

    def __init__(self, key_pool: Any, config: EngineConfig):
        self._pool = key_pool
        self._config = config

    async def generate(
        self,
        prompt: str,
        *,
        tier: Tier = "pro",
        response_schema: type[BaseModel] | None = None,
        system_instruction: str | None = None,
        temperature: float | None = None,
    ) -> GenerateResult:
        """Generate content with tiered model fallback.

        Args:
            prompt: User prompt text.
            tier: 'pro' or 'flash' — selects the model chain.
            response_schema: Pydantic model for structured JSON output.
            system_instruction: Optional system prompt override.
            temperature: Override temperature; defaults to config.gemini.temperature.

        Returns:
            GenerateResult with the response text, model used, and token counts.
        """
        chain = self._config.gemini.model_chains.get(tier)
        if not chain:
            raise GeminiError(f"No model chain configured for tier={tier!r}")

        starting_model = chain[0]

        call_config: dict[str, Any] = {
            "temperature": temperature if temperature is not None else self._config.gemini.temperature,
            "max_output_tokens": self._config.gemini.max_output_tokens,
        }
        if response_schema is not None:
            call_config["response_mime_type"] = "application/json"
            call_config["response_schema"] = response_schema
        if system_instruction:
            call_config["system_instruction"] = system_instruction

        response, model_used, key_index = await self._pool.generate_content(
            contents=prompt,
            config=call_config,
            starting_model=starting_model,
            label=f"engine-v2-{tier}",
        )

        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
        output_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0

        return GenerateResult(
            text=response.text or "",
            model_used=model_used,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            key_index=key_index,
        )
```

- [ ] **Step 4: Run tests, commit**

Run: `pytest website/features/summarization_engine/tests/unit/test_gemini_client.py -v`
Expected: 3 passed.

```bash
git add website/features/summarization_engine/core/gemini_client.py website/features/summarization_engine/tests/unit/test_gemini_client.py
git commit -m "feat(engine): add TieredGeminiClient wrapping key pool"
```

### Task 1.6: Base ingestor ABC + auto-discovery registry

**Files:**
- Create: `website/features/summarization_engine/source_ingest/base.py`
- Create: `website/features/summarization_engine/source_ingest/__init__.py` (replace empty)
- Create: `website/features/summarization_engine/tests/unit/test_ingest_registry.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/test_ingest_registry.py`:

```python
"""Test the source_ingest auto-discovery registry."""
import pytest
from website.features.summarization_engine.source_ingest import (
    get_ingestor,
    list_ingestors,
    register_ingestor,
)
from website.features.summarization_engine.source_ingest.base import BaseIngestor
from website.features.summarization_engine.core.models import SourceType, IngestResult
from datetime import datetime, timezone


class _FakeIngestor(BaseIngestor):
    source_type = SourceType.WEB

    async def ingest(self, url: str, *, config: dict) -> IngestResult:
        return IngestResult(
            source_type=SourceType.WEB,
            url=url, original_url=url,
            raw_text="x", extraction_confidence="high",
            confidence_reason="fake", fetched_at=datetime.now(timezone.utc),
        )


def test_register_and_get():
    register_ingestor(_FakeIngestor)
    cls = get_ingestor(SourceType.WEB)
    assert cls is _FakeIngestor


def test_get_unknown_raises():
    from website.features.summarization_engine.core.errors import RoutingError
    with pytest.raises(RoutingError):
        get_ingestor("nonexistent-source")


def test_list_ingestors_returns_dict():
    register_ingestor(_FakeIngestor)
    mapping = list_ingestors()
    assert SourceType.WEB in mapping
```

- [ ] **Step 2: Run test (fail)**

Run: `pytest website/features/summarization_engine/tests/unit/test_ingest_registry.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement base.py**

Create `website/features/summarization_engine/source_ingest/base.py`:

```python
"""Base class for all source ingestors."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from website.features.summarization_engine.core.models import (
    IngestResult,
    SourceType,
)


class BaseIngestor(ABC):
    """Abstract base class for source ingestors.

    Subclasses must set `source_type` and implement `ingest()`.
    Registration with the auto-discovery registry happens at module
    import time via source_ingest/__init__.py.
    """

    source_type: ClassVar[SourceType]

    @abstractmethod
    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        """Fetch and extract content from the URL.

        Args:
            url: Already normalized and redirect-resolved URL.
            config: Source-specific config from EngineConfig.sources[source_type].

        Returns:
            IngestResult with raw_text, metadata, and extraction confidence.

        Raises:
            ExtractionError: on unrecoverable extraction failure.
        """
        raise NotImplementedError
```

- [ ] **Step 4: Implement registry (__init__.py)**

Overwrite `website/features/summarization_engine/source_ingest/__init__.py`:

```python
"""Auto-discovery registry for source ingestors.

Scans this package at import time and registers every BaseIngestor subclass
that has a `source_type` class attribute set.
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

from website.features.summarization_engine.core.errors import RoutingError
from website.features.summarization_engine.core.models import SourceType

if TYPE_CHECKING:
    from website.features.summarization_engine.source_ingest.base import BaseIngestor


_REGISTRY: dict[SourceType, type["BaseIngestor"]] = {}


def register_ingestor(cls: type["BaseIngestor"]) -> None:
    """Register an ingestor class. Usually called by auto-discovery."""
    if not hasattr(cls, "source_type"):
        return
    _REGISTRY[cls.source_type] = cls


def get_ingestor(source_type: SourceType | str) -> type["BaseIngestor"]:
    """Look up the ingestor class for a source type."""
    if source_type not in _REGISTRY:
        raise RoutingError(
            f"No ingestor registered for source_type={source_type!r}",
            url="",
        )
    return _REGISTRY[source_type]


def list_ingestors() -> dict[SourceType, type["BaseIngestor"]]:
    """Return a copy of the current registry mapping."""
    return dict(_REGISTRY)


def _auto_discover() -> None:
    """Walk this package and import every ingest.py module to trigger registration."""
    from website.features.summarization_engine.source_ingest.base import BaseIngestor

    package_name = __name__
    package_path = __path__  # type: ignore[name-defined]

    for _, modname, ispkg in pkgutil.iter_modules(package_path):
        if not ispkg:
            continue
        sub_pkg = f"{package_name}.{modname}"
        try:
            mod = importlib.import_module(f"{sub_pkg}.ingest")
        except ModuleNotFoundError:
            continue
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseIngestor)
                and obj is not BaseIngestor
                and hasattr(obj, "source_type")
            ):
                register_ingestor(obj)


_auto_discover()
```

- [ ] **Step 5: Run tests, commit**

Run: `pytest website/features/summarization_engine/tests/unit/test_ingest_registry.py -v`
Expected: 3 passed.

```bash
git add website/features/summarization_engine/source_ingest/ website/features/summarization_engine/tests/unit/test_ingest_registry.py
git commit -m "feat(engine): add base ingestor + auto-discovery registry"
```

### Task 1.7: Orchestrator skeleton (compose router + ingestor + summarizer stubs)

**Files:**
- Create: `website/features/summarization_engine/core/orchestrator.py`
- Create: `website/features/summarization_engine/tests/unit/test_orchestrator.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/test_orchestrator.py`:

```python
"""Orchestrator tests with mocked ingestor and summarizer."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from website.features.summarization_engine.core.models import (
    IngestResult,
    SourceType,
    SummaryResult,
    SummaryMetadata,
    DetailedSummarySection,
)


@pytest.mark.asyncio
async def test_orchestrator_routes_and_calls_ingestor_then_summarizer():
    from website.features.summarization_engine.core.orchestrator import summarize_url

    fake_ingest = IngestResult(
        source_type=SourceType.GITHUB,
        url="https://github.com/foo/bar",
        original_url="https://github.com/foo/bar",
        raw_text="README content",
        extraction_confidence="high",
        confidence_reason="readme ok",
        fetched_at=datetime.now(timezone.utc),
    )
    fake_meta = SummaryMetadata(
        source_type=SourceType.GITHUB,
        url="https://github.com/foo/bar",
        extraction_confidence="high",
        confidence_reason="readme ok",
        total_tokens_used=100,
        gemini_pro_tokens=100,
        gemini_flash_tokens=0,
        total_latency_ms=1500,
        cod_iterations_used=2,
        self_check_missing_count=0,
        patch_applied=False,
    )
    fake_summary = SummaryResult(
        mini_title="Fake GitHub repo summary",
        brief_summary="A fake repo used for testing the orchestrator pipeline flow.",
        tags=["github", "test", "python", "fake", "orchestrator", "pipeline", "demo", "sample"],
        detailed_summary=[DetailedSummarySection(heading="Overview", bullets=["Fake data"])],
        metadata=fake_meta,
    )

    mock_ingestor = AsyncMock()
    mock_ingestor.ingest.return_value = fake_ingest
    mock_summarizer = AsyncMock()
    mock_summarizer.summarize.return_value = fake_summary

    with patch(
        "website.features.summarization_engine.core.orchestrator.get_ingestor"
    ) as gi, patch(
        "website.features.summarization_engine.core.orchestrator.get_summarizer"
    ) as gs:
        gi.return_value = lambda: mock_ingestor
        gs.return_value = lambda client, config: mock_summarizer

        result = await summarize_url(
            "https://github.com/foo/bar",
            user_id=UUID("00000000-0000-0000-0000-000000000001"),
            gemini_client=AsyncMock(),
        )

    assert result.mini_title == "Fake GitHub repo summary"
    assert result.metadata.source_type == SourceType.GITHUB
    mock_ingestor.ingest.assert_awaited_once()
    mock_summarizer.summarize.assert_awaited_once()
```

- [ ] **Step 2: Create summarization base + registry stubs (needed by orchestrator)**

Create `website/features/summarization_engine/summarization/base.py`:

```python
"""Base class for all source summarizers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.core.models import (
    IngestResult,
    SourceType,
    SummaryResult,
)


class BaseSummarizer(ABC):
    """Abstract base class for per-source summarizers."""

    source_type: ClassVar[SourceType]

    def __init__(self, gemini_client: TieredGeminiClient, config: dict[str, Any]):
        self._client = gemini_client
        self._config = config

    @abstractmethod
    async def summarize(self, ingest: IngestResult) -> SummaryResult:
        raise NotImplementedError
```

Overwrite `website/features/summarization_engine/summarization/__init__.py`:

```python
"""Auto-discovery registry for source summarizers."""
from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

from website.features.summarization_engine.core.errors import RoutingError
from website.features.summarization_engine.core.models import SourceType

if TYPE_CHECKING:
    from website.features.summarization_engine.summarization.base import BaseSummarizer


_REGISTRY: dict[SourceType, type["BaseSummarizer"]] = {}


def register_summarizer(cls: type["BaseSummarizer"]) -> None:
    if not hasattr(cls, "source_type"):
        return
    _REGISTRY[cls.source_type] = cls


def get_summarizer(source_type: SourceType | str) -> type["BaseSummarizer"]:
    if source_type not in _REGISTRY:
        raise RoutingError(f"No summarizer registered for {source_type!r}", url="")
    return _REGISTRY[source_type]


def list_summarizers() -> dict[SourceType, type["BaseSummarizer"]]:
    return dict(_REGISTRY)


def _auto_discover() -> None:
    from website.features.summarization_engine.summarization.base import BaseSummarizer

    package_name = __name__
    package_path = __path__  # type: ignore[name-defined]

    for _, modname, ispkg in pkgutil.iter_modules(package_path):
        if not ispkg or modname == "common":
            continue
        sub_pkg = f"{package_name}.{modname}"
        try:
            mod = importlib.import_module(f"{sub_pkg}.summarizer")
        except ModuleNotFoundError:
            continue
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseSummarizer)
                and obj is not BaseSummarizer
                and hasattr(obj, "source_type")
            ):
                register_summarizer(obj)


_auto_discover()
```

- [ ] **Step 3: Implement orchestrator**

Create `website/features/summarization_engine/core/orchestrator.py`:

```python
"""Single-URL orchestrator: route → ingest → summarize → return.

Does NOT write anything. Callers compose writers.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.core.errors import EngineError
from website.features.summarization_engine.core.models import (
    SourceType,
    SummaryResult,
)
from website.features.summarization_engine.core.router import detect_source_type
from website.features.summarization_engine.source_ingest import get_ingestor
from website.features.summarization_engine.summarization import get_summarizer

logger = logging.getLogger("summarization_engine.orchestrator")


async def summarize_url(
    url: str,
    *,
    user_id: UUID,
    gemini_client: Any,
    source_type: SourceType | None = None,
) -> SummaryResult:
    """Run the full ingest → summarize pipeline for a single URL.

    Args:
        url: The URL to process.
        user_id: Authenticated user UUID (stored in SummaryMetadata).
        gemini_client: A TieredGeminiClient instance (for summarization).
        source_type: Optional override; auto-detected if None.

    Returns:
        SummaryResult — the caller composes writers.

    Raises:
        EngineError: any failure in the pipeline.
    """
    config = load_config()

    effective_source_type = source_type or detect_source_type(url)
    logger.info(
        "orchestrator.start url=%s user=%s source_type=%s",
        url, user_id, effective_source_type.value,
    )

    ingestor_cls = get_ingestor(effective_source_type)
    ingestor = ingestor_cls()
    source_config = config.sources.get(effective_source_type.value, {})
    ingest_result = await ingestor.ingest(url, config=source_config)
    logger.info(
        "orchestrator.ingested url=%s confidence=%s text_len=%d",
        url, ingest_result.extraction_confidence, len(ingest_result.raw_text),
    )

    summarizer_cls = get_summarizer(effective_source_type)
    summarizer = summarizer_cls(gemini_client, source_config)
    summary = await summarizer.summarize(ingest_result)
    logger.info(
        "orchestrator.summarized url=%s tokens=%d latency_ms=%d",
        url, summary.metadata.total_tokens_used, summary.metadata.total_latency_ms,
    )

    return summary
```

- [ ] **Step 4: Run tests, commit**

Run: `pytest website/features/summarization_engine/tests/unit/test_orchestrator.py -v`
Expected: 1 passed.

```bash
git add website/features/summarization_engine/core/orchestrator.py website/features/summarization_engine/summarization/base.py website/features/summarization_engine/summarization/__init__.py website/features/summarization_engine/tests/unit/test_orchestrator.py
git commit -m "feat(engine): add orchestrator + summarization base/registry"
```

---

## Phase 2: Ingestors Batch 1 (GitHub, HackerNews, arXiv)

These three sources have the most reliable APIs and should ship first.

### Task 2.1: GitHub ingestor

**Files:**
- Create: `website/features/summarization_engine/source_ingest/github/__init__.py` (empty)
- Create: `website/features/summarization_engine/source_ingest/github/ingest.py`
- Create: `website/features/summarization_engine/tests/unit/ingest/test_github_ingest.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/ingest/test_github_ingest.py`:

```python
"""GitHub ingestor tests with mocked httpx."""
import base64
import pytest
from pytest_httpx import HTTPXMock

from website.features.summarization_engine.source_ingest.github.ingest import (
    GitHubIngestor,
)
from website.features.summarization_engine.core.models import SourceType


@pytest.mark.asyncio
async def test_github_ingest_public_repo(httpx_mock: HTTPXMock):
    owner, repo = "anthropic-ai", "anthropic-sdk-python"

    httpx_mock.add_response(
        url=f"https://api.github.com/repos/{owner}/{repo}",
        json={
            "name": repo,
            "full_name": f"{owner}/{repo}",
            "description": "Official Anthropic SDK",
            "stargazers_count": 1234,
            "forks_count": 56,
            "language": "Python",
            "topics": ["ai", "llm", "anthropic"],
            "license": {"spdx_id": "MIT"},
            "updated_at": "2026-04-01T00:00:00Z",
        },
    )
    readme_content = "# anthropic-sdk-python\n\nOfficial SDK for Anthropic's Claude API.\n\n## Install\n\n```\npip install anthropic\n```\n\nThis is the official Python SDK for Anthropic's Claude models with full support for streaming, tool use, and vision."
    httpx_mock.add_response(
        url=f"https://api.github.com/repos/{owner}/{repo}/readme",
        json={
            "content": base64.b64encode(readme_content.encode()).decode(),
            "encoding": "base64",
        },
    )
    httpx_mock.add_response(
        url=f"https://api.github.com/repos/{owner}/{repo}/languages",
        json={"Python": 10000, "Shell": 500},
    )
    httpx_mock.add_response(
        url=f"https://api.github.com/repos/{owner}/{repo}/issues",
        json=[{"number": 1, "title": "Bug: fix X", "body": "details"}],
    )
    httpx_mock.add_response(
        url=f"https://api.github.com/repos/{owner}/{repo}/commits",
        json=[{"sha": "abc", "commit": {"message": "feat: add Y"}}],
    )

    ingestor = GitHubIngestor()
    result = await ingestor.ingest(
        f"https://github.com/{owner}/{repo}",
        config={"fetch_issues": True, "max_issues": 20, "fetch_commits": True, "max_commits": 10},
    )

    assert result.source_type == SourceType.GITHUB
    assert "anthropic-sdk-python" in result.raw_text
    assert "Official SDK" in result.raw_text
    assert result.metadata["stars"] == 1234
    assert result.metadata["language"] == "Python"
    assert result.extraction_confidence == "high"


@pytest.mark.asyncio
async def test_github_ingest_404_raises(httpx_mock: HTTPXMock):
    from website.features.summarization_engine.core.errors import ExtractionError

    httpx_mock.add_response(
        url="https://api.github.com/repos/foo/nonexistent",
        status_code=404,
    )

    ingestor = GitHubIngestor()
    with pytest.raises(ExtractionError) as exc_info:
        await ingestor.ingest(
            "https://github.com/foo/nonexistent",
            config={"fetch_issues": False, "fetch_commits": False},
        )
    assert "404" in exc_info.value.reason or "not found" in exc_info.value.reason.lower()


@pytest.mark.asyncio
async def test_github_ingest_rate_limited_low_confidence(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/foo/bar",
        status_code=403,
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "9999999999"},
    )

    ingestor = GitHubIngestor()
    from website.features.summarization_engine.core.errors import ExtractionError
    with pytest.raises(ExtractionError) as exc:
        await ingestor.ingest(
            "https://github.com/foo/bar",
            config={"fetch_issues": False, "fetch_commits": False},
        )
    assert "rate" in exc.value.reason.lower()
```

- [ ] **Step 2: Run test (expect fail)**

Run: `pytest website/features/summarization_engine/tests/unit/ingest/test_github_ingest.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement GitHubIngestor**

Create `website/features/summarization_engine/source_ingest/github/__init__.py` (empty file).

Create `website/features/summarization_engine/source_ingest/github/ingest.py`:

```python
"""GitHub repository ingestor.

Uses the GitHub REST API v3 to extract README, metadata, open issues, and
recent commits for a repository. Handles rate limits via X-RateLimit headers.
"""
from __future__ import annotations

import base64
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, ClassVar
from urllib.parse import urlparse

import httpx

from website.features.summarization_engine.core.errors import ExtractionError
from website.features.summarization_engine.core.models import (
    IngestResult,
    SourceType,
)
from website.features.summarization_engine.source_ingest.base import BaseIngestor

logger = logging.getLogger("summarization_engine.ingest.github")

_REPO_URL_RE = re.compile(r"^/([^/]+)/([^/]+)(?:/|$)")


class GitHubIngestor(BaseIngestor):
    """Fetches README + metadata + issues + commits from a GitHub repository."""

    source_type: ClassVar[SourceType] = SourceType.GITHUB

    def __init__(self, token: str | None = None, timeout_sec: float = 30.0):
        self._token = token or os.environ.get("GITHUB_TOKEN", "")
        self._timeout = timeout_sec

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        owner, repo = self._parse_repo(url)
        headers = self._headers()

        async with httpx.AsyncClient(timeout=self._timeout, headers=headers) as client:
            metadata = await self._fetch_metadata(client, owner, repo)
            readme = await self._fetch_readme(client, owner, repo)
            languages = await self._fetch_languages(client, owner, repo)

            issues_text = ""
            if config.get("fetch_issues", True):
                issues_text = await self._fetch_issues(
                    client, owner, repo, config.get("max_issues", 20),
                )
            commits_text = ""
            if config.get("fetch_commits", True):
                commits_text = await self._fetch_commits(
                    client, owner, repo, config.get("max_commits", 10),
                )

        sections = {
            "metadata": self._format_metadata(metadata, languages),
            "readme": readme or "(no README)",
        }
        if issues_text:
            sections["open_issues"] = issues_text
        if commits_text:
            sections["recent_commits"] = commits_text

        raw_text = "\n\n".join(f"## {k.upper()}\n{v}" for k, v in sections.items())

        confidence, reason = self._score_confidence(readme, metadata)

        return IngestResult(
            source_type=SourceType.GITHUB,
            url=url,
            original_url=url,
            raw_text=raw_text,
            sections=sections,
            metadata={
                "title": metadata.get("full_name", f"{owner}/{repo}"),
                "description": metadata.get("description"),
                "stars": metadata.get("stargazers_count"),
                "forks": metadata.get("forks_count"),
                "language": metadata.get("language"),
                "topics": metadata.get("topics", []),
                "license": (metadata.get("license") or {}).get("spdx_id"),
                "updated_at": metadata.get("updated_at"),
                "languages_bytes": languages,
            },
            extraction_confidence=confidence,
            confidence_reason=reason,
            fetched_at=datetime.now(timezone.utc),
        )

    def _parse_repo(self, url: str) -> tuple[str, str]:
        parsed = urlparse(url)
        m = _REPO_URL_RE.match(parsed.path or "")
        if not m:
            raise ExtractionError(
                f"Could not parse owner/repo from {url!r}",
                source_type=self.source_type.value,
                reason="bad-url",
            )
        owner = m.group(1)
        repo = m.group(2).removesuffix(".git")
        return owner, repo

    def _headers(self) -> dict[str, str]:
        h = {
            "Accept": "application/vnd.github.mercy-preview+json",
            "User-Agent": "zettelkasten-engine/2.0",
        }
        if self._token:
            h["Authorization"] = f"token {self._token}"
        return h

    async def _fetch_metadata(self, client: httpx.AsyncClient, owner: str, repo: str) -> dict[str, Any]:
        r = await client.get(f"https://api.github.com/repos/{owner}/{repo}")
        if r.status_code == 404:
            raise ExtractionError(
                f"Repository not found: {owner}/{repo}",
                source_type=self.source_type.value,
                reason="404 not found",
            )
        if r.status_code == 403 and r.headers.get("X-RateLimit-Remaining") == "0":
            raise ExtractionError(
                "GitHub rate limit exceeded",
                source_type=self.source_type.value,
                reason="rate limited",
            )
        r.raise_for_status()
        return r.json()

    async def _fetch_readme(self, client: httpx.AsyncClient, owner: str, repo: str) -> str:
        try:
            r = await client.get(f"https://api.github.com/repos/{owner}/{repo}/readme")
            if r.status_code != 200:
                return ""
            data = r.json()
            if data.get("encoding") == "base64":
                return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            return data.get("content", "")
        except Exception as exc:
            logger.warning("readme fetch failed: %s", exc)
            return ""

    async def _fetch_languages(self, client: httpx.AsyncClient, owner: str, repo: str) -> dict[str, int]:
        try:
            r = await client.get(f"https://api.github.com/repos/{owner}/{repo}/languages")
            return r.json() if r.status_code == 200 else {}
        except Exception:
            return {}

    async def _fetch_issues(
        self, client: httpx.AsyncClient, owner: str, repo: str, max_issues: int
    ) -> str:
        try:
            r = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/issues",
                params={"state": "open", "sort": "updated", "per_page": max_issues},
            )
            if r.status_code != 200:
                return ""
            issues = r.json()
            lines = []
            for it in issues[:max_issues]:
                title = it.get("title", "")
                body = (it.get("body") or "").strip()[:500]
                lines.append(f"- #{it.get('number')}: {title}\n  {body}")
            return "\n".join(lines)
        except Exception:
            return ""

    async def _fetch_commits(
        self, client: httpx.AsyncClient, owner: str, repo: str, max_commits: int
    ) -> str:
        try:
            r = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/commits",
                params={"per_page": max_commits},
            )
            if r.status_code != 200:
                return ""
            commits = r.json()
            lines = []
            for c in commits[:max_commits]:
                msg = (c.get("commit", {}).get("message") or "").split("\n")[0]
                sha = (c.get("sha") or "")[:7]
                lines.append(f"- {sha}: {msg}")
            return "\n".join(lines)
        except Exception:
            return ""

    def _format_metadata(self, meta: dict[str, Any], languages: dict[str, int]) -> str:
        lines = [
            f"Full name: {meta.get('full_name', '')}",
            f"Description: {meta.get('description', '(none)')}",
            f"Stars: {meta.get('stargazers_count', 0)}",
            f"Forks: {meta.get('forks_count', 0)}",
            f"Primary language: {meta.get('language', '(unknown)')}",
            f"Topics: {', '.join(meta.get('topics', []) or [])}",
            f"License: {(meta.get('license') or {}).get('spdx_id', '(none)')}",
        ]
        if languages:
            total = sum(languages.values()) or 1
            top = sorted(languages.items(), key=lambda kv: -kv[1])[:5]
            lang_str = ", ".join(f"{k} {v*100//total}%" for k, v in top)
            lines.append(f"Language breakdown: {lang_str}")
        return "\n".join(lines)

    def _score_confidence(
        self, readme: str, metadata: dict[str, Any]
    ) -> tuple[str, str]:
        has_topics = bool(metadata.get("topics"))
        readme_len = len(readme or "")
        if readme_len >= 500 and has_topics:
            return "high", f"readme {readme_len} chars + topics"
        if readme_len >= 500:
            return "medium", f"readme {readme_len} chars, no topics"
        if readme:
            return "medium", f"readme only {readme_len} chars"
        return "low", "no readme"
```

- [ ] **Step 4: Run tests**

Run: `pytest website/features/summarization_engine/tests/unit/ingest/test_github_ingest.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/source_ingest/github/ website/features/summarization_engine/tests/unit/ingest/test_github_ingest.py
git commit -m "feat(engine): add GitHub ingestor with REST API + confidence scoring"
```

### Task 2.2: HackerNews ingestor

**Files:**
- Create: `website/features/summarization_engine/source_ingest/hackernews/__init__.py` (empty)
- Create: `website/features/summarization_engine/source_ingest/hackernews/ingest.py`
- Create: `website/features/summarization_engine/tests/unit/ingest/test_hackernews_ingest.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/ingest/test_hackernews_ingest.py`:

```python
"""HackerNews ingestor tests with mocked Algolia HN API."""
import pytest
from pytest_httpx import HTTPXMock

from website.features.summarization_engine.source_ingest.hackernews.ingest import (
    HackerNewsIngestor,
)
from website.features.summarization_engine.core.models import SourceType


@pytest.mark.asyncio
async def test_hn_ingest_with_linked_article(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url="https://hn.algolia.com/api/v1/items/40123456",
        json={
            "id": 40123456,
            "created_at": "2026-04-01T12:00:00Z",
            "author": "alice",
            "title": "Interesting article about Rust",
            "url": "https://blog.example.com/rust-post",
            "points": 250,
            "text": None,
            "children": [
                {
                    "id": 1, "author": "bob", "text": "Great post! I agree.",
                    "points": 50, "children": [],
                },
                {
                    "id": 2, "author": "carol", "text": "I disagree because X.",
                    "points": 30, "children": [],
                },
                {
                    "id": 3, "author": None, "text": "[dead]", "points": 0, "children": [],
                },
            ],
        },
    )
    # linked article fetch will happen via trafilatura — mock it
    httpx_mock.add_response(
        url="https://blog.example.com/rust-post",
        html="<html><body><article>Article body about Rust with enough content to be extracted.</article></body></html>",
    )

    ingestor = HackerNewsIngestor()
    result = await ingestor.ingest(
        "https://news.ycombinator.com/item?id=40123456",
        config={"max_comments": 100, "comment_min_points": 5, "include_linked_article": True},
    )

    assert result.source_type == SourceType.HACKERNEWS
    assert "Interesting article about Rust" in result.raw_text
    assert "bob" in result.raw_text or "Great post" in result.raw_text
    assert "[dead]" not in result.raw_text
    assert result.metadata["points"] == 250
    assert result.metadata["author"] == "alice"


@pytest.mark.asyncio
async def test_hn_ingest_self_post(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url="https://hn.algolia.com/api/v1/items/999",
        json={
            "id": 999,
            "created_at": "2026-04-01T12:00:00Z",
            "author": "alice",
            "title": "Ask HN: How do you learn Rust?",
            "url": None,
            "text": "I'm a Python developer and want to learn Rust. Any tips?",
            "points": 50,
            "children": [],
        },
    )

    ingestor = HackerNewsIngestor()
    result = await ingestor.ingest(
        "https://news.ycombinator.com/item?id=999",
        config={"include_linked_article": True},
    )

    assert result.source_type == SourceType.HACKERNEWS
    assert "Ask HN" in result.raw_text
    assert "learn Rust" in result.raw_text
    assert result.metadata.get("linked_url") is None
```

- [ ] **Step 2: Run test (fail)**

Run: `pytest website/features/summarization_engine/tests/unit/ingest/test_hackernews_ingest.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement HackerNewsIngestor**

Create `website/features/summarization_engine/source_ingest/hackernews/__init__.py` (empty).

Create `website/features/summarization_engine/source_ingest/hackernews/ingest.py`:

```python
"""HackerNews ingestor via the Algolia HN API.

Fetches a story + full comment tree in one call. Optionally fetches the
linked article using trafilatura. Ranks comments by points.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlparse

import httpx

from website.features.summarization_engine.core.errors import ExtractionError
from website.features.summarization_engine.core.models import (
    IngestResult,
    SourceType,
)
from website.features.summarization_engine.source_ingest.base import BaseIngestor

logger = logging.getLogger("summarization_engine.ingest.hackernews")


class HackerNewsIngestor(BaseIngestor):
    source_type: ClassVar[SourceType] = SourceType.HACKERNEWS

    def __init__(self, timeout_sec: float = 30.0):
        self._timeout = timeout_sec

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        item_id = self._parse_item_id(url)
        max_comments = config.get("max_comments", 100)
        min_points = config.get("comment_min_points", 5)
        include_article = config.get("include_linked_article", True)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            item = await self._fetch_item(client, item_id)

            linked_url = item.get("url")
            article_text = ""
            if include_article and linked_url:
                article_text = await self._fetch_linked_article(client, linked_url)

        comments_text = self._render_comments(item.get("children") or [], max_comments, min_points)

        sections: dict[str, str] = {
            "title": item.get("title", ""),
            "submission_meta": self._format_submission_meta(item),
        }
        if item.get("text"):
            sections["submission_text"] = item["text"]
        if article_text:
            sections["linked_article"] = article_text
        if comments_text:
            sections["top_comments"] = comments_text

        raw_text = "\n\n".join(f"## {k.upper().replace('_', ' ')}\n{v}" for k, v in sections.items() if v)

        confidence, reason = self._score_confidence(article_text, comments_text, item)

        return IngestResult(
            source_type=SourceType.HACKERNEWS,
            url=url, original_url=url,
            raw_text=raw_text,
            sections=sections,
            metadata={
                "title": item.get("title"),
                "author": item.get("author"),
                "points": item.get("points"),
                "created_at": item.get("created_at"),
                "linked_url": linked_url,
                "comment_count": len(item.get("children") or []),
            },
            extraction_confidence=confidence,
            confidence_reason=reason,
            fetched_at=datetime.now(timezone.utc),
        )

    def _parse_item_id(self, url: str) -> int:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        raw = (qs.get("id") or [None])[0]
        if raw is None:
            raise ExtractionError(
                f"Could not parse HN item id from {url!r}",
                source_type=self.source_type.value, reason="bad-url",
            )
        try:
            return int(raw)
        except ValueError:
            raise ExtractionError(
                f"Invalid HN id: {raw!r}",
                source_type=self.source_type.value, reason="bad-id",
            )

    async def _fetch_item(self, client: httpx.AsyncClient, item_id: int) -> dict[str, Any]:
        r = await client.get(f"https://hn.algolia.com/api/v1/items/{item_id}")
        if r.status_code == 404:
            raise ExtractionError(
                f"HN item {item_id} not found",
                source_type=self.source_type.value, reason="404",
            )
        r.raise_for_status()
        return r.json()

    async def _fetch_linked_article(self, client: httpx.AsyncClient, url: str) -> str:
        """Best-effort fetch of the linked article via trafilatura."""
        try:
            import trafilatura
            r = await client.get(url, timeout=20.0, follow_redirects=True)
            if r.status_code != 200:
                return ""
            text = trafilatura.extract(r.text) or ""
            return text
        except Exception as exc:
            logger.warning("linked article fetch failed: %s", exc)
            return ""

    def _render_comments(
        self,
        children: list[dict[str, Any]],
        max_comments: int,
        min_points: int,
        depth: int = 0,
    ) -> str:
        """Recursively render top N comments ranked by points."""
        if not children or depth > 2:
            return ""
        filtered: list[dict[str, Any]] = []
        for c in children:
            if not c.get("author"):
                continue
            text = (c.get("text") or "").strip()
            if not text or text.startswith("[dead]") or text.startswith("[flagged]"):
                continue
            filtered.append(c)
        filtered.sort(key=lambda c: c.get("points") or 0, reverse=True)
        filtered = filtered[:max_comments]

        lines: list[str] = []
        for c in filtered:
            indent = "  " * depth
            author = c.get("author", "?")
            points = c.get("points") or 0
            text = (c.get("text") or "")[:800]
            lines.append(f"{indent}- [{author} · {points} pts] {text}")
            if depth < 1:
                reply_text = self._render_comments(
                    c.get("children") or [], max_comments=5, min_points=min_points, depth=depth + 1,
                )
                if reply_text:
                    lines.append(reply_text)
        return "\n".join(lines)

    def _format_submission_meta(self, item: dict[str, Any]) -> str:
        return (
            f"Submitted by: {item.get('author')}\n"
            f"Points: {item.get('points')}\n"
            f"Created: {item.get('created_at')}\n"
            f"URL: {item.get('url') or '(self-post)'}"
        )

    def _score_confidence(self, article_text: str, comments_text: str, item: dict[str, Any]) -> tuple[str, str]:
        points = item.get("points") or 0
        comments_ok = len(comments_text) >= 500
        if article_text and len(article_text) >= 1000 and comments_ok and points >= 50:
            return "high", f"article {len(article_text)} chars + {len(comments_text)} chars comments + {points} pts"
        if comments_ok:
            return "medium", f"comments {len(comments_text)} chars, article fetch {'ok' if article_text else 'failed'}"
        return "low", "sparse content"
```

- [ ] **Step 4: Run tests**

Run: `pytest website/features/summarization_engine/tests/unit/ingest/test_hackernews_ingest.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/source_ingest/hackernews/ website/features/summarization_engine/tests/unit/ingest/test_hackernews_ingest.py
git commit -m "feat(engine): add HackerNews ingestor via Algolia API"
```

### Task 2.3: arXiv ingestor

**Files:**
- Create: `website/features/summarization_engine/source_ingest/arxiv/__init__.py` (empty)
- Create: `website/features/summarization_engine/source_ingest/arxiv/ingest.py`
- Create: `website/features/summarization_engine/tests/unit/ingest/test_arxiv_ingest.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/ingest/test_arxiv_ingest.py`:

```python
"""arXiv ingestor tests with mocked API + HTML versions."""
import pytest
from pytest_httpx import HTTPXMock

from website.features.summarization_engine.source_ingest.arxiv.ingest import (
    ArxivIngestor,
    extract_arxiv_id,
)
from website.features.summarization_engine.core.models import SourceType


def test_extract_arxiv_id_from_abs_url():
    assert extract_arxiv_id("https://arxiv.org/abs/2310.11511") == "2310.11511"
    assert extract_arxiv_id("https://arxiv.org/abs/2310.11511v2") == "2310.11511"
    assert extract_arxiv_id("https://arxiv.org/pdf/2310.11511.pdf") == "2310.11511"
    assert extract_arxiv_id("https://ar5iv.labs.arxiv.org/html/2310.11511") == "2310.11511"
    assert extract_arxiv_id("https://arxiv.org/abs/cs.AI/0403059") == "cs.AI/0403059"


def test_extract_arxiv_id_bad_url():
    assert extract_arxiv_id("https://example.com/foo") is None


@pytest.mark.asyncio
async def test_arxiv_ingest_uses_html_version(httpx_mock: HTTPXMock):
    atom_feed = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2310.11511v1</id>
    <title>Self-RAG: Learning to Retrieve, Generate, and Critique</title>
    <summary>This paper introduces Self-RAG, a framework for...</summary>
    <author><name>Akari Asai</name></author>
    <author><name>Zeqiu Wu</name></author>
    <published>2023-10-17T00:00:00Z</published>
    <category term="cs.CL"/>
  </entry>
</feed>"""
    httpx_mock.add_response(
        url="http://export.arxiv.org/api/query?id_list=2310.11511",
        text=atom_feed,
    )
    html_body = """<html><body>
    <section><h2>Introduction</h2><p>We propose Self-RAG, a method for adaptive retrieval.</p></section>
    <section><h2>Method</h2><p>Our approach uses reflection tokens.</p></section>
    <section><h2>Results</h2><p>We achieve state-of-the-art on multiple benchmarks.</p></section>
    </body></html>"""
    httpx_mock.add_response(
        url="https://arxiv.org/html/2310.11511",
        text=html_body,
    )

    ingestor = ArxivIngestor()
    result = await ingestor.ingest(
        "https://arxiv.org/abs/2310.11511",
        config={"prefer_html_version": True, "pdf_parser": "pymupdf", "rate_limit_delay_sec": 0.0},
    )

    assert result.source_type == SourceType.ARXIV
    assert "Self-RAG" in result.raw_text
    assert "adaptive retrieval" in result.raw_text or "reflection tokens" in result.raw_text
    assert result.metadata["arxiv_id"] == "2310.11511"
    assert "Akari Asai" in result.metadata["authors"]
    assert result.extraction_confidence in ("high", "medium")
```

- [ ] **Step 2: Run test (fail)**

Run: `pytest website/features/summarization_engine/tests/unit/ingest/test_arxiv_ingest.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement ArxivIngestor**

Create `website/features/summarization_engine/source_ingest/arxiv/__init__.py` (empty).

Create `website/features/summarization_engine/source_ingest/arxiv/ingest.py`:

```python
"""arXiv paper ingestor.

Fetches paper metadata via the arXiv API (Atom feed, parsed with feedparser)
and full text via the HTML version (preferred), ar5iv, or PDF parsing with
PyMuPDF as fallback.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, ClassVar

import httpx

from website.features.summarization_engine.core.errors import ExtractionError
from website.features.summarization_engine.core.models import (
    IngestResult,
    SourceType,
)
from website.features.summarization_engine.source_ingest.base import BaseIngestor

logger = logging.getLogger("summarization_engine.ingest.arxiv")

_ARXIV_ID_RE = re.compile(
    r"arxiv\.org/(?:abs|pdf|html)/([a-z\-]+(?:\.[A-Z]{2})?/\d+|\d{4}\.\d{4,5})(?:v\d+)?",
    re.IGNORECASE,
)
_AR5IV_ID_RE = re.compile(
    r"ar5iv\.labs\.arxiv\.org/html/([a-z\-]+(?:\.[A-Z]{2})?/\d+|\d{4}\.\d{4,5})",
    re.IGNORECASE,
)


def extract_arxiv_id(url: str) -> str | None:
    for rx in (_ARXIV_ID_RE, _AR5IV_ID_RE):
        m = rx.search(url)
        if m:
            return m.group(1)
    return None


class ArxivIngestor(BaseIngestor):
    source_type: ClassVar[SourceType] = SourceType.ARXIV

    def __init__(self, timeout_sec: float = 60.0):
        self._timeout = timeout_sec

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        arxiv_id = extract_arxiv_id(url)
        if not arxiv_id:
            raise ExtractionError(
                f"Could not parse arXiv id from {url!r}",
                source_type=self.source_type.value, reason="bad-url",
            )

        delay = config.get("rate_limit_delay_sec", 3.0)
        prefer_html = config.get("prefer_html_version", True)

        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            metadata = await self._fetch_metadata(client, arxiv_id)
            if delay > 0:
                await asyncio.sleep(delay)

            body_text = ""
            body_source = ""
            if prefer_html:
                body_text = await self._fetch_html(client, arxiv_id)
                if body_text:
                    body_source = "arxiv.org/html"
                else:
                    body_text = await self._fetch_ar5iv(client, arxiv_id)
                    if body_text:
                        body_source = "ar5iv"
            if not body_text:
                body_text = await self._fetch_pdf_text(client, arxiv_id)
                if body_text:
                    body_source = f"pdf ({config.get('pdf_parser', 'pymupdf')})"

        sections = {"metadata": self._format_metadata(metadata, arxiv_id)}
        if metadata.get("summary"):
            sections["abstract"] = metadata["summary"]
        if body_text:
            sections["body"] = body_text[:60000]  # cap to ~60k chars

        raw_text = "\n\n".join(f"## {k.upper()}\n{v}" for k, v in sections.items())

        confidence, reason = self._score_confidence(metadata, body_text)

        return IngestResult(
            source_type=SourceType.ARXIV,
            url=url, original_url=url,
            raw_text=raw_text, sections=sections,
            metadata={
                "arxiv_id": arxiv_id,
                "title": metadata.get("title"),
                "authors": metadata.get("authors", []),
                "published": metadata.get("published"),
                "categories": metadata.get("categories", []),
                "body_source": body_source,
            },
            extraction_confidence=confidence,
            confidence_reason=reason,
            fetched_at=datetime.now(timezone.utc),
        )

    async def _fetch_metadata(self, client: httpx.AsyncClient, arxiv_id: str) -> dict[str, Any]:
        import feedparser
        r = await client.get(
            "http://export.arxiv.org/api/query",
            params={"id_list": arxiv_id},
        )
        r.raise_for_status()
        feed = feedparser.parse(r.text)
        if not feed.entries:
            raise ExtractionError(
                f"arXiv returned no entries for {arxiv_id}",
                source_type=self.source_type.value, reason="no-entry",
            )
        e = feed.entries[0]
        return {
            "title": (e.get("title") or "").replace("\n", " ").strip(),
            "summary": (e.get("summary") or "").strip(),
            "authors": [a.get("name", "") for a in e.get("authors", [])],
            "published": e.get("published"),
            "categories": [t.get("term", "") for t in e.get("tags", [])],
        }

    async def _fetch_html(self, client: httpx.AsyncClient, arxiv_id: str) -> str:
        try:
            r = await client.get(f"https://arxiv.org/html/{arxiv_id}")
            if r.status_code == 200:
                return self._strip_html(r.text)
        except Exception as exc:
            logger.debug("arxiv.org/html fetch failed: %s", exc)
        return ""

    async def _fetch_ar5iv(self, client: httpx.AsyncClient, arxiv_id: str) -> str:
        try:
            r = await client.get(f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}")
            if r.status_code == 200:
                return self._strip_html(r.text)
        except Exception as exc:
            logger.debug("ar5iv fetch failed: %s", exc)
        return ""

    async def _fetch_pdf_text(self, client: httpx.AsyncClient, arxiv_id: str) -> str:
        try:
            r = await client.get(f"https://arxiv.org/pdf/{arxiv_id}")
            if r.status_code != 200:
                return ""
            import fitz  # PyMuPDF
            doc = fitz.open(stream=r.content, filetype="pdf")
            chunks = []
            for page in doc:
                chunks.append(page.get_text("text"))
            doc.close()
            return "\n".join(chunks)
        except Exception as exc:
            logger.warning("PDF fetch/parse failed: %s", exc)
            return ""

    def _strip_html(self, html: str) -> str:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)

    def _format_metadata(self, meta: dict[str, Any], arxiv_id: str) -> str:
        return (
            f"arXiv ID: {arxiv_id}\n"
            f"Title: {meta.get('title', '')}\n"
            f"Authors: {', '.join(meta.get('authors', []))}\n"
            f"Published: {meta.get('published', '')}\n"
            f"Categories: {', '.join(meta.get('categories', []))}"
        )

    def _score_confidence(self, meta: dict[str, Any], body_text: str) -> tuple[str, str]:
        has_metadata = bool(meta.get("title") and meta.get("authors"))
        body_len = len(body_text or "")
        if has_metadata and body_len >= 5000:
            return "high", f"metadata + {body_len} chars body"
        if has_metadata and body_len > 0:
            return "medium", f"metadata + partial body ({body_len} chars)"
        if has_metadata:
            return "medium", "metadata only, body fetch failed"
        return "low", "no metadata"
```

- [ ] **Step 4: Run tests**

Run: `pytest website/features/summarization_engine/tests/unit/ingest/test_arxiv_ingest.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/source_ingest/arxiv/ website/features/summarization_engine/tests/unit/ingest/test_arxiv_ingest.py
git commit -m "feat(engine): add arXiv ingestor with HTML + PDF fallback"
```

---

## Phase 3: Ingestors Batch 2 (Newsletters, Reddit, YouTube)

### Task 3.1: Newsletter / generic web ingestor

**Files:**
- Create: `website/features/summarization_engine/source_ingest/newsletters/__init__.py` (empty)
- Create: `website/features/summarization_engine/source_ingest/newsletters/ingest.py`
- Create: `website/features/summarization_engine/tests/unit/ingest/test_newsletter_ingest.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/ingest/test_newsletter_ingest.py`:

```python
"""Newsletter ingestor tests with mocked httpx."""
import pytest
from pytest_httpx import HTTPXMock

from website.features.summarization_engine.source_ingest.newsletters.ingest import (
    NewsletterIngestor,
)
from website.features.summarization_engine.core.models import SourceType


SAMPLE_ARTICLE_HTML = """<html>
<head>
<title>The Future of AI Agents</title>
<meta property="og:title" content="The Future of AI Agents">
<meta property="article:author" content="Jane Doe">
<script type="application/ld+json">
{"@type":"Article","headline":"The Future of AI Agents","author":{"name":"Jane Doe"},"datePublished":"2026-04-01","isAccessibleForFree":"True"}
</script>
</head>
<body>
<article>
<h1>The Future of AI Agents</h1>
<p>AI agents are transforming how we build software. This article explores the major trends.</p>
<p>First, agents are becoming more autonomous. Second, they are learning to use tools effectively. Third, multi-agent systems are emerging as a dominant architecture pattern.</p>
<p>The implications for engineering teams are significant: we now need to think about agent-oriented design patterns, observability for non-deterministic workflows, and evaluation frameworks that can handle open-ended outputs.</p>
</article>
</body>
</html>"""


@pytest.mark.asyncio
async def test_newsletter_ingest_public_article(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url="https://example.substack.com/p/future-of-ai-agents",
        html=SAMPLE_ARTICLE_HTML,
    )

    ingestor = NewsletterIngestor()
    result = await ingestor.ingest(
        "https://example.substack.com/p/future-of-ai-agents",
        config={
            "extractors": ["trafilatura"],
            "paywall_fallbacks": [],
            "googlebot_ua": True,
            "min_text_length": 100,
        },
    )

    assert result.source_type == SourceType.NEWSLETTER
    assert "AI agents" in result.raw_text
    assert "multi-agent systems" in result.raw_text
    assert result.metadata.get("title") == "The Future of AI Agents"
    assert result.extraction_confidence in ("high", "medium")


@pytest.mark.asyncio
async def test_newsletter_ingest_detects_paywall(httpx_mock: HTTPXMock):
    paywalled_html = """<html><body><article>
    <h1>Paid Post</h1>
    <p>This post is for paid subscribers. Subscribe to read.</p>
    </article></body></html>"""
    httpx_mock.add_response(
        url="https://example.substack.com/p/paid-post",
        html=paywalled_html,
    )

    ingestor = NewsletterIngestor()
    result = await ingestor.ingest(
        "https://example.substack.com/p/paid-post",
        config={
            "extractors": ["trafilatura"],
            "paywall_fallbacks": [],
            "googlebot_ua": True,
            "min_text_length": 500,
        },
    )
    assert result.extraction_confidence == "low"
    assert "paywall" in result.confidence_reason.lower() or "short" in result.confidence_reason.lower()
```

- [ ] **Step 2: Run test (fail)**

Run: `pytest website/features/summarization_engine/tests/unit/ingest/test_newsletter_ingest.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement NewsletterIngestor**

Create `website/features/summarization_engine/source_ingest/newsletters/__init__.py` (empty).

Create `website/features/summarization_engine/source_ingest/newsletters/ingest.py`:

```python
"""Newsletter / generic article ingestor.

Primary: trafilatura 2.x with Googlebot UA. Fallbacks: Wayback, archive.ph,
readability-lxml, newspaper4k. Detects paywalls via keyword matching and
JSON-LD isAccessibleForFree.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, ClassVar

import httpx
from bs4 import BeautifulSoup

from website.features.summarization_engine.core.errors import ExtractionError
from website.features.summarization_engine.core.models import (
    IngestResult,
    SourceType,
)
from website.features.summarization_engine.source_ingest.base import BaseIngestor

logger = logging.getLogger("summarization_engine.ingest.newsletter")

_PAYWALL_KEYWORDS = (
    "subscribe to read",
    "sign in to continue",
    "this post is for paid subscribers",
    "continue reading with a free account",
    "to read the rest of this post",
)

_GOOGLEBOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"


class NewsletterIngestor(BaseIngestor):
    source_type: ClassVar[SourceType] = SourceType.NEWSLETTER

    def __init__(self, timeout_sec: float = 30.0):
        self._timeout = timeout_sec

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        use_googlebot = config.get("googlebot_ua", True)
        min_length = config.get("min_text_length", 500)
        extractors = config.get("extractors", ["trafilatura", "readability", "newspaper4k"])
        paywall_fallbacks = config.get("paywall_fallbacks", ["wayback", "archive_ph"])

        ua = _GOOGLEBOT_UA if use_googlebot else "zettelkasten-engine/2.0"
        headers = {"User-Agent": ua}

        html = ""
        async with httpx.AsyncClient(timeout=self._timeout, headers=headers, follow_redirects=True) as client:
            try:
                r = await client.get(url)
                if r.status_code == 200:
                    html = r.text
            except Exception as exc:
                logger.warning("direct fetch failed: %s", exc)

            # Extract via chain
            text, meta = self._run_extractors(html, extractors)

            # Detect paywall / short content → try fallbacks
            is_paywalled = self._is_paywalled(html, text)
            if (not text or len(text) < min_length or is_paywalled) and paywall_fallbacks:
                text, meta = await self._run_paywall_fallbacks(
                    client, url, paywall_fallbacks, extractors, meta,
                )

        confidence, reason = self._score_confidence(text, meta, min_length)

        return IngestResult(
            source_type=SourceType.NEWSLETTER,
            url=url, original_url=url,
            raw_text=text or "(extraction failed)",
            sections={"body": text},
            metadata=meta,
            extraction_confidence=confidence,
            confidence_reason=reason,
            fetched_at=datetime.now(timezone.utc),
        )

    def _run_extractors(
        self, html: str, extractors: list[str]
    ) -> tuple[str, dict[str, Any]]:
        if not html:
            return "", {}
        meta = self._extract_metadata(html)
        text = ""
        for ext in extractors:
            if ext == "trafilatura":
                text = self._trafilatura_extract(html)
            elif ext == "readability":
                text = self._readability_extract(html)
            elif ext == "newspaper4k":
                text = self._newspaper4k_extract(html)
            if text and len(text) >= 500:
                break
        return text, meta

    def _trafilatura_extract(self, html: str) -> str:
        try:
            import trafilatura
            out = trafilatura.extract(
                html,
                favor_precision=True,
                include_comments=False,
                include_tables=False,
                output_format="markdown",
            )
            return out or ""
        except Exception as exc:
            logger.debug("trafilatura failed: %s", exc)
            return ""

    def _readability_extract(self, html: str) -> str:
        try:
            from readability import Document
            doc = Document(html)
            summary_html = doc.summary()
            soup = BeautifulSoup(summary_html, "html.parser")
            return soup.get_text(separator="\n", strip=True)
        except Exception as exc:
            logger.debug("readability failed: %s", exc)
            return ""

    def _newspaper4k_extract(self, html: str) -> str:
        try:
            from newspaper import Article
            article = Article("")
            article.set_html(html)
            article.parse()
            return article.text or ""
        except Exception as exc:
            logger.debug("newspaper4k failed: %s", exc)
            return ""

    def _extract_metadata(self, html: str) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        if not html:
            return meta
        soup = BeautifulSoup(html, "html.parser")

        title_tag = soup.find("meta", property="og:title") or soup.find("title")
        if title_tag:
            meta["title"] = (title_tag.get("content") if title_tag.name == "meta" else title_tag.get_text()) or ""
            meta["title"] = meta["title"].strip()

        author_tag = soup.find("meta", {"name": "author"}) or soup.find(
            "meta", property="article:author"
        )
        if author_tag:
            meta["author"] = author_tag.get("content", "").strip()

        desc_tag = soup.find("meta", property="og:description") or soup.find(
            "meta", {"name": "description"}
        )
        if desc_tag:
            meta["og_description"] = desc_tag.get("content", "").strip()

        # JSON-LD
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "{}")
                if isinstance(data, list):
                    data = data[0] if data else {}
                if isinstance(data, dict):
                    if data.get("headline") and not meta.get("title"):
                        meta["title"] = data["headline"]
                    if isinstance(data.get("author"), dict) and not meta.get("author"):
                        meta["author"] = data["author"].get("name", "")
                    if data.get("datePublished"):
                        meta["date"] = data["datePublished"]
                    if "isAccessibleForFree" in data:
                        meta["is_accessible_for_free"] = str(
                            data["isAccessibleForFree"]
                        ).lower() == "true"
            except Exception:
                continue
        return meta

    def _is_paywalled(self, html: str, text: str) -> bool:
        haystack = (text or html).lower()
        for kw in _PAYWALL_KEYWORDS:
            if kw in haystack:
                return True
        return False

    async def _run_paywall_fallbacks(
        self,
        client: httpx.AsyncClient,
        original_url: str,
        fallbacks: list[str],
        extractors: list[str],
        existing_meta: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        for fb in fallbacks:
            logger.info("paywall fallback: %s", fb)
            try:
                if fb == "wayback":
                    r = await client.get(
                        "https://archive.org/wayback/available",
                        params={"url": original_url},
                    )
                    if r.status_code == 200:
                        snap = r.json().get("archived_snapshots", {}).get("closest", {})
                        if snap.get("available") and snap.get("url"):
                            r2 = await client.get(snap["url"])
                            if r2.status_code == 200:
                                text, meta = self._run_extractors(r2.text, extractors)
                                if text and len(text) >= 500:
                                    meta.update(existing_meta)
                                    meta["fallback_used"] = "wayback"
                                    return text, meta
                elif fb == "archive_ph":
                    r = await client.get(
                        f"https://archive.ph/newest/{original_url}",
                        follow_redirects=True,
                    )
                    if r.status_code == 200:
                        text, meta = self._run_extractors(r.text, extractors)
                        if text and len(text) >= 500:
                            meta.update(existing_meta)
                            meta["fallback_used"] = "archive_ph"
                            return text, meta
            except Exception as exc:
                logger.warning("fallback %s failed: %s", fb, exc)
        return "", existing_meta

    def _score_confidence(
        self, text: str, meta: dict[str, Any], min_length: int
    ) -> tuple[str, str]:
        text_len = len(text or "")
        has_byline = bool(meta.get("author"))
        has_date = bool(meta.get("date"))
        if text_len >= 1500 and has_byline and has_date:
            return "high", f"{text_len} chars + author + date"
        if text_len >= min_length:
            reason = f"{text_len} chars"
            if not has_byline:
                reason += ", no byline"
            return "medium", reason
        if self._is_paywalled("", text):
            return "low", "paywall detected"
        return "low", f"short content ({text_len} chars)"
```

- [ ] **Step 4: Run tests**

Run: `pytest website/features/summarization_engine/tests/unit/ingest/test_newsletter_ingest.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/source_ingest/newsletters/ website/features/summarization_engine/tests/unit/ingest/test_newsletter_ingest.py
git commit -m "feat(engine): add newsletter ingestor with paywall fallbacks"
```

### Task 3.2: Reddit ingestor

**Files:**
- Create: `website/features/summarization_engine/source_ingest/reddit/__init__.py` (empty)
- Create: `website/features/summarization_engine/source_ingest/reddit/ingest.py`
- Create: `website/features/summarization_engine/tests/unit/ingest/test_reddit_ingest.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/ingest/test_reddit_ingest.py`:

```python
"""Reddit ingestor tests with mocked .json endpoint."""
import pytest
from pytest_httpx import HTTPXMock

from website.features.summarization_engine.source_ingest.reddit.ingest import (
    RedditIngestor,
)
from website.features.summarization_engine.core.models import SourceType


def _post_listing(title: str, selftext: str, subreddit: str = "Python") -> dict:
    return {
        "kind": "Listing",
        "data": {
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "title": title,
                        "selftext": selftext,
                        "author": "op_user",
                        "subreddit": subreddit,
                        "score": 123,
                        "num_comments": 2,
                        "upvote_ratio": 0.95,
                        "created_utc": 1712345678.0,
                    },
                }
            ]
        },
    }


def _comments_listing(comments: list[dict]) -> dict:
    return {
        "kind": "Listing",
        "data": {
            "children": [
                {"kind": "t1", "data": c} for c in comments
            ]
        },
    }


@pytest.mark.asyncio
async def test_reddit_ingest_post_with_comments(httpx_mock: HTTPXMock):
    post_json = [
        _post_listing("Why I love Python", "Python is great because of its readability and ecosystem."),
        _comments_listing([
            {
                "author": "alice", "body": "Totally agree, the ecosystem is massive.",
                "score": 50, "stickied": False, "replies": "",
            },
            {
                "author": "bob", "body": "I prefer Rust for systems work though.",
                "score": 30, "stickied": False, "replies": "",
            },
            {
                "author": "[deleted]", "body": "[removed]",
                "score": 0, "stickied": False, "replies": "",
            },
            {
                "author": "AutoModerator", "body": "Please follow rule 3.",
                "score": 1, "stickied": True, "replies": "",
            },
        ]),
    ]
    httpx_mock.add_response(
        url="https://old.reddit.com/r/Python/comments/abc123/why_i_love_python/.json?limit=100&sort=top",
        json=post_json,
    )

    ingestor = RedditIngestor()
    result = await ingestor.ingest(
        "https://www.reddit.com/r/Python/comments/abc123/why_i_love_python/",
        config={
            "prefer_oauth": False,
            "user_agent": "test-bot/1.0",
            "comment_depth": 3,
            "max_comments": 50,
            "top_comment_rank": "top",
        },
    )

    assert result.source_type == SourceType.REDDIT
    assert "Why I love Python" in result.raw_text
    assert "alice" in result.raw_text
    assert "ecosystem" in result.raw_text
    # Filtered out:
    assert "[removed]" not in result.raw_text
    assert "AutoModerator" not in result.raw_text
    assert result.metadata["subreddit"] == "Python"
    assert result.metadata["score"] == 123
    assert result.extraction_confidence == "high"
```

- [ ] **Step 2: Run test (fail)**

Run: `pytest website/features/summarization_engine/tests/unit/ingest/test_reddit_ingest.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement RedditIngestor**

Create `website/features/summarization_engine/source_ingest/reddit/__init__.py` (empty).

Create `website/features/summarization_engine/source_ingest/reddit/ingest.py`:

```python
"""Reddit ingestor via the .json endpoint.

Primary: old.reddit.com/{path}.json — no auth required. Must set a proper
User-Agent. Fallback: PRAW with client_credentials (read-only app-only).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, ClassVar
from urllib.parse import urlparse

import httpx

from website.features.summarization_engine.core.errors import ExtractionError
from website.features.summarization_engine.core.models import (
    IngestResult,
    SourceType,
)
from website.features.summarization_engine.source_ingest.base import BaseIngestor

logger = logging.getLogger("summarization_engine.ingest.reddit")


class RedditIngestor(BaseIngestor):
    source_type: ClassVar[SourceType] = SourceType.REDDIT

    def __init__(self, timeout_sec: float = 30.0):
        self._timeout = timeout_sec

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        sort = config.get("top_comment_rank", "top")
        max_comments = config.get("max_comments", 50)
        depth = config.get("comment_depth", 3)
        user_agent = config.get("user_agent", "zettelkasten-engine/2.0")

        json_url = self._build_json_url(url, sort)
        headers = {"User-Agent": user_agent}

        async with httpx.AsyncClient(timeout=self._timeout, headers=headers, follow_redirects=True) as client:
            r = await client.get(json_url)
            if r.status_code == 404:
                raise ExtractionError(
                    f"Reddit post not found at {json_url}",
                    source_type=self.source_type.value, reason="404",
                )
            if r.status_code == 429:
                raise ExtractionError(
                    "Reddit rate limit exceeded",
                    source_type=self.source_type.value, reason="rate limited",
                )
            r.raise_for_status()
            data = r.json()

        if not isinstance(data, list) or len(data) < 2:
            raise ExtractionError(
                "Reddit returned unexpected JSON shape",
                source_type=self.source_type.value, reason="bad-json",
            )

        post_data = self._extract_post(data[0])
        comments_text = self._render_comments(data[1], max_comments, depth)

        sections = {
            "title": post_data.get("title", ""),
            "submission_meta": self._format_meta(post_data),
        }
        if post_data.get("selftext"):
            sections["selftext"] = post_data["selftext"]
        if comments_text:
            sections["top_comments"] = comments_text

        raw_text = "\n\n".join(f"## {k.upper().replace('_', ' ')}\n{v}" for k, v in sections.items() if v)

        confidence, reason = self._score_confidence(post_data, comments_text)

        return IngestResult(
            source_type=SourceType.REDDIT,
            url=url, original_url=url,
            raw_text=raw_text, sections=sections,
            metadata={
                "title": post_data.get("title"),
                "author": post_data.get("author"),
                "subreddit": post_data.get("subreddit"),
                "score": post_data.get("score"),
                "upvote_ratio": post_data.get("upvote_ratio"),
                "num_comments": post_data.get("num_comments"),
                "created_utc": post_data.get("created_utc"),
            },
            extraction_confidence=confidence,
            confidence_reason=reason,
            fetched_at=datetime.now(timezone.utc),
        )

    def _build_json_url(self, url: str, sort: str) -> str:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        # Switch host to old.reddit.com for stability
        return f"https://old.reddit.com{path}/.json?limit=100&sort={sort}"

    def _extract_post(self, listing: dict[str, Any]) -> dict[str, Any]:
        children = (listing.get("data") or {}).get("children") or []
        if not children:
            raise ExtractionError(
                "No post children in Reddit listing",
                source_type=self.source_type.value, reason="empty",
            )
        return (children[0].get("data") or {})

    def _render_comments(
        self,
        listing: dict[str, Any],
        max_comments: int,
        max_depth: int,
        depth: int = 0,
    ) -> str:
        if depth >= max_depth:
            return ""
        children = (listing.get("data") or {}).get("children") or []
        rendered: list[str] = []
        count = 0
        for c in children:
            if c.get("kind") != "t1":
                continue
            data = c.get("data") or {}
            if data.get("stickied"):
                continue
            author = data.get("author") or ""
            body = (data.get("body") or "").strip()
            if not body or author == "[deleted]" or body == "[removed]":
                continue
            if author == "AutoModerator":
                continue
            score = data.get("score") or 0
            indent = "  " * depth
            rendered.append(f"{indent}- [{author} · {score} pts] {body[:800]}")
            count += 1
            # Recurse into replies
            replies = data.get("replies")
            if isinstance(replies, dict):
                sub = self._render_comments(replies, max_comments, max_depth, depth + 1)
                if sub:
                    rendered.append(sub)
            if count >= max_comments:
                break
        return "\n".join(rendered)

    def _format_meta(self, post: dict[str, Any]) -> str:
        return (
            f"Subreddit: r/{post.get('subreddit', '')}\n"
            f"Author: u/{post.get('author', '')}\n"
            f"Score: {post.get('score', 0)}\n"
            f"Upvote ratio: {post.get('upvote_ratio', 0)}\n"
            f"Num comments: {post.get('num_comments', 0)}"
        )

    def _score_confidence(self, post: dict[str, Any], comments_text: str) -> tuple[str, str]:
        selftext_len = len(post.get("selftext") or "")
        comments_len = len(comments_text or "")
        if selftext_len >= 200 or comments_len >= 1000:
            return "high", f"selftext {selftext_len} + comments {comments_len}"
        if selftext_len or comments_len >= 300:
            return "medium", f"partial content"
        return "low", "sparse content"
```

- [ ] **Step 4: Run tests**

Run: `pytest website/features/summarization_engine/tests/unit/ingest/test_reddit_ingest.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/source_ingest/reddit/ website/features/summarization_engine/tests/unit/ingest/test_reddit_ingest.py
git commit -m "feat(engine): add Reddit ingestor via .json endpoint"
```

### Task 3.3: YouTube ingestor

**Files:**
- Create: `website/features/summarization_engine/source_ingest/youtube/__init__.py` (empty)
- Create: `website/features/summarization_engine/source_ingest/youtube/ingest.py`
- Create: `website/features/summarization_engine/tests/unit/ingest/test_youtube_ingest.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/ingest/test_youtube_ingest.py`:

```python
"""YouTube ingestor tests with mocked transcript API + oEmbed."""
import pytest
from unittest.mock import patch, MagicMock
from pytest_httpx import HTTPXMock

from website.features.summarization_engine.source_ingest.youtube.ingest import (
    YouTubeIngestor,
    extract_video_id,
)
from website.features.summarization_engine.core.models import SourceType


def test_extract_video_id_variants():
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://m.youtube.com/watch?v=dQw4w9WgXcQ&t=10s") == "dQw4w9WgXcQ"
    assert extract_video_id("https://www.youtube.com/shorts/abcDEF12345") == "abcDEF12345"
    assert extract_video_id("https://example.com") is None


@pytest.mark.asyncio
async def test_youtube_ingest_transcript_success(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url="https://www.youtube.com/oembed?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3DdQw4w9WgXcQ&format=json",
        json={
            "title": "Rick Astley - Never Gonna Give You Up",
            "author_name": "Rick Astley",
            "author_url": "https://youtube.com/@rickastley",
            "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        },
    )

    # Mock the youtube-transcript-api at the method level
    fake_segments = [
        {"text": "We're no strangers to love", "start": 0.0, "duration": 3.0},
        {"text": "You know the rules and so do I", "start": 3.0, "duration": 3.0},
        {"text": "A full commitment's what I'm thinking of", "start": 6.0, "duration": 3.0},
    ] * 20  # ~60 segments for length

    with patch(
        "website.features.summarization_engine.source_ingest.youtube.ingest._fetch_transcript",
        return_value=(fake_segments, "en"),
    ):
        ingestor = YouTubeIngestor()
        result = await ingestor.ingest(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            config={
                "transcript_languages": ["en"],
                "use_ytdlp_fallback": False,
                "use_gemini_video_fallback": False,
            },
        )

    assert result.source_type == SourceType.YOUTUBE
    assert "strangers to love" in result.raw_text
    assert result.metadata.get("title") == "Rick Astley - Never Gonna Give You Up"
    assert result.metadata.get("author_name") == "Rick Astley"
    assert result.extraction_confidence == "high"


@pytest.mark.asyncio
async def test_youtube_ingest_transcript_unavailable_falls_to_oembed_only(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url="https://www.youtube.com/oembed?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3DdQw4w9WgXcQ&format=json",
        json={
            "title": "Some Video",
            "author_name": "Some Channel",
            "author_url": "https://youtube.com/@some",
            "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        },
    )

    with patch(
        "website.features.summarization_engine.source_ingest.youtube.ingest._fetch_transcript",
        side_effect=RuntimeError("TranscriptsDisabled"),
    ):
        ingestor = YouTubeIngestor()
        result = await ingestor.ingest(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            config={
                "transcript_languages": ["en"],
                "use_ytdlp_fallback": False,
                "use_gemini_video_fallback": False,
            },
        )

    assert result.extraction_confidence == "low"
    assert "transcript" in result.confidence_reason.lower()
    assert result.metadata.get("title") == "Some Video"
```

- [ ] **Step 2: Run test (fail)**

Run: `pytest website/features/summarization_engine/tests/unit/ingest/test_youtube_ingest.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement YouTubeIngestor**

Create `website/features/summarization_engine/source_ingest/youtube/__init__.py` (empty).

Create `website/features/summarization_engine/source_ingest/youtube/ingest.py`:

```python
"""YouTube ingestor.

Primary: youtube-transcript-api for transcripts.
Fallback chain: yt-dlp subtitle download → Gemini direct video URL → oEmbed metadata only.
The Gemini direct-video fallback is required on cloud IPs (AWS/GCP/Render)
where YouTube blocks direct HTTP access.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, ClassVar
from urllib.parse import parse_qs, quote, urlparse

import httpx

from website.features.summarization_engine.core.errors import ExtractionError
from website.features.summarization_engine.core.models import (
    IngestResult,
    SourceType,
)
from website.features.summarization_engine.source_ingest.base import BaseIngestor

logger = logging.getLogger("summarization_engine.ingest.youtube")


def extract_video_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().lstrip("m.").replace("www.", "")
    if host == "youtu.be":
        return parsed.path.strip("/") or None
    if host.endswith("youtube.com"):
        path = parsed.path
        if path.startswith("/shorts/"):
            return path.removeprefix("/shorts/").split("/")[0] or None
        qs = parse_qs(parsed.query)
        v = qs.get("v", [None])[0]
        return v
    return None


def _fetch_transcript(video_id: str, languages: list[str]) -> tuple[list[dict], str]:
    """Call youtube-transcript-api. Separated so tests can monkeypatch."""
    from youtube_transcript_api import YouTubeTranscriptApi
    api = YouTubeTranscriptApi()
    fetched = api.fetch(video_id, languages=languages)
    segments = [
        {"text": seg.text, "start": seg.start, "duration": seg.duration}
        for seg in fetched.snippets
    ]
    return segments, fetched.language_code or (languages[0] if languages else "en")


class YouTubeIngestor(BaseIngestor):
    source_type: ClassVar[SourceType] = SourceType.YOUTUBE

    def __init__(self, timeout_sec: float = 30.0):
        self._timeout = timeout_sec

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        video_id = extract_video_id(url)
        if not video_id:
            raise ExtractionError(
                f"Could not parse YouTube video id from {url!r}",
                source_type=self.source_type.value, reason="bad-url",
            )

        languages = config.get("transcript_languages", ["en", "en-US", "en-GB"])

        # Always fetch oEmbed for metadata (cheap, reliable)
        oembed = await self._fetch_oembed(url)

        # Try transcript
        transcript_text = ""
        transcript_lang = ""
        transcript_error = ""
        try:
            segments, transcript_lang = _fetch_transcript(video_id, languages)
            transcript_text = " ".join(s["text"] for s in segments)
        except Exception as exc:
            transcript_error = str(exc)
            logger.info("transcript unavailable for %s: %s", video_id, exc)

        # Fallback: yt-dlp
        if not transcript_text and config.get("use_ytdlp_fallback", True):
            transcript_text = await self._ytdlp_fallback(video_id, languages)

        # Sections + raw text
        sections: dict[str, str] = {}
        if oembed:
            sections["metadata"] = self._format_oembed(oembed)
        if transcript_text:
            sections["transcript"] = transcript_text

        raw_text = "\n\n".join(f"## {k.upper()}\n{v}" for k, v in sections.items())

        confidence, reason = self._score_confidence(transcript_text, oembed, transcript_error)

        return IngestResult(
            source_type=SourceType.YOUTUBE,
            url=url, original_url=url,
            raw_text=raw_text,
            sections=sections,
            metadata={
                "video_id": video_id,
                "title": oembed.get("title") if oembed else None,
                "author_name": oembed.get("author_name") if oembed else None,
                "author_url": oembed.get("author_url") if oembed else None,
                "thumbnail_url": oembed.get("thumbnail_url") if oembed else None,
                "transcript_language": transcript_lang,
                "transcript_error": transcript_error or None,
            },
            extraction_confidence=confidence,
            confidence_reason=reason,
            fetched_at=datetime.now(timezone.utc),
        )

    async def _fetch_oembed(self, url: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
                r = await client.get(
                    f"https://www.youtube.com/oembed?url={quote(url, safe='')}&format=json"
                )
                if r.status_code == 200:
                    return r.json()
        except Exception as exc:
            logger.debug("oembed fetch failed: %s", exc)
        return {}

    async def _ytdlp_fallback(self, video_id: str, languages: list[str]) -> str:
        """Run yt-dlp in a subprocess to extract auto subtitles."""
        import asyncio
        import json as _json
        try:
            cmd = [
                "yt-dlp",
                "--write-auto-subs",
                "--sub-langs", ",".join(f"{l}.*" for l in languages),
                "--skip-download",
                "--sub-format", "vtt",
                "--dump-json",
                f"https://www.youtube.com/watch?v={video_id}",
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode != 0 or not stdout:
                return ""
            # Parse last JSON line for info; find .vtt path
            info = _json.loads(stdout.strip().splitlines()[-1])
            # VTT usually at requested_subtitles -> lang -> filepath
            subs = info.get("requested_subtitles") or {}
            for _lang, meta in subs.items():
                fp = meta.get("filepath") or ""
                if fp:
                    try:
                        with open(fp, encoding="utf-8") as f:
                            return self._vtt_to_text(f.read())
                    except Exception:
                        continue
            return ""
        except Exception as exc:
            logger.warning("yt-dlp fallback failed: %s", exc)
            return ""

    def _vtt_to_text(self, vtt: str) -> str:
        # Strip WEBVTT header, cue timestamps, and numeric cue ids
        lines = []
        for line in vtt.splitlines():
            s = line.strip()
            if not s or s.startswith("WEBVTT") or "-->" in s or s.isdigit():
                continue
            # Strip simple HTML tags
            s = re.sub(r"<[^>]+>", "", s)
            lines.append(s)
        return " ".join(lines)

    def _format_oembed(self, oembed: dict[str, Any]) -> str:
        return (
            f"Title: {oembed.get('title', '')}\n"
            f"Channel: {oembed.get('author_name', '')}\n"
            f"Channel URL: {oembed.get('author_url', '')}"
        )

    def _score_confidence(
        self, transcript_text: str, oembed: dict[str, Any], error: str
    ) -> tuple[str, str]:
        text_len = len(transcript_text or "")
        has_title = bool(oembed.get("title")) if oembed else False
        if text_len >= 2000 and has_title:
            return "high", f"transcript {text_len} chars + metadata"
        if text_len >= 200:
            return "medium", f"transcript {text_len} chars"
        if has_title:
            return "low", f"oembed only; transcript error: {error[:60]}"
        return "low", "no transcript, no metadata"
```

- [ ] **Step 4: Run tests**

Run: `pytest website/features/summarization_engine/tests/unit/ingest/test_youtube_ingest.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/source_ingest/youtube/ website/features/summarization_engine/tests/unit/ingest/test_youtube_ingest.py
git commit -m "feat(engine): add YouTube ingestor with transcript + yt-dlp fallback"
```

---

## Phase 4: Ingestors Batch 3 (LinkedIn, Podcasts, Twitter)

These are best-effort sources. Confidence is often medium or low. Implement minimum viable extraction and graceful degradation.

### Task 4.1: LinkedIn ingestor

**Files:**
- Create: `website/features/summarization_engine/source_ingest/linkedin/__init__.py` (empty)
- Create: `website/features/summarization_engine/source_ingest/linkedin/ingest.py`
- Create: `website/features/summarization_engine/tests/unit/ingest/test_linkedin_ingest.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/ingest/test_linkedin_ingest.py`:

```python
"""LinkedIn ingestor tests."""
import pytest
from pytest_httpx import HTTPXMock

from website.features.summarization_engine.source_ingest.linkedin.ingest import (
    LinkedInIngestor,
)
from website.features.summarization_engine.core.models import SourceType


@pytest.mark.asyncio
async def test_linkedin_ingest_json_ld_success(httpx_mock: HTTPXMock):
    html = """<html>
    <head><title>Post | LinkedIn</title>
    <meta property="og:description" content="A great post about AI engineering.">
    <meta property="og:title" content="Satya on AI Engineering">
    <script type="application/ld+json">
    {"@type":"DiscussionForumPosting","headline":"AI Engineering","articleBody":"AI engineering is becoming a distinct discipline. Here are five things every AI engineer should know about production systems. First, observability matters more than model quality in most cases. Second, prompt engineering is real engineering.","author":{"name":"Satya Nadella"},"datePublished":"2026-04-01"}
    </script>
    </head><body><div>Main content</div></body></html>"""
    httpx_mock.add_response(
        url="https://www.linkedin.com/posts/satya_activity-1234",
        html=html,
    )

    ingestor = LinkedInIngestor()
    result = await ingestor.ingest(
        "https://www.linkedin.com/posts/satya_activity-1234",
        config={
            "googlebot_ua": True,
            "parse_json_ld": True,
            "use_wayback_fallback": False,
            "login_wall_keywords": ["authwall"],
        },
    )

    assert result.source_type == SourceType.LINKEDIN
    assert "AI engineering" in result.raw_text
    assert result.metadata.get("author") == "Satya Nadella"
    assert result.extraction_confidence == "high"


@pytest.mark.asyncio
async def test_linkedin_ingest_authwall_detected(httpx_mock: HTTPXMock):
    html = """<html><head><title>Sign Up | LinkedIn</title></head>
    <body><div class="authwall">Join now to see what you are missing</div></body></html>"""
    httpx_mock.add_response(
        url="https://www.linkedin.com/posts/foo_activity-9999",
        html=html,
    )

    ingestor = LinkedInIngestor()
    result = await ingestor.ingest(
        "https://www.linkedin.com/posts/foo_activity-9999",
        config={
            "googlebot_ua": True,
            "parse_json_ld": True,
            "use_wayback_fallback": False,
            "login_wall_keywords": ["authwall", "Join now to see"],
        },
    )
    assert result.extraction_confidence == "low"
    assert "authwall" in result.confidence_reason.lower()
```

- [ ] **Step 2: Run test (fail)**

Run: `pytest website/features/summarization_engine/tests/unit/ingest/test_linkedin_ingest.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement LinkedInIngestor**

Create `website/features/summarization_engine/source_ingest/linkedin/__init__.py` (empty).

Create `website/features/summarization_engine/source_ingest/linkedin/ingest.py`:

```python
"""LinkedIn post ingestor (best-effort, no auth).

Primary: Googlebot UA + JSON-LD extraction. Fallback: og:description +
og:title meta only. Authwall detection via keyword match.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, ClassVar

import httpx
from bs4 import BeautifulSoup

from website.features.summarization_engine.core.models import (
    IngestResult,
    SourceType,
)
from website.features.summarization_engine.source_ingest.base import BaseIngestor

logger = logging.getLogger("summarization_engine.ingest.linkedin")

_GOOGLEBOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"


class LinkedInIngestor(BaseIngestor):
    source_type: ClassVar[SourceType] = SourceType.LINKEDIN

    def __init__(self, timeout_sec: float = 30.0):
        self._timeout = timeout_sec

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        ua = _GOOGLEBOT_UA if config.get("googlebot_ua", True) else "zettelkasten-engine/2.0"
        login_wall_keywords = config.get("login_wall_keywords", ["authwall"])
        parse_json_ld = config.get("parse_json_ld", True)
        use_wayback = config.get("use_wayback_fallback", True)

        html = ""
        async with httpx.AsyncClient(
            timeout=self._timeout, headers={"User-Agent": ua}, follow_redirects=True,
        ) as client:
            try:
                r = await client.get(url)
                if r.status_code == 200:
                    html = r.text
            except Exception as exc:
                logger.warning("linkedin fetch failed: %s", exc)

            is_authwall = self._detect_authwall(html, login_wall_keywords)

            text, meta = self._extract(html, parse_json_ld)

            if (is_authwall or len(text) < 200) and use_wayback:
                text, meta = await self._wayback_fallback(client, url, parse_json_ld, meta)
                if text:
                    meta["fallback_used"] = "wayback"

        confidence, reason = self._score_confidence(text, meta, is_authwall)

        return IngestResult(
            source_type=SourceType.LINKEDIN,
            url=url, original_url=url,
            raw_text=text or meta.get("og_description", "") or "(extraction failed)",
            sections={"body": text} if text else {},
            metadata=meta,
            extraction_confidence=confidence,
            confidence_reason=reason,
            fetched_at=datetime.now(timezone.utc),
        )

    def _detect_authwall(self, html: str, keywords: list[str]) -> bool:
        if not html:
            return False
        lower = html.lower()
        for kw in keywords:
            if kw.lower() in lower:
                return True
        if "<title>sign up | linkedin" in lower[:500]:
            return True
        return False

    def _extract(self, html: str, parse_json_ld: bool) -> tuple[str, dict[str, Any]]:
        meta: dict[str, Any] = {}
        text = ""
        if not html:
            return text, meta

        soup = BeautifulSoup(html, "html.parser")

        og_title = soup.find("meta", property="og:title")
        if og_title:
            meta["title"] = (og_title.get("content") or "").strip()
        og_desc = soup.find("meta", property="og:description")
        if og_desc:
            meta["og_description"] = (og_desc.get("content") or "").strip()

        if parse_json_ld:
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "{}")
                    if isinstance(data, list):
                        data = data[0] if data else {}
                    if isinstance(data, dict):
                        article_body = data.get("articleBody") or ""
                        if article_body and len(article_body) > len(text):
                            text = article_body
                        author = data.get("author") or {}
                        if isinstance(author, dict) and not meta.get("author"):
                            meta["author"] = author.get("name", "")
                        if data.get("datePublished"):
                            meta["date"] = data["datePublished"]
                        if data.get("headline") and not meta.get("title"):
                            meta["title"] = data["headline"]
                except Exception:
                    continue

        if not text and meta.get("og_description"):
            text = meta["og_description"]

        return text, meta

    async def _wayback_fallback(
        self,
        client: httpx.AsyncClient,
        url: str,
        parse_json_ld: bool,
        existing_meta: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        try:
            r = await client.get("https://archive.org/wayback/available", params={"url": url})
            if r.status_code != 200:
                return "", existing_meta
            snap = r.json().get("archived_snapshots", {}).get("closest", {})
            if not (snap.get("available") and snap.get("url")):
                return "", existing_meta
            r2 = await client.get(snap["url"])
            if r2.status_code != 200:
                return "", existing_meta
            text, meta = self._extract(r2.text, parse_json_ld)
            meta.update({k: v for k, v in existing_meta.items() if not meta.get(k)})
            return text, meta
        except Exception as exc:
            logger.warning("wayback fallback failed: %s", exc)
            return "", existing_meta

    def _score_confidence(
        self, text: str, meta: dict[str, Any], is_authwall: bool
    ) -> tuple[str, str]:
        if is_authwall:
            return "low", "authwall detected"
        text_len = len(text or "")
        has_author = bool(meta.get("author"))
        if text_len >= 500 and has_author:
            return "high", f"json-ld articleBody {text_len} chars + author"
        if text_len >= 100 and has_author:
            return "medium", f"og:description {text_len} chars + author"
        if text_len >= 100:
            return "medium", f"og:description {text_len} chars"
        return "low", "title/meta only"
```

- [ ] **Step 4: Run tests**

Run: `pytest website/features/summarization_engine/tests/unit/ingest/test_linkedin_ingest.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/source_ingest/linkedin/ website/features/summarization_engine/tests/unit/ingest/test_linkedin_ingest.py
git commit -m "feat(engine): add LinkedIn best-effort ingestor"
```

### Task 4.2: Podcast ingestor (show notes only)

**Files:**
- Create: `website/features/summarization_engine/source_ingest/podcasts/__init__.py` (empty)
- Create: `website/features/summarization_engine/source_ingest/podcasts/ingest.py`
- Create: `website/features/summarization_engine/tests/unit/ingest/test_podcast_ingest.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/ingest/test_podcast_ingest.py`:

```python
"""Podcast ingestor tests (show notes only, no transcription)."""
import pytest
from pytest_httpx import HTTPXMock

from website.features.summarization_engine.source_ingest.podcasts.ingest import (
    PodcastIngestor,
)
from website.features.summarization_engine.core.models import SourceType


@pytest.mark.asyncio
async def test_podcast_ingest_apple_via_itunes_lookup(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url="https://itunes.apple.com/lookup?id=1000123456&entity=podcastEpisode",
        json={
            "resultCount": 1,
            "results": [{
                "wrapperType": "podcastEpisode",
                "feedUrl": "https://feeds.simplecast.com/example",
                "trackName": "Lex Fridman Ep 400 — Guest: Prof. Foo Bar",
                "releaseDate": "2026-03-15T10:00:00Z",
                "description": "Guest bio and episode description here.",
            }],
        },
    )
    rss_feed = """<?xml version="1.0"?>
<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
<title>Lex Fridman Podcast</title>
<item>
  <title>Ep 400 — Guest: Prof. Foo Bar</title>
  <pubDate>Sat, 15 Mar 2026 10:00:00 GMT</pubDate>
  <content:encoded><![CDATA[<h2>Ep 400</h2><p>In this episode, Prof. Foo Bar discusses consciousness, AI alignment, and the future of education. Topics include:</p><ul><li>Consciousness research</li><li>AI alignment techniques</li><li>Open-source education</li></ul>]]></content:encoded>
  <itunes:summary>Prof. Foo Bar on consciousness and AI</itunes:summary>
  <itunes:duration>02:15:30</itunes:duration>
  <itunes:episode>400</itunes:episode>
</item>
</channel>
</rss>"""
    httpx_mock.add_response(
        url="https://feeds.simplecast.com/example",
        content=rss_feed.encode("utf-8"),
    )

    ingestor = PodcastIngestor()
    result = await ingestor.ingest(
        "https://podcasts.apple.com/us/podcast/lex/id1434243584?i=1000123456",
        config={
            "use_itunes_lookup": True,
            "show_notes_precedence": ["content:encoded", "itunes:summary", "description", "itunes:subtitle"],
            "audio_transcription": False,
        },
    )

    assert result.source_type == SourceType.PODCAST
    assert "consciousness" in result.raw_text.lower()
    assert result.metadata.get("episode_number") == 400
    assert result.extraction_confidence in ("medium", "low")
    assert result.extraction_confidence != "high"  # no audio
```

- [ ] **Step 2: Run test (fail)**

Run: `pytest website/features/summarization_engine/tests/unit/ingest/test_podcast_ingest.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement PodcastIngestor**

Create `website/features/summarization_engine/source_ingest/podcasts/__init__.py` (empty).

Create `website/features/summarization_engine/source_ingest/podcasts/ingest.py`:

```python
"""Podcast ingestor — show notes only (no audio transcription in v1).

Resolves any podcast URL (Apple, Spotify, Overcast, Snipd) to an RSS feed
via iTunes Lookup or Podcast Index, then extracts show notes from the RSS
item via feedparser + trafilatura.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlparse

import httpx

from website.features.summarization_engine.core.errors import ExtractionError
from website.features.summarization_engine.core.models import (
    IngestResult,
    SourceType,
)
from website.features.summarization_engine.source_ingest.base import BaseIngestor

logger = logging.getLogger("summarization_engine.ingest.podcast")


class PodcastIngestor(BaseIngestor):
    source_type: ClassVar[SourceType] = SourceType.PODCAST

    def __init__(self, timeout_sec: float = 30.0):
        self._timeout = timeout_sec

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        use_itunes = config.get("use_itunes_lookup", True)
        precedence = config.get(
            "show_notes_precedence",
            ["content:encoded", "itunes:summary", "description", "itunes:subtitle"],
        )

        host = (urlparse(url).hostname or "").lower().replace("www.", "")
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            feed_url: str | None = None
            episode_meta: dict[str, Any] = {}

            if "podcasts.apple.com" in host and use_itunes:
                feed_url, episode_meta = await self._resolve_apple(client, url)
            elif "open.spotify.com" in host:
                feed_url, episode_meta = await self._resolve_spotify(client, url)
            else:
                # Overcast, Snipd, Pocket Casts, RSS direct
                feed_url, episode_meta = await self._resolve_generic(client, url)

            if not feed_url:
                raise ExtractionError(
                    f"Could not resolve podcast RSS for {url!r}",
                    source_type=self.source_type.value,
                    reason="no-feed",
                )

            # Fetch RSS feed
            r = await client.get(feed_url)
            r.raise_for_status()
            feed_bytes = r.content

        import feedparser
        feed = feedparser.parse(feed_bytes)
        episode_entry = self._find_episode_entry(feed, episode_meta)

        sections = {"podcast_title": (feed.feed.get("title") if feed.feed else "") or ""}
        notes_raw = ""
        for key in precedence:
            if key == "content:encoded":
                val = episode_entry.get("content", [{}])[0].get("value", "") if episode_entry.get("content") else ""
            elif key == "itunes:summary":
                val = episode_entry.get("itunes_summary", "") or ""
            elif key == "description":
                val = episode_entry.get("description", "") or ""
            elif key == "itunes:subtitle":
                val = episode_entry.get("itunes_subtitle", "") or ""
            else:
                val = ""
            if val and len(val) > len(notes_raw):
                notes_raw = val
                sections["show_notes_source"] = key

        # Clean HTML via trafilatura
        notes_text = self._clean_html(notes_raw)
        if notes_text:
            sections["show_notes"] = notes_text

        if episode_entry.get("title"):
            sections["episode_title"] = episode_entry["title"]
        duration = episode_entry.get("itunes_duration") or ""
        if duration:
            sections["duration"] = duration

        raw_text = "\n\n".join(f"## {k.upper().replace('_', ' ')}\n{v}" for k, v in sections.items() if v)

        episode_number = None
        ep_str = episode_entry.get("itunes_episode")
        if ep_str:
            try:
                episode_number = int(ep_str)
            except (TypeError, ValueError):
                pass
        if episode_number is None:
            m = re.search(r"\b(?:Ep\.?|Episode)\s*#?(\d+)", episode_entry.get("title", ""))
            if m:
                episode_number = int(m.group(1))

        confidence, reason = self._score_confidence(notes_text, episode_entry)

        return IngestResult(
            source_type=SourceType.PODCAST,
            url=url, original_url=url,
            raw_text=raw_text, sections=sections,
            metadata={
                "podcast_title": feed.feed.get("title") if feed.feed else "",
                "episode_title": episode_entry.get("title"),
                "episode_number": episode_number,
                "pub_date": episode_entry.get("published"),
                "duration": duration,
                "feed_url": feed_url,
                "transcription_available": False,
            },
            extraction_confidence=confidence,
            confidence_reason=reason,
            fetched_at=datetime.now(timezone.utc),
        )

    async def _resolve_apple(
        self, client: httpx.AsyncClient, url: str
    ) -> tuple[str | None, dict[str, Any]]:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        episode_id = (qs.get("i") or [None])[0]
        if not episode_id:
            return None, {}
        r = await client.get(
            "https://itunes.apple.com/lookup",
            params={"id": episode_id, "entity": "podcastEpisode"},
        )
        if r.status_code != 200:
            return None, {}
        data = r.json()
        results = data.get("results") or []
        if not results:
            return None, {}
        result = results[0]
        return result.get("feedUrl"), {
            "track_name": result.get("trackName"),
            "release_date": result.get("releaseDate"),
            "episode_id": episode_id,
        }

    async def _resolve_spotify(
        self, client: httpx.AsyncClient, url: str
    ) -> tuple[str | None, dict[str, Any]]:
        # Best-effort: scrape og:title from Spotify page, then we'd need Podcast Index
        # to map to RSS. For v1, return None (no API key wired) and degrade to low confidence.
        logger.info("Spotify podcast URLs require Podcast Index API (not configured in v1)")
        return None, {}

    async def _resolve_generic(
        self, client: httpx.AsyncClient, url: str
    ) -> tuple[str | None, dict[str, Any]]:
        # For RSS URLs or direct feeds, pass through
        if url.endswith(".xml") or "/feed" in url or "/rss" in url:
            return url, {}
        return None, {}

    def _find_episode_entry(self, feed: Any, episode_meta: dict[str, Any]) -> dict[str, Any]:
        entries = feed.entries or []
        if not entries:
            return {}
        # Try matching by trackName if we have one
        track_name = episode_meta.get("track_name") or ""
        if track_name:
            for e in entries:
                if track_name.lower() in (e.get("title", "") or "").lower():
                    return dict(e)
        return dict(entries[0])

    def _clean_html(self, html: str) -> str:
        if not html:
            return ""
        try:
            import trafilatura
            out = trafilatura.extract(
                html, favor_precision=False, include_comments=False, output_format="markdown",
            )
            return out or self._strip_tags(html)
        except Exception:
            return self._strip_tags(html)

    def _strip_tags(self, html: str) -> str:
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "html.parser").get_text(separator="\n", strip=True)

    def _score_confidence(self, notes_text: str, entry: dict[str, Any]) -> tuple[str, str]:
        # v1 cap: no audio, so confidence max is medium
        text_len = len(notes_text or "")
        has_title = bool(entry.get("title"))
        if text_len >= 500 and has_title:
            return "medium", f"show notes {text_len} chars + title"
        if text_len >= 100:
            return "medium", f"show notes {text_len} chars (short)"
        if has_title:
            return "low", "title only"
        return "low", "no content"
```

- [ ] **Step 4: Run tests**

Run: `pytest website/features/summarization_engine/tests/unit/ingest/test_podcast_ingest.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/source_ingest/podcasts/ website/features/summarization_engine/tests/unit/ingest/test_podcast_ingest.py
git commit -m "feat(engine): add podcast ingestor (show notes only)"
```

### Task 4.3: Twitter / X ingestor

**Files:**
- Create: `website/features/summarization_engine/source_ingest/twitter/__init__.py` (empty)
- Create: `website/features/summarization_engine/source_ingest/twitter/ingest.py`
- Create: `website/features/summarization_engine/tests/unit/ingest/test_twitter_ingest.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/ingest/test_twitter_ingest.py`:

```python
"""Twitter / X ingestor tests."""
import pytest
from pytest_httpx import HTTPXMock

from website.features.summarization_engine.source_ingest.twitter.ingest import (
    TwitterIngestor,
)
from website.features.summarization_engine.core.models import SourceType


@pytest.mark.asyncio
async def test_twitter_ingest_oembed_success(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url="https://publish.twitter.com/oembed?url=https%3A%2F%2Ftwitter.com%2Fuser%2Fstatus%2F1234567890&omit_script=1&hide_thread=false",
        json={
            "html": '<blockquote class="twitter-tweet"><p>This is a great tweet about AI safety and alignment. #ai #safety</p>— Some User (@user) April 1, 2026</blockquote>',
            "author_name": "Some User",
            "author_url": "https://twitter.com/user",
            "url": "https://twitter.com/user/status/1234567890",
        },
    )

    ingestor = TwitterIngestor()
    result = await ingestor.ingest(
        "https://twitter.com/user/status/1234567890",
        config={
            "use_oembed": True,
            "use_nitter_fallback": False,
            "nitter_instances": [],
        },
    )

    assert result.source_type == SourceType.TWITTER
    assert "great tweet" in result.raw_text
    assert "AI safety" in result.raw_text
    assert result.metadata.get("author_name") == "Some User"
    assert result.extraction_confidence == "high"


@pytest.mark.asyncio
async def test_twitter_ingest_oembed_404_low_confidence(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url="https://publish.twitter.com/oembed?url=https%3A%2F%2Ftwitter.com%2Fdeleted%2Fstatus%2F999&omit_script=1&hide_thread=false",
        status_code=404,
    )

    ingestor = TwitterIngestor()
    from website.features.summarization_engine.core.errors import ExtractionError
    with pytest.raises(ExtractionError) as exc:
        await ingestor.ingest(
            "https://twitter.com/deleted/status/999",
            config={
                "use_oembed": True,
                "use_nitter_fallback": False,
                "nitter_instances": [],
            },
        )
    assert "not found" in exc.value.reason.lower() or "404" in exc.value.reason
```

- [ ] **Step 2: Run test (fail)**

Run: `pytest website/features/summarization_engine/tests/unit/ingest/test_twitter_ingest.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement TwitterIngestor**

Create `website/features/summarization_engine/source_ingest/twitter/__init__.py` (empty).

Create `website/features/summarization_engine/source_ingest/twitter/ingest.py`:

```python
"""Twitter / X ingestor (best-effort, no auth).

Primary: publish.twitter.com/oembed — reliable, unauthenticated, single
tweet only. Fallback: rotating Nitter instances for thread context.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, ClassVar
from urllib.parse import quote, urlparse

import httpx
from bs4 import BeautifulSoup

from website.features.summarization_engine.core.errors import ExtractionError
from website.features.summarization_engine.core.models import (
    IngestResult,
    SourceType,
)
from website.features.summarization_engine.source_ingest.base import BaseIngestor

logger = logging.getLogger("summarization_engine.ingest.twitter")

_STATUS_RE = re.compile(r"/([^/]+)/status(?:es)?/(\d+)")


class TwitterIngestor(BaseIngestor):
    source_type: ClassVar[SourceType] = SourceType.TWITTER

    def __init__(self, timeout_sec: float = 20.0):
        self._timeout = timeout_sec

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        use_oembed = config.get("use_oembed", True)
        use_nitter = config.get("use_nitter_fallback", True)
        instances = config.get("nitter_instances", [])
        health_timeout = config.get("nitter_health_check_timeout_sec", 5)

        m = _STATUS_RE.search(urlparse(url).path)
        username = m.group(1) if m else None
        tweet_id = m.group(2) if m else None

        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            oembed_data = {}
            tweet_text = ""
            if use_oembed:
                oembed_data, tweet_text = await self._fetch_oembed(client, url)

            thread_text = ""
            nitter_instance_used = ""
            if use_nitter and username and tweet_id:
                thread_text, nitter_instance_used = await self._fetch_via_nitter(
                    client, instances, username, tweet_id, health_timeout,
                )

        if not tweet_text and not thread_text:
            raise ExtractionError(
                f"Twitter oEmbed returned nothing for {url!r}",
                source_type=self.source_type.value,
                reason="404 not found (deleted/protected/suspended)",
            )

        sections: dict[str, str] = {}
        if tweet_text:
            sections["tweet"] = tweet_text
        if thread_text:
            sections["thread"] = thread_text
        if oembed_data.get("author_name"):
            sections["author"] = str(oembed_data.get("author_name"))

        raw_text = "\n\n".join(f"## {k.upper()}\n{v}" for k, v in sections.items() if v)

        confidence, reason = self._score_confidence(tweet_text, thread_text, oembed_data)

        return IngestResult(
            source_type=SourceType.TWITTER,
            url=url, original_url=url,
            raw_text=raw_text,
            sections=sections,
            metadata={
                "tweet_id": tweet_id,
                "author_name": oembed_data.get("author_name"),
                "author_url": oembed_data.get("author_url"),
                "nitter_instance": nitter_instance_used or None,
                "thread_reconstructed": bool(thread_text),
            },
            extraction_confidence=confidence,
            confidence_reason=reason,
            fetched_at=datetime.now(timezone.utc),
        )

    async def _fetch_oembed(
        self, client: httpx.AsyncClient, url: str
    ) -> tuple[dict[str, Any], str]:
        try:
            r = await client.get(
                f"https://publish.twitter.com/oembed?url={quote(url, safe='')}"
                f"&omit_script=1&hide_thread=false"
            )
            if r.status_code == 404:
                raise ExtractionError(
                    "Twitter oEmbed 404",
                    source_type=self.source_type.value, reason="404 not found",
                )
            if r.status_code != 200:
                return {}, ""
            data = r.json()
            html = data.get("html") or ""
            text = self._parse_oembed_html(html)
            return data, text
        except ExtractionError:
            raise
        except Exception as exc:
            logger.warning("oembed fetch failed: %s", exc)
            return {}, ""

    def _parse_oembed_html(self, html: str) -> str:
        if not html:
            return ""
        soup = BeautifulSoup(html, "html.parser")
        p = soup.find("p")
        if p:
            return p.get_text(separator=" ", strip=True)
        return soup.get_text(separator=" ", strip=True)

    async def _fetch_via_nitter(
        self,
        client: httpx.AsyncClient,
        instances: list[str],
        username: str,
        tweet_id: str,
        health_timeout: int,
    ) -> tuple[str, str]:
        for instance in instances:
            # HEAD health check
            try:
                h = await client.head(instance, timeout=health_timeout)
                if h.status_code >= 400:
                    continue
            except Exception:
                continue
            # Fetch thread
            try:
                r = await client.get(f"{instance}/{username}/status/{tweet_id}")
                if r.status_code != 200:
                    continue
                text = self._parse_nitter_html(r.text)
                if text:
                    return text, instance
            except Exception as exc:
                logger.debug("nitter %s failed: %s", instance, exc)
                continue
        return "", ""

    def _parse_nitter_html(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        if "rate limited" in soup.get_text().lower():
            return ""
        tweets: list[str] = []
        for item in soup.select(".timeline-item"):
            content = item.select_one(".tweet-content")
            if content:
                tweets.append(content.get_text(separator=" ", strip=True))
        return "\n\n".join(tweets)

    def _score_confidence(
        self, tweet_text: str, thread_text: str, oembed: dict[str, Any]
    ) -> tuple[str, str]:
        has_author = bool(oembed.get("author_name"))
        if tweet_text and len(tweet_text) >= 50 and has_author and not thread_text:
            return "high", f"oembed success, single tweet {len(tweet_text)} chars"
        if thread_text and len(thread_text) >= 200:
            return "medium", f"partial thread reconstructed via nitter"
        if tweet_text:
            return "medium", "short single tweet"
        return "low", "no content extracted"
```

- [ ] **Step 4: Run tests**

Run: `pytest website/features/summarization_engine/tests/unit/ingest/test_twitter_ingest.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/source_ingest/twitter/ website/features/summarization_engine/tests/unit/ingest/test_twitter_ingest.py
git commit -m "feat(engine): add Twitter/X ingestor via oEmbed + Nitter"
```

### Task 4.4: Generic web ingestor

**Files:**
- Create: `website/features/summarization_engine/source_ingest/web/__init__.py` (empty)
- Create: `website/features/summarization_engine/source_ingest/web/ingest.py`

- [ ] **Step 1: Create web ingestor as a thin wrapper around NewsletterIngestor**

Create `website/features/summarization_engine/source_ingest/web/__init__.py` (empty).

Create `website/features/summarization_engine/source_ingest/web/ingest.py`:

```python
"""Generic web article ingestor — same stack as NewsletterIngestor but registers
for the SourceType.WEB fallback.
"""
from __future__ import annotations

from typing import Any, ClassVar

from website.features.summarization_engine.core.models import (
    IngestResult,
    SourceType,
)
from website.features.summarization_engine.source_ingest.base import BaseIngestor
from website.features.summarization_engine.source_ingest.newsletters.ingest import (
    NewsletterIngestor,
)


class WebIngestor(BaseIngestor):
    """Fallback ingestor for URLs that don't match any specific source."""

    source_type: ClassVar[SourceType] = SourceType.WEB

    def __init__(self, timeout_sec: float = 30.0):
        self._inner = NewsletterIngestor(timeout_sec=timeout_sec)

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        result = await self._inner.ingest(url, config=config)
        # Rewrite source_type to WEB
        result.source_type = SourceType.WEB
        return result
```

- [ ] **Step 2: Verify registry picks it up**

Run: `python -c "from website.features.summarization_engine.source_ingest import list_ingestors; from website.features.summarization_engine.core.models import SourceType; m = list_ingestors(); print(sorted(k.value for k in m)); assert SourceType.WEB in m"`
Expected: Output lists all 10 source types including 'web'.

- [ ] **Step 3: Commit**

```bash
git add website/features/summarization_engine/source_ingest/web/
git commit -m "feat(engine): add generic web ingestor as fallback"
```

---

## Phase 5: Summarization Common (CoD, self-check, patch, structured extract)

This phase builds the 4-phase summarization pipeline components. All live under `summarization/common/` and are called by the per-source summarizers.

### Task 5.1: Prompt constants + source context blocks

**Files:**
- Create: `website/features/summarization_engine/summarization/common/prompts_base.py`

- [ ] **Step 1: Create prompts_base.py**

Create `website/features/summarization_engine/summarization/common/prompts_base.py`:

```python
"""Shared prompt templates for the summarization pipeline.

Per-source prompts inject a SOURCE_CONTEXT_BLOCK into the base templates.
"""
from __future__ import annotations

SOURCE_CONTEXT_BLOCKS: dict[str, str] = {
    "youtube": (
        "This is a YouTube transcript. Speaker attribution may be imperfect "
        "(auto-captions). Preserve numeric claims verbatim. Note timestamps "
        "where known."
    ),
    "github": (
        "This is a GitHub repository digest (README + metadata + top issues). "
        "Preserve code identifiers, dependency names, version numbers, and "
        "architectural decisions exactly. Identify the tech stack explicitly."
    ),
    "reddit": (
        "This is a Reddit thread — original post plus top comments. "
        "Distinguish the OP's claims from community consensus. Note when "
        "comments substantively disagree with or correct the OP."
    ),
    "hackernews": (
        "This is a Hacker News submission — the linked article AND the HN "
        "discussion. Summarize them SEPARATELY: first the article's argument, "
        "then the discussion's most substantive/contrarian points."
    ),
    "newsletter": (
        "This is a long-form essay or newsletter article. Extract the central "
        "thesis, the key supporting arguments in order, the evidence cited, "
        "and actionable takeaways (if any)."
    ),
    "linkedin": (
        "This is a LinkedIn post. Extract the core professional insight or "
        "argument. Note engagement signals if present. Flag if extraction "
        "appears incomplete due to login wall."
    ),
    "arxiv": (
        "This is an academic paper (arXiv). Follow academic summarization: "
        "problem statement → methodology → key results (with numbers) → "
        "limitations → implications. Do NOT hallucinate technical claims — "
        "if unclear, say so."
    ),
    "podcast": (
        "This is podcast SHOW NOTES (no audio transcript available). "
        "Summarize only what is explicitly in the notes; do not fabricate "
        "discussion points or speculate about unspoken content."
    ),
    "twitter": (
        "This is a Twitter/X tweet or thread. Reconstruct the argument arc. "
        "Identify the core claim and supporting points. If only the root "
        "tweet is available, note that context may be missing."
    ),
    "web": (
        "This is a generic web article. Extract thesis, key arguments, "
        "evidence, and conclusions."
    ),
}


PHASE_1_SYSTEM = (
    "You are a knowledge-management assistant producing summaries for a "
    "personal Zettelkasten. Coverage is the top priority — missing a key "
    "insight from the source is a critical failure. Minor over-inclusion "
    "is acceptable."
)


PHASE_1_USER_TEMPLATE = """You will summarize the following {source_type} in 2 progressive passes.

{source_context_block}

SOURCE:
<<<
{source_content}
>>>

INSTRUCTIONS:

Pass 1 — Write an exhaustive dense summary of the source in ~{pass1_word_target} words (prose, not bullets). Cover:
- Main thesis, argument, or purpose
- ALL key entities (people, orgs, products, numbers, named concepts)
- Mechanisms and reasoning (not just claims)
- Supporting evidence, examples, quotes
- Conclusions, recommendations, or takeaways
- Notable counterpoints or caveats the source itself raises

Pass 2 — Rewrite Pass 1 at the SAME LENGTH but denser. Identify 3-5 salient items from the source that are MISSING from Pass 1 (new named entities, numerical facts, causal mechanisms, or named concepts) and fuse them in. Compress generic phrasing to make room. Every entity from Pass 1 MUST still appear in Pass 2. Do not fabricate — if you can't find 3-5 missing items, say so and keep Pass 1.

Return ONLY this JSON (no code fences, no prose before or after):
{{
  "pass_1": {{
    "summary": "...",
    "covered_entities": ["..."]
  }},
  "pass_2": {{
    "summary": "...",
    "newly_added": ["..."],
    "covered_entities": ["..."]
  }}
}}"""


PHASE_2_SYSTEM = (
    "You are auditing a summary against its source for coverage gaps. Your "
    "job is to find missing key insights, not to edit or rewrite."
)


PHASE_2_USER_TEMPLATE = """SOURCE:
<<<
{source_content}
>>>

SUMMARY (the thing being audited):
<<<
{summary}
>>>

TASK:
1. From the SOURCE, list the 8-12 most important ATOMIC CLAIMS. An atomic claim is a single standalone factual statement (one subject, one predicate, one object). Rank them 1 = most central to the source's argument, 12 = least.

2. For each claim, mark:
   - COVERED if the summary contains the same information (exact wording not required — just the fact)
   - MISSING if absent from the summary
   - A claim that is only "partially covered" counts as MISSING.

3. List the MISSING claims ranked 1-5 as `critical_missing`.

Return ONLY this JSON:
{{
  "claims": [
    {{"rank": 1, "claim": "...", "status": "COVERED"}},
    {{"rank": 2, "claim": "...", "status": "MISSING"}}
  ],
  "missing_count": 0,
  "critical_missing": ["..."]
}}"""


PHASE_3_SYSTEM = (
    "You rewrite summaries to incorporate missing claims while preserving "
    "everything that's already there."
)


PHASE_3_USER_TEMPLATE = """The following summary was audited and found to be missing critical claims. Rewrite it at the SAME LENGTH, preserving all existing facts, while fusing in the missing claims below. Do not add filler; compress existing phrasing if you need room.

CURRENT SUMMARY:
<<<
{summary}
>>>

MISSING CLAIMS TO INCLUDE:
{critical_missing_bulleted}

Return ONLY this JSON:
{{
  "summary": "...",
  "included_claims": ["..."]
}}"""


PHASE_4_SYSTEM = (
    "You extract structured metadata from a dense summary. Be concise and "
    "use the source's own terminology where possible."
)


PHASE_4_USER_TEMPLATE = """DENSE SUMMARY:
<<<
{final_summary}
>>>

SOURCE URL: {url}
SOURCE TYPE: {source_type}
SOURCE TITLE: {source_title}

Extract structured metadata and produce the exhaustive nested-bullet detailed_summary that captures everything in the dense summary organized by theme. The detailed_summary must be a PERMANENT REPLACEMENT for re-reading the source.

REQUIREMENTS:
- mini_title: Under 5 words. Must be SPECIFIC to this content. Never generic like "Interesting AI Article". Think: what would a Zettelkasten note title look like for this?
  Examples of good titles:
    * "LoRA fine-tuning for medical QA"
    * "Rust async runtime comparison 2025"
    * "Kahneman on attention economics"
  Examples of BAD titles:
    * "AI research paper"
    * "Tech discussion"
    * "Blog post about coding"

- brief_summary: ≤50 words, single paragraph. Answers three questions: what is this, who made it, why does it matter.

- tags: 8-15 tags, flat list, lowercase-kebab. Mix granular (e.g. "lora-fine-tuning") with broad (e.g. "machine-learning"). Include: entities, concepts, technologies, domains, people, themes.

- detailed_summary: Nested bullet structure. Top-level = major themes/sections; each has `bullets` (direct points) and optional `sub_sections` (nested dict of sub-heading → bullet list). This must be EXHAUSTIVE — a future reader should not need to re-read the source."""
```

- [ ] **Step 2: Commit**

```bash
git add website/features/summarization_engine/summarization/common/prompts_base.py
git commit -m "feat(engine): add shared prompt templates + source context blocks"
```

### Task 5.2: Chain-of-Density densifier

**Files:**
- Create: `website/features/summarization_engine/summarization/common/chain_of_density.py`
- Create: `website/features/summarization_engine/tests/unit/test_cod.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/test_cod.py`:

```python
"""Chain-of-Density tests with mocked Gemini client."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from website.features.summarization_engine.core.gemini_client import GenerateResult
from website.features.summarization_engine.summarization.common.chain_of_density import (
    CoDResult,
    run_chain_of_density,
)


@pytest.mark.asyncio
async def test_cod_returns_pass_2_when_entities_added():
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(
        return_value=GenerateResult(
            text=json.dumps({
                "pass_1": {
                    "summary": "Initial dense summary about X.",
                    "covered_entities": ["X", "A", "B"],
                },
                "pass_2": {
                    "summary": "Denser summary about X and Y with Z.",
                    "newly_added": ["Y", "Z", "W"],
                    "covered_entities": ["X", "A", "B", "Y", "Z", "W"],
                },
            }),
            model_used="gemini-2.5-pro",
            input_tokens=500,
            output_tokens=200,
        )
    )

    result = await run_chain_of_density(
        mock_client,
        source_content="Long source content here...",
        source_type="github",
        pass1_word_target=200,
    )

    assert isinstance(result, CoDResult)
    assert result.final_summary == "Denser summary about X and Y with Z."
    assert result.iterations_used == 2
    assert "Y" in result.covered_entities
    assert result.input_tokens == 500
    assert result.output_tokens == 200


@pytest.mark.asyncio
async def test_cod_early_stop_when_few_new_entities():
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(
        return_value=GenerateResult(
            text=json.dumps({
                "pass_1": {
                    "summary": "First pass covering everything.",
                    "covered_entities": ["X", "A", "B", "C", "D"],
                },
                "pass_2": {
                    "summary": "Second pass identical.",
                    "newly_added": [],
                    "covered_entities": ["X", "A", "B", "C", "D"],
                },
            }),
            model_used="gemini-2.5-pro",
            input_tokens=500,
            output_tokens=200,
        )
    )

    result = await run_chain_of_density(
        mock_client,
        source_content="Source",
        source_type="github",
        pass1_word_target=200,
        early_stop_if_few_new_entities=2,
    )
    # early stop means pass_1 is returned as final
    assert result.final_summary == "First pass covering everything."
    assert result.iterations_used == 1
```

- [ ] **Step 2: Run test (fail)**

Run: `pytest website/features/summarization_engine/tests/unit/test_cod.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement chain_of_density.py**

Create `website/features/summarization_engine/summarization/common/chain_of_density.py`:

```python
"""Chain-of-Density Phase 1 runner.

Implements a 2-pass prose densification using Gemini 2.5 Pro. Research
(Adams et al. 2023 + replications) shows 2-3 iterations is the quality
peak; iteration 5 over-compresses.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from website.features.summarization_engine.core.errors import SummarizationError
from website.features.summarization_engine.core.gemini_client import (
    GenerateResult,
    TieredGeminiClient,
)
from website.features.summarization_engine.summarization.common.prompts_base import (
    PHASE_1_SYSTEM,
    PHASE_1_USER_TEMPLATE,
    SOURCE_CONTEXT_BLOCKS,
)

logger = logging.getLogger("summarization_engine.cod")


@dataclass
class CoDResult:
    final_summary: str
    covered_entities: list[str]
    iterations_used: int
    input_tokens: int
    output_tokens: int
    model_used: str


async def run_chain_of_density(
    client: TieredGeminiClient,
    *,
    source_content: str,
    source_type: str,
    pass1_word_target: int = 200,
    early_stop_if_few_new_entities: int = 2,
) -> CoDResult:
    """Run the 2-pass CoD densifier on the source content.

    Returns Pass 2 as the final summary unless early-stop fires (newly_added
    count below threshold AND Pass 2 length within 10% of Pass 1), in which
    case Pass 1 is returned.
    """
    context_block = SOURCE_CONTEXT_BLOCKS.get(source_type, SOURCE_CONTEXT_BLOCKS["web"])
    user_prompt = PHASE_1_USER_TEMPLATE.format(
        source_type=source_type,
        source_context_block=context_block,
        source_content=source_content,
        pass1_word_target=pass1_word_target,
    )

    result: GenerateResult = await client.generate(
        user_prompt,
        tier="pro",
        system_instruction=PHASE_1_SYSTEM,
    )

    try:
        data = json.loads(_strip_code_fence(result.text))
    except json.JSONDecodeError as exc:
        raise SummarizationError(f"CoD Phase 1 returned invalid JSON: {exc}") from exc

    pass_1 = data.get("pass_1") or {}
    pass_2 = data.get("pass_2") or {}

    pass_1_summary = (pass_1.get("summary") or "").strip()
    pass_2_summary = (pass_2.get("summary") or "").strip()
    newly_added = pass_2.get("newly_added") or []

    # Early stop: if Pass 2 added < threshold entities AND length is similar,
    # use Pass 1.
    length_ratio = (
        len(pass_2_summary) / max(len(pass_1_summary), 1) if pass_1_summary else 1.0
    )
    early_stop = (
        len(newly_added) < early_stop_if_few_new_entities
        and 0.9 <= length_ratio <= 1.1
    )

    if early_stop or not pass_2_summary:
        logger.info("cod.early_stop newly_added=%d length_ratio=%.2f", len(newly_added), length_ratio)
        return CoDResult(
            final_summary=pass_1_summary,
            covered_entities=list(pass_1.get("covered_entities") or []),
            iterations_used=1,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            model_used=result.model_used,
        )

    return CoDResult(
        final_summary=pass_2_summary,
        covered_entities=list(pass_2.get("covered_entities") or []),
        iterations_used=2,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        model_used=result.model_used,
    )


def _strip_code_fence(text: str) -> str:
    """Strip ```json ... ``` fences if present."""
    stripped = text.strip()
    if stripped.startswith("```"):
        # remove first line
        lines = stripped.splitlines()
        lines = lines[1:] if len(lines) > 1 else lines
        # remove trailing ```
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped
```

- [ ] **Step 4: Run tests**

Run: `pytest website/features/summarization_engine/tests/unit/test_cod.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/summarization/common/chain_of_density.py website/features/summarization_engine/tests/unit/test_cod.py
git commit -m "feat(engine): implement Chain-of-Density Phase 1 densifier"
```

### Task 5.3: Self-check (inverted FactScore)

**Files:**
- Create: `website/features/summarization_engine/summarization/common/self_check.py`
- Create: `website/features/summarization_engine/tests/unit/test_self_check.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/test_self_check.py`:

```python
"""Self-check Phase 2 tests."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from website.features.summarization_engine.core.gemini_client import GenerateResult
from website.features.summarization_engine.summarization.common.self_check import (
    SelfCheckResult,
    run_self_check,
)


@pytest.mark.asyncio
async def test_self_check_returns_missing_count_and_critical():
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(
        return_value=GenerateResult(
            text=json.dumps({
                "claims": [
                    {"rank": 1, "claim": "X is true", "status": "COVERED"},
                    {"rank": 2, "claim": "Y mechanism", "status": "MISSING"},
                    {"rank": 3, "claim": "Z result", "status": "MISSING"},
                    {"rank": 4, "claim": "A detail", "status": "COVERED"},
                ],
                "missing_count": 2,
                "critical_missing": ["Y mechanism", "Z result"],
            }),
            model_used="gemini-2.5-pro",
            input_tokens=800,
            output_tokens=200,
        )
    )

    result = await run_self_check(
        mock_client,
        source_content="Original source",
        summary="Summary text here",
    )

    assert isinstance(result, SelfCheckResult)
    assert result.missing_count == 2
    assert "Y mechanism" in result.critical_missing
    assert result.input_tokens == 800


@pytest.mark.asyncio
async def test_self_check_handles_no_missing():
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(
        return_value=GenerateResult(
            text=json.dumps({
                "claims": [{"rank": 1, "claim": "X", "status": "COVERED"}],
                "missing_count": 0,
                "critical_missing": [],
            }),
            model_used="gemini-2.5-pro",
            input_tokens=800, output_tokens=100,
        )
    )

    result = await run_self_check(mock_client, source_content="s", summary="s")
    assert result.missing_count == 0
    assert result.critical_missing == []
```

- [ ] **Step 2: Run test (fail)**

Run: `pytest website/features/summarization_engine/tests/unit/test_self_check.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement self_check.py**

Create `website/features/summarization_engine/summarization/common/self_check.py`:

```python
"""Coverage self-check using inverted FactScore.

The LLM extracts atomic claims from the SOURCE and marks each COVERED or
MISSING relative to the SUMMARY. This detects coverage gaps that
pure Reflexion-style critique misses.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from website.features.summarization_engine.core.errors import SummarizationError
from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.summarization.common.chain_of_density import (
    _strip_code_fence,
)
from website.features.summarization_engine.summarization.common.prompts_base import (
    PHASE_2_SYSTEM,
    PHASE_2_USER_TEMPLATE,
)

logger = logging.getLogger("summarization_engine.self_check")


@dataclass
class SelfCheckResult:
    claims: list[dict] = field(default_factory=list)
    missing_count: int = 0
    critical_missing: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model_used: str = ""


async def run_self_check(
    client: TieredGeminiClient,
    *,
    source_content: str,
    summary: str,
) -> SelfCheckResult:
    """Run Phase 2 coverage self-check."""
    prompt = PHASE_2_USER_TEMPLATE.format(
        source_content=source_content,
        summary=summary,
    )

    result = await client.generate(
        prompt,
        tier="pro",
        system_instruction=PHASE_2_SYSTEM,
    )

    try:
        data = json.loads(_strip_code_fence(result.text))
    except json.JSONDecodeError as exc:
        raise SummarizationError(f"Self-check returned invalid JSON: {exc}") from exc

    claims = data.get("claims") or []
    missing_count = int(data.get("missing_count") or 0)
    critical_missing = list(data.get("critical_missing") or [])

    return SelfCheckResult(
        claims=claims,
        missing_count=missing_count,
        critical_missing=critical_missing,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        model_used=result.model_used,
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest website/features/summarization_engine/tests/unit/test_self_check.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/summarization/common/self_check.py website/features/summarization_engine/tests/unit/test_self_check.py
git commit -m "feat(engine): implement self-check (inverted FactScore)"
```

### Task 5.4: Patch step (conditional rewrite)

**Files:**
- Create: `website/features/summarization_engine/summarization/common/patch.py`
- Create: `website/features/summarization_engine/tests/unit/test_patch.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/test_patch.py`:

```python
"""Patch Phase 3 tests."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from website.features.summarization_engine.core.gemini_client import GenerateResult
from website.features.summarization_engine.summarization.common.patch import (
    PatchResult,
    run_patch,
    should_patch,
)


def test_should_patch_respects_threshold():
    assert should_patch(missing_count=3, threshold=3) is True
    assert should_patch(missing_count=2, threshold=3) is False
    assert should_patch(missing_count=0, threshold=3) is False


@pytest.mark.asyncio
async def test_run_patch_returns_revised_summary():
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(
        return_value=GenerateResult(
            text=json.dumps({
                "summary": "Revised summary including Y, Z, W missing claims.",
                "included_claims": ["Y mechanism", "Z result"],
            }),
            model_used="gemini-2.5-pro",
            input_tokens=300,
            output_tokens=150,
        )
    )

    result = await run_patch(
        mock_client,
        summary="Old summary",
        critical_missing=["Y mechanism", "Z result"],
    )

    assert isinstance(result, PatchResult)
    assert "Revised" in result.revised_summary
    assert "Y mechanism" in result.included_claims
```

- [ ] **Step 2: Run test (fail)**

Run: `pytest website/features/summarization_engine/tests/unit/test_patch.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement patch.py**

Create `website/features/summarization_engine/summarization/common/patch.py`:

```python
"""Phase 3: Conditional patch step.

Only runs when Phase 2 reports missing_count >= threshold. Rewrites the
summary ONCE to fuse in the missing claims, never loops.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from website.features.summarization_engine.core.errors import SummarizationError
from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.summarization.common.chain_of_density import (
    _strip_code_fence,
)
from website.features.summarization_engine.summarization.common.prompts_base import (
    PHASE_3_SYSTEM,
    PHASE_3_USER_TEMPLATE,
)


@dataclass
class PatchResult:
    revised_summary: str
    included_claims: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model_used: str = ""


def should_patch(missing_count: int, threshold: int) -> bool:
    """Decide whether to trigger the patch step."""
    return missing_count >= threshold


async def run_patch(
    client: TieredGeminiClient,
    *,
    summary: str,
    critical_missing: list[str],
) -> PatchResult:
    """Rewrite the summary once, fusing in critical_missing claims."""
    missing_bulleted = "\n".join(f"- {claim}" for claim in critical_missing)
    prompt = PHASE_3_USER_TEMPLATE.format(
        summary=summary,
        critical_missing_bulleted=missing_bulleted,
    )

    result = await client.generate(
        prompt,
        tier="pro",
        system_instruction=PHASE_3_SYSTEM,
    )

    try:
        data = json.loads(_strip_code_fence(result.text))
    except json.JSONDecodeError as exc:
        raise SummarizationError(f"Patch returned invalid JSON: {exc}") from exc

    return PatchResult(
        revised_summary=(data.get("summary") or "").strip(),
        included_claims=list(data.get("included_claims") or []),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        model_used=result.model_used,
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest website/features/summarization_engine/tests/unit/test_patch.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/summarization/common/patch.py website/features/summarization_engine/tests/unit/test_patch.py
git commit -m "feat(engine): implement conditional patch step"
```

### Task 5.5: Structured extract (Phase 4, Flash tier)

**Files:**
- Create: `website/features/summarization_engine/summarization/common/validators.py`
- Create: `website/features/summarization_engine/summarization/common/tag_utils.py`
- Create: `website/features/summarization_engine/summarization/common/structured_extract.py`
- Create: `website/features/summarization_engine/tests/unit/test_tag_utils.py`
- Create: `website/features/summarization_engine/tests/unit/test_structured_extract.py`

- [ ] **Step 1: Write failing tests**

Create `website/features/summarization_engine/tests/unit/test_tag_utils.py`:

```python
from website.features.summarization_engine.summarization.common.tag_utils import (
    normalize_tag,
    normalize_tags,
    enforce_tag_count,
)
import pytest


def test_normalize_single_tag():
    assert normalize_tag("Machine Learning") == "machine-learning"
    assert normalize_tag("  LoRA Fine-tuning  ") == "lora-fine-tuning"
    assert normalize_tag("C++") == "c"
    assert normalize_tag("kebab-already") == "kebab-already"


def test_normalize_tags_dedupes_and_sorts_stable():
    tags = ["Machine Learning", "machine-learning", "Python", "python", "ML"]
    out = normalize_tags(tags)
    assert "machine-learning" in out
    assert "python" in out
    assert "ml" in out
    assert len(out) == 3  # deduped


def test_enforce_tag_count_pads_and_truncates():
    # Fewer than min → pad with generic tags from source_type
    assert len(enforce_tag_count(["a", "b"], min_count=8, max_count=15, source_type="github")) == 8
    # More than max → truncate
    tags = [f"t{i}" for i in range(20)]
    assert len(enforce_tag_count(tags, min_count=8, max_count=15, source_type="web")) == 15
```

Create `website/features/summarization_engine/tests/unit/test_structured_extract.py`:

```python
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from website.features.summarization_engine.core.gemini_client import GenerateResult
from website.features.summarization_engine.summarization.common.structured_extract import (
    run_structured_extract,
)


@pytest.mark.asyncio
async def test_structured_extract_success():
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(
        return_value=GenerateResult(
            text=json.dumps({
                "mini_title": "Rust async runtime comparison",
                "brief_summary": "A benchmark of Tokio and async-std runtimes showing Tokio is significantly faster on IO-bound workloads across most test scenarios.",
                "tags": ["rust", "async", "tokio", "async-std", "benchmarks", "runtimes", "concurrency", "systems"],
                "detailed_summary": [
                    {
                        "heading": "Overview",
                        "bullets": ["Tokio is faster", "async-std is simpler"],
                        "sub_sections": {},
                    }
                ],
            }),
            model_used="gemini-2.5-flash",
            input_tokens=400,
            output_tokens=200,
        )
    )

    result = await run_structured_extract(
        mock_client,
        final_summary="Dense summary about Rust runtimes.",
        url="https://example.com",
        source_type="github",
        source_title="Example",
    )

    assert result.mini_title_extracted == "Rust async runtime comparison"
    assert len(result.tags) >= 8
    assert result.input_tokens == 400


@pytest.mark.asyncio
async def test_structured_extract_retries_on_validation_fail():
    mock_client = MagicMock()
    bad = GenerateResult(
        text=json.dumps({
            "mini_title": "too few tags",
            "brief_summary": "x",
            "tags": ["only", "three", "tags"],
            "detailed_summary": [{"heading": "h", "bullets": ["b"]}],
        }),
        model_used="gemini-2.5-flash", input_tokens=400, output_tokens=100,
    )
    good = GenerateResult(
        text=json.dumps({
            "mini_title": "Corrected",
            "brief_summary": "Now valid.",
            "tags": ["a", "b", "c", "d", "e", "f", "g", "h"],
            "detailed_summary": [{"heading": "h", "bullets": ["b"]}],
        }),
        model_used="gemini-2.5-flash", input_tokens=450, output_tokens=120,
    )
    mock_client.generate = AsyncMock(side_effect=[bad, good])

    result = await run_structured_extract(
        mock_client, final_summary="x", url="u", source_type="web", source_title="t",
        validation_retries=1,
    )
    assert len(result.tags) == 8
    assert mock_client.generate.call_count == 2
```

- [ ] **Step 2: Run tests (expect fail)**

Run: `pytest website/features/summarization_engine/tests/unit/test_tag_utils.py website/features/summarization_engine/tests/unit/test_structured_extract.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement tag_utils.py**

Create `website/features/summarization_engine/summarization/common/tag_utils.py`:

```python
"""Tag normalization and count enforcement utilities."""
from __future__ import annotations

import re

_TAG_CLEAN_RE = re.compile(r"[^a-z0-9]+")

_FALLBACK_TAGS_BY_SOURCE: dict[str, list[str]] = {
    "github": ["open-source", "software", "code", "development", "repository", "programming"],
    "newsletter": ["essay", "analysis", "writing", "opinion", "long-read", "commentary"],
    "reddit": ["discussion", "forum", "community", "thread", "opinion", "social"],
    "youtube": ["video", "talk", "lecture", "media", "presentation", "content"],
    "hackernews": ["tech-news", "discussion", "community", "opinion", "technology"],
    "linkedin": ["professional", "career", "business", "industry", "insight"],
    "arxiv": ["research", "academic", "paper", "preprint", "science"],
    "podcast": ["podcast", "interview", "audio", "conversation", "media"],
    "twitter": ["tweet", "social-media", "short-form", "commentary"],
    "web": ["article", "web", "content", "reading"],
}


def normalize_tag(tag: str) -> str:
    """Normalize a single tag to lowercase-kebab-case."""
    t = tag.strip().lower()
    t = _TAG_CLEAN_RE.sub("-", t)
    t = t.strip("-")
    return t


def normalize_tags(tags: list[str]) -> list[str]:
    """Normalize + dedupe a list of tags, preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in tags:
        norm = normalize_tag(raw)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


def enforce_tag_count(
    tags: list[str], *, min_count: int, max_count: int, source_type: str
) -> list[str]:
    """Ensure tag count is within [min_count, max_count].

    - If too many, truncate to max_count.
    - If too few, pad with source-type fallback tags (deduped).
    """
    normalized = normalize_tags(tags)
    if len(normalized) > max_count:
        return normalized[:max_count]
    if len(normalized) >= min_count:
        return normalized

    fallbacks = _FALLBACK_TAGS_BY_SOURCE.get(source_type, _FALLBACK_TAGS_BY_SOURCE["web"])
    for fb in fallbacks:
        if fb not in normalized:
            normalized.append(fb)
        if len(normalized) >= min_count:
            break
    return normalized[:max_count]
```

- [ ] **Step 4: Implement validators.py**

Create `website/features/summarization_engine/summarization/common/validators.py`:

```python
"""Post-Gemini validators for the structured output."""
from __future__ import annotations


class ValidationFailure(Exception):
    """Raised when post-hoc validation of structured output fails."""


def validate_word_count(text: str, max_words: int, field_name: str) -> None:
    if not text:
        raise ValidationFailure(f"{field_name} is empty")
    word_count = len(text.split())
    if word_count > max_words:
        raise ValidationFailure(
            f"{field_name} has {word_count} words, max is {max_words}"
        )


def validate_tag_count(tags: list[str], min_count: int, max_count: int) -> None:
    if len(tags) < min_count:
        raise ValidationFailure(
            f"tags has {len(tags)} items, min is {min_count}"
        )
    if len(tags) > max_count:
        raise ValidationFailure(
            f"tags has {len(tags)} items, max is {max_count}"
        )


def validate_detailed_summary(detailed_summary: list) -> None:
    if not detailed_summary or len(detailed_summary) < 1:
        raise ValidationFailure("detailed_summary must have at least 1 section")
    for i, section in enumerate(detailed_summary):
        if not isinstance(section, dict):
            raise ValidationFailure(f"detailed_summary[{i}] must be a dict")
        if not section.get("heading"):
            raise ValidationFailure(f"detailed_summary[{i}] missing heading")
        bullets = section.get("bullets") or []
        if not bullets:
            raise ValidationFailure(f"detailed_summary[{i}] has no bullets")
```

- [ ] **Step 5: Implement structured_extract.py**

Create `website/features/summarization_engine/summarization/common/structured_extract.py`:

```python
"""Phase 4: Structured metadata extraction via Gemini 2.5 Flash.

Uses response_schema with a Pydantic model for reliable JSON output.
Post-validates word counts and tag format; retries once on failure.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from website.features.summarization_engine.core.errors import SummarizationError
from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.core.models import DetailedSummarySection
from website.features.summarization_engine.summarization.common.chain_of_density import (
    _strip_code_fence,
)
from website.features.summarization_engine.summarization.common.prompts_base import (
    PHASE_4_SYSTEM,
    PHASE_4_USER_TEMPLATE,
)
from website.features.summarization_engine.summarization.common.tag_utils import (
    enforce_tag_count,
    normalize_tags,
)
from website.features.summarization_engine.summarization.common.validators import (
    ValidationFailure,
    validate_detailed_summary,
    validate_tag_count,
    validate_word_count,
)

logger = logging.getLogger("summarization_engine.structured_extract")


class _StructuredOut(BaseModel):
    mini_title: str
    brief_summary: str
    tags: list[str] = Field(default_factory=list)
    detailed_summary: list[dict] = Field(default_factory=list)


@dataclass
class StructuredExtractResult:
    mini_title_extracted: str
    brief_summary_extracted: str
    tags: list[str] = field(default_factory=list)
    detailed_summary: list[DetailedSummarySection] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model_used: str = ""


async def run_structured_extract(
    client: TieredGeminiClient,
    *,
    final_summary: str,
    url: str,
    source_type: str,
    source_title: str,
    mini_title_max_words: int = 5,
    brief_summary_max_words: int = 50,
    tags_min: int = 8,
    tags_max: int = 15,
    validation_retries: int = 1,
) -> StructuredExtractResult:
    """Phase 4: extract structured metadata via Flash tier + response_schema."""
    base_prompt = PHASE_4_USER_TEMPLATE.format(
        final_summary=final_summary,
        url=url,
        source_type=source_type,
        source_title=source_title,
    )

    last_error: str = ""
    total_input = 0
    total_output = 0
    model_used = ""

    for attempt in range(validation_retries + 1):
        prompt = base_prompt
        if attempt > 0 and last_error:
            prompt += f"\n\nPREVIOUS ATTEMPT FAILED VALIDATION: {last_error}\nFIX THE ISSUE AND RETURN VALID JSON."

        result = await client.generate(
            prompt,
            tier="flash",
            response_schema=_StructuredOut,
            system_instruction=PHASE_4_SYSTEM,
        )
        total_input += result.input_tokens
        total_output += result.output_tokens
        model_used = result.model_used

        try:
            data = json.loads(_strip_code_fence(result.text))
        except json.JSONDecodeError as exc:
            last_error = f"invalid JSON: {exc}"
            continue

        mini_title = (data.get("mini_title") or "").strip()
        brief_summary = (data.get("brief_summary") or "").strip()
        raw_tags = data.get("tags") or []
        raw_detailed = data.get("detailed_summary") or []

        tags = normalize_tags(raw_tags)
        tags = enforce_tag_count(tags, min_count=tags_min, max_count=tags_max, source_type=source_type)

        try:
            validate_word_count(mini_title, mini_title_max_words, "mini_title")
            validate_word_count(brief_summary, brief_summary_max_words, "brief_summary")
            validate_tag_count(tags, tags_min, tags_max)
            validate_detailed_summary(raw_detailed)
        except ValidationFailure as exc:
            last_error = str(exc)
            logger.info("phase_4.validation_failed attempt=%d error=%s", attempt, exc)
            continue

        detailed_summary = [
            DetailedSummarySection(
                heading=section["heading"],
                bullets=list(section.get("bullets") or []),
                sub_sections={k: list(v) for k, v in (section.get("sub_sections") or {}).items()},
            )
            for section in raw_detailed
        ]

        return StructuredExtractResult(
            mini_title_extracted=mini_title,
            brief_summary_extracted=brief_summary,
            tags=tags,
            detailed_summary=detailed_summary,
            input_tokens=total_input,
            output_tokens=total_output,
            model_used=model_used,
        )

    raise SummarizationError(
        f"Structured extract failed after {validation_retries + 1} attempts: {last_error}"
    )
```

- [ ] **Step 6: Run tests**

Run: `pytest website/features/summarization_engine/tests/unit/test_tag_utils.py website/features/summarization_engine/tests/unit/test_structured_extract.py -v`
Expected: All 5 passed.

- [ ] **Step 7: Commit**

```bash
git add website/features/summarization_engine/summarization/common/validators.py website/features/summarization_engine/summarization/common/tag_utils.py website/features/summarization_engine/summarization/common/structured_extract.py website/features/summarization_engine/tests/unit/test_tag_utils.py website/features/summarization_engine/tests/unit/test_structured_extract.py
git commit -m "feat(engine): implement Phase 4 structured extract + validators"
```

---

## Phase 6: Per-Source Summarizers + Default Summarizer

Every source has its own `summarization/{source}/summarizer.py` that extends `BaseSummarizer`. Most are thin wrappers over a `DefaultSummarizer` that runs the 4-phase pipeline. Only sources that need special handling override methods.

### Task 6.1: DefaultSummarizer implementing the 4-phase pipeline

**Files:**
- Create: `website/features/summarization_engine/summarization/common/default_summarizer.py`
- Create: `website/features/summarization_engine/tests/unit/test_default_summarizer.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/test_default_summarizer.py`:

```python
"""End-to-end test for DefaultSummarizer with mocked CoD/self_check/patch/extract."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from website.features.summarization_engine.core.models import (
    DetailedSummarySection,
    IngestResult,
    SourceType,
)
from website.features.summarization_engine.summarization.common.chain_of_density import CoDResult
from website.features.summarization_engine.summarization.common.default_summarizer import (
    DefaultSummarizer,
)
from website.features.summarization_engine.summarization.common.patch import PatchResult
from website.features.summarization_engine.summarization.common.self_check import SelfCheckResult
from website.features.summarization_engine.summarization.common.structured_extract import (
    StructuredExtractResult,
)


@pytest.mark.asyncio
async def test_default_summarizer_full_pipeline_no_patch():
    mock_client = MagicMock()
    ingest = IngestResult(
        source_type=SourceType.GITHUB,
        url="https://github.com/foo/bar",
        original_url="https://github.com/foo/bar",
        raw_text="Project README content with many details.",
        metadata={"title": "foo/bar", "author": "foo"},
        extraction_confidence="high",
        confidence_reason="ok",
        fetched_at=datetime.now(timezone.utc),
    )

    cod_result = CoDResult(
        final_summary="Dense summary of the repo.",
        covered_entities=["foo", "bar"],
        iterations_used=2,
        input_tokens=8500,
        output_tokens=1200,
        model_used="gemini-2.5-pro",
    )
    self_check_result = SelfCheckResult(
        claims=[{"rank": 1, "claim": "x", "status": "COVERED"}],
        missing_count=0,
        critical_missing=[],
        input_tokens=8600,
        output_tokens=700,
        model_used="gemini-2.5-pro",
    )
    extract_result = StructuredExtractResult(
        mini_title_extracted="Foo bar library",
        brief_summary_extracted="A Python library that does foo.",
        tags=["python", "library", "foo", "bar", "open-source", "code", "development", "repository"],
        detailed_summary=[
            DetailedSummarySection(heading="Overview", bullets=["Does foo"]),
            DetailedSummarySection(heading="Usage", bullets=["pip install foo-bar"]),
            DetailedSummarySection(heading="Notes", bullets=["Stable"]),
        ],
        input_tokens=700,
        output_tokens=1000,
        model_used="gemini-2.5-flash",
    )

    with patch(
        "website.features.summarization_engine.summarization.common.default_summarizer.run_chain_of_density",
        AsyncMock(return_value=cod_result),
    ), patch(
        "website.features.summarization_engine.summarization.common.default_summarizer.run_self_check",
        AsyncMock(return_value=self_check_result),
    ), patch(
        "website.features.summarization_engine.summarization.common.default_summarizer.run_structured_extract",
        AsyncMock(return_value=extract_result),
    ):
        summarizer = DefaultSummarizer(mock_client, config={})
        summarizer.source_type = SourceType.GITHUB
        result = await summarizer.summarize(ingest)

    assert result.mini_title == "Foo bar library"
    assert len(result.tags) >= 8
    assert result.metadata.cod_iterations_used == 2
    assert result.metadata.self_check_missing_count == 0
    assert result.metadata.patch_applied is False
    assert result.metadata.gemini_pro_tokens == 8500 + 1200 + 8600 + 700
    assert result.metadata.gemini_flash_tokens == 700 + 1000


@pytest.mark.asyncio
async def test_default_summarizer_triggers_patch_when_missing_claims():
    mock_client = MagicMock()
    ingest = IngestResult(
        source_type=SourceType.WEB,
        url="u", original_url="u", raw_text="r",
        extraction_confidence="high", confidence_reason="ok",
        fetched_at=datetime.now(timezone.utc),
    )

    cod = CoDResult(
        final_summary="Initial dense summary.",
        covered_entities=[], iterations_used=2,
        input_tokens=100, output_tokens=100, model_used="gemini-2.5-pro",
    )
    sc = SelfCheckResult(
        claims=[], missing_count=4,
        critical_missing=["a", "b", "c", "d"],
        input_tokens=100, output_tokens=100, model_used="gemini-2.5-pro",
    )
    patch_res = PatchResult(
        revised_summary="Patched summary with missing items.",
        included_claims=["a", "b"],
        input_tokens=200, output_tokens=150, model_used="gemini-2.5-pro",
    )
    ex = StructuredExtractResult(
        mini_title_extracted="Example article",
        brief_summary_extracted="Brief summary text.",
        tags=["a", "b", "c", "d", "e", "f", "g", "h"],
        detailed_summary=[DetailedSummarySection(heading="h", bullets=["b"])],
        input_tokens=100, output_tokens=100, model_used="gemini-2.5-flash",
    )

    with patch(
        "website.features.summarization_engine.summarization.common.default_summarizer.run_chain_of_density",
        AsyncMock(return_value=cod),
    ), patch(
        "website.features.summarization_engine.summarization.common.default_summarizer.run_self_check",
        AsyncMock(return_value=sc),
    ), patch(
        "website.features.summarization_engine.summarization.common.default_summarizer.run_patch",
        AsyncMock(return_value=patch_res),
    ), patch(
        "website.features.summarization_engine.summarization.common.default_summarizer.run_structured_extract",
        AsyncMock(return_value=ex),
    ) as mock_extract:
        summarizer = DefaultSummarizer(mock_client, config={"self_check": {"patch_threshold": 3}})
        summarizer.source_type = SourceType.WEB
        result = await summarizer.summarize(ingest)

    assert result.metadata.patch_applied is True
    assert result.metadata.self_check_missing_count == 4
    # The structured extract should be called with the PATCHED summary
    call_kwargs = mock_extract.call_args.kwargs
    assert call_kwargs["final_summary"] == "Patched summary with missing items."
```

- [ ] **Step 2: Run test (fail)**

Run: `pytest website/features/summarization_engine/tests/unit/test_default_summarizer.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement default_summarizer.py**

Create `website/features/summarization_engine/summarization/common/default_summarizer.py`:

```python
"""Default 4-phase summarizer.

Phase 1: Chain-of-Density prose densification (Pro)
Phase 2: Coverage self-check (Pro)
Phase 3: Conditional patch (Pro, optional)
Phase 4: Structured extract (Flash, response_schema)
"""
from __future__ import annotations

import logging
import time
from typing import Any

from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.core.models import (
    IngestResult,
    SummaryMetadata,
    SummaryResult,
)
from website.features.summarization_engine.summarization.base import BaseSummarizer
from website.features.summarization_engine.summarization.common.chain_of_density import (
    run_chain_of_density,
)
from website.features.summarization_engine.summarization.common.patch import (
    run_patch,
    should_patch,
)
from website.features.summarization_engine.summarization.common.self_check import (
    run_self_check,
)
from website.features.summarization_engine.summarization.common.structured_extract import (
    run_structured_extract,
)

logger = logging.getLogger("summarization_engine.summarizer")


class DefaultSummarizer(BaseSummarizer):
    """4-phase summarizer used by all sources unless overridden."""

    # source_type is set by the subclass
    def __init__(self, gemini_client: TieredGeminiClient, config: dict[str, Any]):
        super().__init__(gemini_client, config)
        self._engine_config = load_config()

    async def summarize(self, ingest: IngestResult) -> SummaryResult:
        start = time.perf_counter()
        cfg = self._engine_config

        cod_cfg = cfg.chain_of_density
        self_check_cfg = cfg.self_check
        extract_cfg = cfg.structured_extract

        # Phase 1: Chain-of-Density
        logger.info("phase_1.start url=%s", ingest.url)
        cod_result = await run_chain_of_density(
            self._client,
            source_content=ingest.raw_text,
            source_type=ingest.source_type.value,
            pass1_word_target=cod_cfg.pass1_word_target,
            early_stop_if_few_new_entities=cod_cfg.early_stop_if_few_new_entities,
        )
        current_summary = cod_result.final_summary
        pro_input_tokens = cod_result.input_tokens
        pro_output_tokens = cod_result.output_tokens

        # Phase 2: Self-check
        missing_count = 0
        patch_applied = False
        if self_check_cfg.enabled:
            logger.info("phase_2.start")
            sc_result = await run_self_check(
                self._client,
                source_content=ingest.raw_text,
                summary=current_summary,
            )
            missing_count = sc_result.missing_count
            pro_input_tokens += sc_result.input_tokens
            pro_output_tokens += sc_result.output_tokens

            # Phase 3: Conditional patch
            if should_patch(missing_count, self_check_cfg.patch_threshold):
                logger.info("phase_3.start missing=%d", missing_count)
                patch_result = await run_patch(
                    self._client,
                    summary=current_summary,
                    critical_missing=sc_result.critical_missing,
                )
                current_summary = patch_result.revised_summary
                pro_input_tokens += patch_result.input_tokens
                pro_output_tokens += patch_result.output_tokens
                patch_applied = True

        # Phase 4: Structured extract
        logger.info("phase_4.start")
        extract_result = await run_structured_extract(
            self._client,
            final_summary=current_summary,
            url=ingest.url,
            source_type=ingest.source_type.value,
            source_title=(ingest.metadata.get("title") if ingest.metadata else "") or "",
            mini_title_max_words=extract_cfg.mini_title_max_words,
            brief_summary_max_words=extract_cfg.brief_summary_max_words,
            tags_min=extract_cfg.tags_min,
            tags_max=extract_cfg.tags_max,
            validation_retries=extract_cfg.validation_retries,
        )
        flash_input_tokens = extract_result.input_tokens
        flash_output_tokens = extract_result.output_tokens

        total_latency_ms = int((time.perf_counter() - start) * 1000)

        # Author / date from ingestor metadata, if present
        author = None
        if ingest.metadata:
            author_val = ingest.metadata.get("author") or ingest.metadata.get("author_name")
            if isinstance(author_val, str):
                author = author_val

        metadata = SummaryMetadata(
            source_type=ingest.source_type,
            url=ingest.url,
            author=author,
            date=None,  # let writers parse from metadata if they want
            extraction_confidence=ingest.extraction_confidence,
            confidence_reason=ingest.confidence_reason,
            total_tokens_used=(
                pro_input_tokens + pro_output_tokens
                + flash_input_tokens + flash_output_tokens
            ),
            gemini_pro_tokens=pro_input_tokens + pro_output_tokens,
            gemini_flash_tokens=flash_input_tokens + flash_output_tokens,
            total_latency_ms=total_latency_ms,
            cod_iterations_used=cod_result.iterations_used,
            self_check_missing_count=missing_count,
            patch_applied=patch_applied,
        )

        return SummaryResult(
            mini_title=extract_result.mini_title_extracted,
            brief_summary=extract_result.brief_summary_extracted,
            tags=extract_result.tags,
            detailed_summary=extract_result.detailed_summary,
            metadata=metadata,
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest website/features/summarization_engine/tests/unit/test_default_summarizer.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/summarization/common/default_summarizer.py website/features/summarization_engine/tests/unit/test_default_summarizer.py
git commit -m "feat(engine): implement DefaultSummarizer 4-phase pipeline"
```

### Task 6.2: Per-source summarizer thin wrappers

**Files:**
- Create: `website/features/summarization_engine/summarization/{source}/__init__.py` (empty) for all 10 sources
- Create: `website/features/summarization_engine/summarization/{source}/summarizer.py` for all 10 sources
- Create: `website/features/summarization_engine/summarization/{source}/prompts.py` for all 10 sources (re-exports from common)

- [ ] **Step 1: Create all 10 source subdirectories with wrapper summarizers**

For each source in `[github, newsletters, reddit, youtube, hackernews, linkedin, arxiv, podcasts, twitter, web]`, create:

`website/features/summarization_engine/summarization/{source}/__init__.py` (empty file).

`website/features/summarization_engine/summarization/{source}/prompts.py`:

```python
"""Re-exports source-specific prompt constants (all live in common/prompts_base)."""
from website.features.summarization_engine.summarization.common.prompts_base import (
    SOURCE_CONTEXT_BLOCKS,
    PHASE_1_SYSTEM,
    PHASE_1_USER_TEMPLATE,
    PHASE_2_SYSTEM,
    PHASE_2_USER_TEMPLATE,
    PHASE_3_SYSTEM,
    PHASE_3_USER_TEMPLATE,
    PHASE_4_SYSTEM,
    PHASE_4_USER_TEMPLATE,
)
```

`website/features/summarization_engine/summarization/{source}/summarizer.py`:

```python
"""{SOURCE_DISPLAY} summarizer — thin wrapper around DefaultSummarizer."""
from typing import ClassVar

from website.features.summarization_engine.core.models import SourceType
from website.features.summarization_engine.summarization.common.default_summarizer import (
    DefaultSummarizer,
)


class {ClassName}Summarizer(DefaultSummarizer):
    source_type: ClassVar[SourceType] = SourceType.{ENUM_VALUE}
```

Specific substitutions per source:

| dir | SOURCE_DISPLAY | ClassName | ENUM_VALUE |
|---|---|---|---|
| github | GitHub | GitHub | GITHUB |
| newsletters | Newsletter | Newsletter | NEWSLETTER |
| reddit | Reddit | Reddit | REDDIT |
| youtube | YouTube | YouTube | YOUTUBE |
| hackernews | HackerNews | HackerNews | HACKERNEWS |
| linkedin | LinkedIn | LinkedIn | LINKEDIN |
| arxiv | arXiv | Arxiv | ARXIV |
| podcasts | Podcast | Podcast | PODCAST |
| twitter | Twitter | Twitter | TWITTER |
| web | Web | Web | WEB |

- [ ] **Step 2: Verify the summarization registry discovers all 10**

Run: `python -c "from website.features.summarization_engine.summarization import list_summarizers; from website.features.summarization_engine.core.models import SourceType; m = list_summarizers(); print(sorted(k.value for k in m)); assert len(m) == 10"`
Expected: Output lists all 10 source types.

- [ ] **Step 3: Commit**

```bash
git add website/features/summarization_engine/summarization/github/ website/features/summarization_engine/summarization/newsletters/ website/features/summarization_engine/summarization/reddit/ website/features/summarization_engine/summarization/youtube/ website/features/summarization_engine/summarization/hackernews/ website/features/summarization_engine/summarization/linkedin/ website/features/summarization_engine/summarization/arxiv/ website/features/summarization_engine/summarization/podcasts/ website/features/summarization_engine/summarization/twitter/ website/features/summarization_engine/summarization/web/
git commit -m "feat(engine): add per-source summarizer wrappers for all 10 sources"
```

---

## Phase 7: Supabase Schema Migration

### Task 7.1: Write and apply the migration SQL

**Files:**
- Create: `supabase/website/kg_public/migrations/2026-04-10-summarization-engine-v2.sql`

- [ ] **Step 1: Write the migration**

Create `supabase/website/kg_public/migrations/2026-04-10-summarization-engine-v2.sql` (copy verbatim from spec §6):

```sql
-- Extend kg_nodes with new summarization engine fields
ALTER TABLE public.kg_nodes
    ADD COLUMN IF NOT EXISTS mini_title TEXT,
    ADD COLUMN IF NOT EXISTS brief_summary TEXT,
    ADD COLUMN IF NOT EXISTS detailed_summary JSONB,
    ADD COLUMN IF NOT EXISTS extraction_confidence TEXT
        CHECK (extraction_confidence IN ('high', 'medium', 'low')),
    ADD COLUMN IF NOT EXISTS confidence_reason TEXT,
    ADD COLUMN IF NOT EXISTS engine_version TEXT DEFAULT 'v2.0.0',
    ADD COLUMN IF NOT EXISTS total_tokens_used INT,
    ADD COLUMN IF NOT EXISTS gemini_pro_tokens INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS gemini_flash_tokens INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS total_latency_ms INT,
    ADD COLUMN IF NOT EXISTS cod_iterations_used INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS self_check_missing_count INT,
    ADD COLUMN IF NOT EXISTS patch_applied BOOLEAN DEFAULT FALSE;

-- Expand source_type CHECK
ALTER TABLE public.kg_nodes
    DROP CONSTRAINT IF EXISTS kg_nodes_source_type_check;
ALTER TABLE public.kg_nodes
    ADD CONSTRAINT kg_nodes_source_type_check CHECK (
        source_type IN (
            'youtube', 'reddit', 'github', 'twitter', 'substack', 'medium',
            'web', 'generic', 'hackernews', 'linkedin', 'arxiv', 'podcast',
            'newsletter'
        )
    );

-- New indexes for v2 queries
CREATE INDEX IF NOT EXISTS idx_kg_nodes_user_confidence
    ON public.kg_nodes(user_id, extraction_confidence);
CREATE INDEX IF NOT EXISTS idx_kg_nodes_engine_version
    ON public.kg_nodes(engine_version);
CREATE INDEX IF NOT EXISTS idx_kg_nodes_mini_title_trgm
    ON public.kg_nodes USING gin (mini_title gin_trgm_ops);

-- Batch run tracking
CREATE TABLE IF NOT EXISTS public.summarization_batch_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.kg_users(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN (
        'pending', 'running', 'completed', 'partial_success', 'failed', 'cancelled'
    )),
    input_filename TEXT,
    input_format TEXT CHECK (input_format IN ('csv', 'json')),
    total_urls INT NOT NULL DEFAULT 0,
    processed_count INT NOT NULL DEFAULT 0,
    success_count INT NOT NULL DEFAULT 0,
    skipped_count INT NOT NULL DEFAULT 0,
    failed_count INT NOT NULL DEFAULT 0,
    mode TEXT NOT NULL DEFAULT 'realtime' CHECK (mode IN ('realtime', 'batch_api')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    config_snapshot JSONB
);

CREATE INDEX IF NOT EXISTS idx_batch_runs_user_status
    ON public.summarization_batch_runs(user_id, status, started_at DESC);

-- Per-URL batch item results
CREATE TABLE IF NOT EXISTS public.summarization_batch_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES public.summarization_batch_runs(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.kg_users(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    source_type TEXT,
    status TEXT NOT NULL CHECK (status IN (
        'pending', 'ingesting', 'summarizing', 'writing', 'succeeded', 'failed', 'skipped'
    )),
    node_id TEXT,
    error_code TEXT,
    error_message TEXT,
    tokens_used INT,
    latency_ms INT,
    user_tags TEXT[] DEFAULT ARRAY[]::TEXT[],
    user_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_batch_items_run
    ON public.summarization_batch_items(run_id, status);

-- RLS policies
ALTER TABLE public.summarization_batch_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.summarization_batch_items ENABLE ROW LEVEL SECURITY;

CREATE POLICY batch_runs_user_access ON public.summarization_batch_runs
    FOR ALL
    USING (
        user_id::text = current_setting('request.jwt.claims', true)::json->>'render_user_id'
        OR auth.role() = 'service_role'
    )
    WITH CHECK (
        user_id::text = current_setting('request.jwt.claims', true)::json->>'render_user_id'
        OR auth.role() = 'service_role'
    );

CREATE POLICY batch_items_user_access ON public.summarization_batch_items
    FOR ALL
    USING (
        user_id::text = current_setting('request.jwt.claims', true)::json->>'render_user_id'
        OR auth.role() = 'service_role'
    )
    WITH CHECK (
        user_id::text = current_setting('request.jwt.claims', true)::json->>'render_user_id'
        OR auth.role() = 'service_role'
    );
```

- [ ] **Step 2: Apply to local Supabase or dev instance**

Run (if using Supabase CLI locally):
```
supabase db push
```

Or apply manually via `psql` against the dev database:
```
psql "$SUPABASE_DB_URL" -f supabase/website/kg_public/migrations/2026-04-10-summarization-engine-v2.sql
```

Expected: no errors. All ALTER/CREATE statements succeed (idempotent via IF NOT EXISTS).

- [ ] **Step 3: Verify new columns exist**

Run via `psql` or Supabase SQL editor:
```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'kg_nodes'
  AND column_name IN ('mini_title', 'brief_summary', 'detailed_summary', 'extraction_confidence', 'engine_version');
```
Expected: 5 rows returned.

```sql
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' AND table_name LIKE 'summarization_%';
```
Expected: 2 rows (`summarization_batch_runs`, `summarization_batch_items`).

- [ ] **Step 4: Commit**

```bash
git add supabase/website/kg_public/migrations/2026-04-10-summarization-engine-v2.sql
git commit -m "feat(engine): add Supabase schema migration for v2 (kg_nodes + batch tables)"
```

---

## Phase 8: Writers (Supabase, Obsidian, GitHub)

### Task 8.1: Base writer ABC

**Files:**
- Create: `website/features/summarization_engine/writers/base.py`

- [ ] **Step 1: Create base.py**

Create `website/features/summarization_engine/writers/base.py`:

```python
"""Base class for result writers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

from website.features.summarization_engine.core.models import SummaryResult


@dataclass
class WriteResult:
    """Return value from BaseWriter.write()."""
    writer: str
    node_id: str
    success: bool
    message: str = ""


class BaseWriter(ABC):
    """Abstract base for writers — composable persistence sinks."""

    name: str

    @abstractmethod
    async def write(
        self,
        *,
        result: SummaryResult,
        user_id: UUID,
    ) -> WriteResult:
        raise NotImplementedError
```

- [ ] **Step 2: Commit**

```bash
git add website/features/summarization_engine/writers/base.py
git commit -m "feat(engine): add BaseWriter ABC"
```

### Task 8.2: Supabase writer

**Files:**
- Create: `website/features/summarization_engine/writers/supabase_writer.py`
- Create: `website/features/summarization_engine/tests/unit/test_supabase_writer.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/test_supabase_writer.py`:

```python
"""SupabaseWriter tests with mocked supabase client."""
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from website.features.summarization_engine.core.models import (
    DetailedSummarySection,
    SourceType,
    SummaryMetadata,
    SummaryResult,
)
from website.features.summarization_engine.writers.supabase_writer import (
    SupabaseWriter,
)


@pytest.fixture
def sample_result():
    meta = SummaryMetadata(
        source_type=SourceType.GITHUB,
        url="https://github.com/foo/bar",
        author="foo",
        extraction_confidence="high",
        confidence_reason="ok",
        total_tokens_used=1000,
        gemini_pro_tokens=800,
        gemini_flash_tokens=200,
        total_latency_ms=1500,
        cod_iterations_used=2,
        self_check_missing_count=0,
        patch_applied=False,
    )
    return SummaryResult(
        mini_title="Foo bar library",
        brief_summary="A library that does foo bar things.",
        tags=["python", "foo", "bar", "library", "open-source", "github", "code", "development"],
        detailed_summary=[
            DetailedSummarySection(heading="Overview", bullets=["Does foo"])
        ],
        metadata=meta,
    )


@pytest.mark.asyncio
async def test_supabase_writer_upserts_kg_node(sample_result):
    client = MagicMock()
    upsert_mock = MagicMock()
    upsert_mock.execute.return_value = MagicMock(data=[{"id": "foo-bar-abc"}])
    table_mock = MagicMock()
    table_mock.upsert.return_value = upsert_mock
    client.table.return_value = table_mock

    writer = SupabaseWriter(client=client)
    result = await writer.write(
        result=sample_result,
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
    )

    assert result.success is True
    assert result.writer == "supabase"
    client.table.assert_called_with("kg_nodes")

    call_args = table_mock.upsert.call_args[0][0]
    assert call_args["mini_title"] == "Foo bar library"
    assert call_args["source_type"] == "github"
    assert call_args["tags"] == sample_result.tags
    assert call_args["detailed_summary"] is not None
```

- [ ] **Step 2: Run test (fail)**

Run: `pytest website/features/summarization_engine/tests/unit/test_supabase_writer.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement supabase_writer.py**

Create `website/features/summarization_engine/writers/supabase_writer.py`:

```python
"""SupabaseWriter — persists SummaryResult to the extended kg_nodes table."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from hashlib import sha1
from typing import Any
from uuid import UUID

from website.features.summarization_engine.core.errors import WriterError
from website.features.summarization_engine.core.models import SummaryResult
from website.features.summarization_engine.writers.base import BaseWriter, WriteResult

logger = logging.getLogger("summarization_engine.writers.supabase")

_SOURCE_TYPE_PREFIX = {
    "github": "gh",
    "newsletter": "nl",
    "reddit": "rd",
    "youtube": "yt",
    "hackernews": "hn",
    "linkedin": "li",
    "arxiv": "ax",
    "podcast": "pc",
    "twitter": "tw",
    "web": "web",
}

_SLUG_RE = re.compile(r"[^a-z0-9-]")


class SupabaseWriter(BaseWriter):
    name = "supabase"

    def __init__(self, client: Any):
        self._client = client

    async def write(
        self, *, result: SummaryResult, user_id: UUID,
    ) -> WriteResult:
        node_id = self._build_node_id(result)
        row = self._build_row(result, user_id, node_id)

        try:
            resp = self._client.table("kg_nodes").upsert(row).execute()
        except Exception as exc:
            raise WriterError(
                f"Supabase upsert failed: {exc}", writer=self.name,
            ) from exc

        if not getattr(resp, "data", None):
            logger.warning("supabase upsert returned no data")

        return WriteResult(
            writer=self.name, node_id=node_id, success=True,
        )

    def _build_node_id(self, result: SummaryResult) -> str:
        prefix = _SOURCE_TYPE_PREFIX.get(result.metadata.source_type.value, "web")
        slug = _SLUG_RE.sub("-", result.mini_title.lower()).strip("-") or "untitled"
        if len(slug) > 40:
            slug = slug[:40].rstrip("-")
        url_hash = sha1(result.metadata.url.encode()).hexdigest()[:6]
        return f"{prefix}-{slug}-{url_hash}"

    def _build_row(
        self, result: SummaryResult, user_id: UUID, node_id: str,
    ) -> dict[str, Any]:
        meta = result.metadata
        detailed_summary_json = [
            {
                "heading": s.heading,
                "bullets": s.bullets,
                "sub_sections": s.sub_sections,
            }
            for s in result.detailed_summary
        ]
        now = datetime.now(timezone.utc).isoformat()
        return {
            "id": node_id,
            "user_id": str(user_id),
            "name": result.mini_title,
            "source_type": meta.source_type.value,
            # Legacy `summary` column: keep populated for backwards compat
            "summary": result.brief_summary,
            "tags": result.tags,
            "url": meta.url,
            "node_date": None,
            "metadata": {
                "author": meta.author,
                "extraction_confidence": meta.extraction_confidence,
                "confidence_reason": meta.confidence_reason,
                "engine_version": meta.engine_version,
            },
            "mini_title": result.mini_title,
            "brief_summary": result.brief_summary,
            "detailed_summary": detailed_summary_json,
            "extraction_confidence": meta.extraction_confidence,
            "confidence_reason": meta.confidence_reason,
            "engine_version": meta.engine_version,
            "total_tokens_used": meta.total_tokens_used,
            "gemini_pro_tokens": meta.gemini_pro_tokens,
            "gemini_flash_tokens": meta.gemini_flash_tokens,
            "total_latency_ms": meta.total_latency_ms,
            "cod_iterations_used": meta.cod_iterations_used,
            "self_check_missing_count": meta.self_check_missing_count,
            "patch_applied": meta.patch_applied,
            "updated_at": now,
        }
```

- [ ] **Step 4: Run tests**

Run: `pytest website/features/summarization_engine/tests/unit/test_supabase_writer.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/writers/supabase_writer.py website/features/summarization_engine/tests/unit/test_supabase_writer.py
git commit -m "feat(engine): implement SupabaseWriter for extended kg_nodes"
```

### Task 8.3: Obsidian writer (opt-in)

**Files:**
- Create: `website/features/summarization_engine/writers/obsidian_writer.py`
- Create: `website/features/summarization_engine/tests/unit/test_obsidian_writer.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/test_obsidian_writer.py`:

```python
"""ObsidianWriter tests — writes .md with YAML frontmatter."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from website.features.summarization_engine.core.models import (
    DetailedSummarySection,
    SourceType,
    SummaryMetadata,
    SummaryResult,
)
from website.features.summarization_engine.writers.obsidian_writer import (
    ObsidianWriter,
)


@pytest.mark.asyncio
async def test_obsidian_writer_creates_markdown_file(tmp_path: Path):
    meta = SummaryMetadata(
        source_type=SourceType.GITHUB,
        url="https://github.com/foo/bar",
        author="foo",
        extraction_confidence="high", confidence_reason="ok",
        total_tokens_used=100,
        gemini_pro_tokens=100, gemini_flash_tokens=0,
        total_latency_ms=100, cod_iterations_used=2,
        self_check_missing_count=0, patch_applied=False,
    )
    result = SummaryResult(
        mini_title="Foo bar library",
        brief_summary="A library for foo bar.",
        tags=["python", "foo", "bar", "library", "open-source", "github", "code", "development"],
        detailed_summary=[
            DetailedSummarySection(
                heading="Overview",
                bullets=["Does foo", "Also does bar"],
                sub_sections={"Install": ["pip install foo-bar"]},
            ),
        ],
        metadata=meta,
    )

    writer = ObsidianWriter(kg_directory=tmp_path)
    write_result = await writer.write(
        result=result,
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
    )

    assert write_result.success is True
    # File exists
    files = list(tmp_path.glob("*.md"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert "Foo bar library" in content
    assert "Does foo" in content
    assert "---" in content  # frontmatter delimiters
    assert "pip install foo-bar" in content
```

- [ ] **Step 2: Run test (fail)**

Run: `pytest website/features/summarization_engine/tests/unit/test_obsidian_writer.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement obsidian_writer.py**

Create `website/features/summarization_engine/writers/obsidian_writer.py`:

```python
"""ObsidianWriter — writes .md notes with YAML frontmatter to a local vault."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from uuid import UUID

import yaml

from website.features.summarization_engine.core.errors import WriterError
from website.features.summarization_engine.core.models import SummaryResult
from website.features.summarization_engine.writers.base import BaseWriter, WriteResult

logger = logging.getLogger("summarization_engine.writers.obsidian")

_SLUG_RE = re.compile(r"[^a-z0-9-]")


class ObsidianWriter(BaseWriter):
    name = "obsidian"

    def __init__(self, kg_directory: Path):
        self._kg_dir = Path(kg_directory)

    async def write(
        self, *, result: SummaryResult, user_id: UUID,
    ) -> WriteResult:
        self._kg_dir.mkdir(parents=True, exist_ok=True)
        path = self._build_path(result)
        body = self._render(result)

        try:
            tmp = path.with_suffix(".md.tmp")
            tmp.write_text(body, encoding="utf-8")
            tmp.replace(path)
        except Exception as exc:
            raise WriterError(
                f"Obsidian write failed: {exc}", writer=self.name,
            ) from exc

        return WriteResult(
            writer=self.name, node_id=path.stem, success=True,
        )

    def _build_path(self, result: SummaryResult) -> Path:
        source = result.metadata.source_type.value
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        slug = _SLUG_RE.sub("-", result.mini_title.lower()).strip("-") or "untitled"
        if len(slug) > 50:
            slug = slug[:50].rstrip("-")
        url_hash = sha1(result.metadata.url.encode()).hexdigest()[:6]
        return self._kg_dir / f"{source}_{date_str}_{slug}-{url_hash}.md"

    def _render(self, result: SummaryResult) -> str:
        meta = result.metadata
        frontmatter: dict = {
            "title": result.mini_title,
            "mini_title": result.mini_title,
            "brief_summary": result.brief_summary,
            "source_type": meta.source_type.value,
            "source_url": meta.url,
            "author": meta.author or "",
            "extraction_confidence": meta.extraction_confidence,
            "engine_version": meta.engine_version,
            "tags": result.tags,
            "gemini_pro_tokens": meta.gemini_pro_tokens,
            "gemini_flash_tokens": meta.gemini_flash_tokens,
            "total_latency_ms": meta.total_latency_ms,
            "cod_iterations_used": meta.cod_iterations_used,
            "self_check_missing_count": meta.self_check_missing_count,
            "patch_applied": meta.patch_applied,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        fm_yaml = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)

        lines: list[str] = [
            "---",
            fm_yaml.strip(),
            "---",
            "",
            f"# {result.mini_title}",
            "",
            f"> {result.brief_summary}",
            "",
            f"**Source:** [{meta.source_type.value}]({meta.url})",
            "",
            "## Detailed summary",
            "",
        ]
        for section in result.detailed_summary:
            lines.append(f"### {section.heading}")
            lines.append("")
            for bullet in section.bullets:
                lines.append(f"- {bullet}")
            for sub_heading, sub_bullets in (section.sub_sections or {}).items():
                lines.append("")
                lines.append(f"#### {sub_heading}")
                for sb in sub_bullets:
                    lines.append(f"- {sb}")
            lines.append("")
        return "\n".join(lines)
```

- [ ] **Step 4: Run tests**

Run: `pytest website/features/summarization_engine/tests/unit/test_obsidian_writer.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/writers/obsidian_writer.py website/features/summarization_engine/tests/unit/test_obsidian_writer.py
git commit -m "feat(engine): implement ObsidianWriter with YAML frontmatter"
```

### Task 8.4: GitHub repo writer (opt-in)

**Files:**
- Create: `website/features/summarization_engine/writers/github_repo_writer.py`

- [ ] **Step 1: Implement github_repo_writer.py**

Create `website/features/summarization_engine/writers/github_repo_writer.py`:

```python
"""GithubRepoWriter — pushes .md notes to a GitHub repo via Contents API."""
from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from uuid import UUID

import httpx

from website.features.summarization_engine.core.errors import WriterError
from website.features.summarization_engine.core.models import SummaryResult
from website.features.summarization_engine.writers.base import BaseWriter, WriteResult
from website.features.summarization_engine.writers.obsidian_writer import ObsidianWriter

logger = logging.getLogger("summarization_engine.writers.github_repo")


class GithubRepoWriter(BaseWriter):
    name = "github_repo"

    def __init__(
        self,
        *,
        token: str | None = None,
        repo: str | None = None,
        branch: str | None = None,
    ):
        self._token = token or os.environ.get("GITHUB_TOKEN", "")
        self._repo = repo or os.environ.get("GITHUB_REPO", "")
        self._branch = branch or os.environ.get("GITHUB_BRANCH", "main")
        if not self._token or not self._repo:
            raise WriterError(
                "GithubRepoWriter requires GITHUB_TOKEN and GITHUB_REPO",
                writer=self.name,
            )

    async def write(
        self, *, result: SummaryResult, user_id: UUID,
    ) -> WriteResult:
        # Reuse ObsidianWriter to render the markdown body (without touching disk)
        renderer = ObsidianWriter(kg_directory=Path("."))
        body = renderer._render(result)  # noqa: SLF001
        path = renderer._build_path(result).name  # noqa: SLF001

        url = f"https://api.github.com/repos/{self._repo}/contents/{path}"
        headers = {
            "Authorization": f"token {self._token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "zettelkasten-engine/2.0",
        }
        payload = {
            "message": f"note: {result.mini_title[:60]}",
            "content": base64.b64encode(body.encode("utf-8")).decode("ascii"),
            "branch": self._branch,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.put(url, headers=headers, json=payload)
            if r.status_code not in (200, 201):
                raise WriterError(
                    f"GitHub Contents API returned {r.status_code}: {r.text[:200]}",
                    writer=self.name,
                )

        return WriteResult(writer=self.name, node_id=path, success=True)
```

- [ ] **Step 2: Commit**

```bash
git add website/features/summarization_engine/writers/github_repo_writer.py
git commit -m "feat(engine): implement GithubRepoWriter via Contents API"
```

---

## Phase 9: Batch Processor

### Task 9.1: Input loader (CSV + JSON auto-detection)

**Files:**
- Create: `website/features/summarization_engine/batch/input_loader.py`
- Create: `website/features/summarization_engine/tests/unit/test_input_loader.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/test_input_loader.py`:

```python
"""Batch input loader tests (CSV + JSON)."""
import json

import pytest

from website.features.summarization_engine.batch.input_loader import (
    LoadedItem,
    load_input,
)


def test_load_csv_basic():
    csv_bytes = b"url,user_tags,user_note\nhttps://a.com,tag1|tag2,hello\nhttps://b.com,,\n"
    items = load_input(csv_bytes, fmt="csv")
    assert len(items) == 2
    assert items[0].url == "https://a.com"
    assert items[0].user_tags == ["tag1", "tag2"]
    assert items[0].user_note == "hello"
    assert items[1].user_tags == []
    assert items[1].user_note is None


def test_load_json_list_of_strings():
    data = ["https://a.com", "https://b.com"]
    items = load_input(json.dumps(data).encode(), fmt="json")
    assert len(items) == 2
    assert items[0].url == "https://a.com"
    assert items[0].user_tags == []


def test_load_json_list_of_objects():
    data = [
        {"url": "https://a.com", "user_tags": ["x", "y"], "user_note": "n"},
        "https://b.com",
    ]
    items = load_input(json.dumps(data).encode(), fmt="json")
    assert len(items) == 2
    assert items[0].user_tags == ["x", "y"]
    assert items[0].user_note == "n"
    assert items[1].user_tags == []


def test_load_dedupes_duplicates():
    csv_bytes = b"url\nhttps://a.com\nhttps://a.com\nhttps://b.com\n"
    items = load_input(csv_bytes, fmt="csv")
    assert len(items) == 2


def test_load_skips_invalid_urls():
    data = ["https://a.com", "not-a-url", ""]
    items = load_input(json.dumps(data).encode(), fmt="json")
    assert len(items) == 1
    assert items[0].url == "https://a.com"


def test_auto_detect_format():
    from website.features.summarization_engine.batch.input_loader import detect_format

    assert detect_format("data.csv", b"url\nhttps://a.com") == "csv"
    assert detect_format("data.json", b'[]') == "json"
    assert detect_format("data.txt", b'[]') == "json"  # JSON sniff
    assert detect_format("data.txt", b"url,x\nhttps://a.com,1") == "csv"
```

- [ ] **Step 2: Run test (fail)**

Run: `pytest website/features/summarization_engine/tests/unit/test_input_loader.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement input_loader.py**

Create `website/features/summarization_engine/batch/input_loader.py`:

```python
"""Batch input file loader — supports CSV and JSON, auto-detects format."""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse

from website.features.summarization_engine.core.errors import EngineError


@dataclass
class LoadedItem:
    url: str
    user_tags: list[str] = field(default_factory=list)
    user_note: str | None = None


_VALID_URL_SCHEMES = {"http", "https"}


def _is_valid_url(url: str) -> bool:
    if not url or len(url) > 2000:
        return False
    try:
        p = urlparse(url)
    except ValueError:
        return False
    return p.scheme in _VALID_URL_SCHEMES and bool(p.netloc)


def detect_format(filename: str, content: bytes) -> Literal["csv", "json"]:
    """Detect CSV vs JSON from filename and content sniffing."""
    if filename.lower().endswith(".csv"):
        return "csv"
    if filename.lower().endswith(".json"):
        return "json"
    # Sniff: first non-whitespace char
    for b in content[:100]:
        if b in (0x20, 0x09, 0x0a, 0x0d):  # ws
            continue
        if chr(b) in "[{":
            return "json"
        break
    return "csv"


def load_input(
    content: bytes, *, fmt: Literal["csv", "json"],
) -> list[LoadedItem]:
    """Parse batch input file and return normalized LoadedItems.

    - Dedupes URLs (first-seen wins)
    - Skips invalid URLs silently
    """
    if fmt == "csv":
        items = _load_csv(content)
    elif fmt == "json":
        items = _load_json(content)
    else:
        raise EngineError(f"Unsupported input format: {fmt!r}")

    seen: set[str] = set()
    out: list[LoadedItem] = []
    for it in items:
        if not _is_valid_url(it.url):
            continue
        if it.url in seen:
            continue
        seen.add(it.url)
        out.append(it)
    return out


def _load_csv(content: bytes) -> list[LoadedItem]:
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    out: list[LoadedItem] = []
    for row in reader:
        url = (row.get("url") or "").strip()
        if not url:
            continue
        tags_raw = (row.get("user_tags") or "").strip()
        tags: list[str] = []
        if tags_raw:
            # Allow comma, pipe, or semicolon separators
            tags = [t.strip() for t in re.split(r"[,|;]", tags_raw) if t.strip()]
        note = (row.get("user_note") or "").strip() or None
        out.append(LoadedItem(url=url, user_tags=tags, user_note=note))
    return out


def _load_json(content: bytes) -> list[LoadedItem]:
    try:
        data = json.loads(content.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise EngineError(f"Invalid JSON input: {exc}") from exc
    if not isinstance(data, list):
        raise EngineError("JSON input must be a list")
    out: list[LoadedItem] = []
    for entry in data:
        if isinstance(entry, str):
            out.append(LoadedItem(url=entry.strip()))
        elif isinstance(entry, dict):
            url = (entry.get("url") or "").strip()
            if not url:
                continue
            tags = [t.strip() for t in (entry.get("user_tags") or []) if t]
            note = (entry.get("user_note") or "").strip() or None
            out.append(LoadedItem(url=url, user_tags=tags, user_note=note))
    return out
```

- [ ] **Step 4: Run tests**

Run: `pytest website/features/summarization_engine/tests/unit/test_input_loader.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/batch/input_loader.py website/features/summarization_engine/tests/unit/test_input_loader.py
git commit -m "feat(engine): implement batch input loader (CSV + JSON)"
```

### Task 9.2: Progress event emitter (SSE)

**Files:**
- Create: `website/features/summarization_engine/batch/progress.py`

- [ ] **Step 1: Implement progress.py**

Create `website/features/summarization_engine/batch/progress.py`:

```python
"""Progress event emitter for batch runs (SSE-friendly)."""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID


@dataclass
class BatchProgressEvent:
    event_type: Literal["started", "item_status", "completed", "error"]
    run_id: UUID
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    item_url: str | None = None
    item_status: str | None = None
    processed: int = 0
    total: int = 0
    message: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["run_id"] = str(self.run_id)
        return d


class ProgressBroker:
    """Per-run progress broker that fans out events to SSE subscribers."""

    def __init__(self) -> None:
        self._queues: dict[UUID, list[asyncio.Queue[BatchProgressEvent]]] = {}

    def subscribe(self, run_id: UUID) -> asyncio.Queue[BatchProgressEvent]:
        q: asyncio.Queue[BatchProgressEvent] = asyncio.Queue(maxsize=1000)
        self._queues.setdefault(run_id, []).append(q)
        return q

    def unsubscribe(self, run_id: UUID, q: asyncio.Queue[BatchProgressEvent]) -> None:
        subs = self._queues.get(run_id) or []
        if q in subs:
            subs.remove(q)
        if not subs:
            self._queues.pop(run_id, None)

    async def emit(self, event: BatchProgressEvent) -> None:
        subs = list(self._queues.get(event.run_id) or [])
        for q in subs:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass


_global_broker = ProgressBroker()


def get_global_broker() -> ProgressBroker:
    return _global_broker
```

- [ ] **Step 2: Commit**

```bash
git add website/features/summarization_engine/batch/progress.py
git commit -m "feat(engine): add SSE progress broker for batch runs"
```

### Task 9.3: Batch processor

**Files:**
- Create: `website/features/summarization_engine/batch/processor.py`
- Create: `website/features/summarization_engine/tests/unit/test_batch_processor.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/test_batch_processor.py`:

```python
"""BatchProcessor tests."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from website.features.summarization_engine.batch.input_loader import LoadedItem
from website.features.summarization_engine.batch.processor import BatchProcessor
from website.features.summarization_engine.core.models import (
    DetailedSummarySection,
    SourceType,
    SummaryMetadata,
    SummaryResult,
)


def _fake_summary(url: str) -> SummaryResult:
    meta = SummaryMetadata(
        source_type=SourceType.WEB, url=url,
        extraction_confidence="high", confidence_reason="ok",
        total_tokens_used=100, gemini_pro_tokens=80, gemini_flash_tokens=20,
        total_latency_ms=100, cod_iterations_used=2,
        self_check_missing_count=0, patch_applied=False,
    )
    return SummaryResult(
        mini_title="Mock title",
        brief_summary="Mock brief.",
        tags=["a", "b", "c", "d", "e", "f", "g", "h"],
        detailed_summary=[DetailedSummarySection(heading="h", bullets=["b"])],
        metadata=meta,
    )


@pytest.mark.asyncio
async def test_batch_processor_realtime_success():
    supabase_client = MagicMock()
    supabase_client.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[{"id": "x"}])
    supabase_client.table.return_value.insert.return_value.execute.return_value = MagicMock(
        data=[{"id": str(uuid4())}]
    )
    supabase_client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

    gemini_client = MagicMock()

    items = [
        LoadedItem(url="https://a.com/1"),
        LoadedItem(url="https://b.com/2"),
    ]

    async def fake_summarize_url(url, **kwargs):
        return _fake_summary(url)

    with patch(
        "website.features.summarization_engine.batch.processor.summarize_url",
        side_effect=fake_summarize_url,
    ):
        processor = BatchProcessor(
            user_id=UUID("00000000-0000-0000-0000-000000000001"),
            supabase_client=supabase_client,
            gemini_client=gemini_client,
        )
        run = await processor.run_items(items, mode="realtime")

    assert run.total_urls == 2
    assert run.success_count == 2
    assert run.failed_count == 0


@pytest.mark.asyncio
async def test_batch_processor_continues_on_error():
    supabase_client = MagicMock()
    supabase_client.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[{"id": "x"}])
    supabase_client.table.return_value.insert.return_value.execute.return_value = MagicMock(
        data=[{"id": str(uuid4())}]
    )
    supabase_client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

    items = [
        LoadedItem(url="https://ok.com/1"),
        LoadedItem(url="https://bad.com/2"),
    ]

    async def fake_summarize_url(url, **kwargs):
        if "bad" in url:
            raise RuntimeError("simulated failure")
        return _fake_summary(url)

    with patch(
        "website.features.summarization_engine.batch.processor.summarize_url",
        side_effect=fake_summarize_url,
    ):
        processor = BatchProcessor(
            user_id=UUID("00000000-0000-0000-0000-000000000001"),
            supabase_client=supabase_client,
            gemini_client=MagicMock(),
        )
        run = await processor.run_items(items, mode="realtime")

    assert run.total_urls == 2
    assert run.success_count == 1
    assert run.failed_count == 1
    assert run.status.value == "partial_success"
```

- [ ] **Step 2: Run test (fail)**

Run: `pytest website/features/summarization_engine/tests/unit/test_batch_processor.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement processor.py**

Create `website/features/summarization_engine/batch/processor.py`:

```python
"""BatchProcessor — runs a batch of URLs through the engine and persists.

In v1:
- Realtime mode: concurrent ingest+summarize with asyncio.Semaphore
- Batch-API mode: uses Gemini Batch API for Phase 1 only (stub for v2)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from website.features.summarization_engine.batch.input_loader import LoadedItem
from website.features.summarization_engine.batch.progress import (
    BatchProgressEvent,
    ProgressBroker,
    get_global_broker,
)
from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.core.models import (
    BatchRun,
    BatchRunStatus,
)
from website.features.summarization_engine.core.orchestrator import summarize_url
from website.features.summarization_engine.writers.supabase_writer import (
    SupabaseWriter,
)

logger = logging.getLogger("summarization_engine.batch")


class BatchProcessor:
    """Process a batch of URLs end-to-end."""

    def __init__(
        self,
        *,
        user_id: UUID,
        supabase_client: Any,
        gemini_client: Any,
        progress_broker: ProgressBroker | None = None,
    ):
        self._user_id = user_id
        self._sb = supabase_client
        self._gemini = gemini_client
        self._broker = progress_broker or get_global_broker()
        self._config = load_config()
        self._sem = asyncio.Semaphore(self._config.batch.max_concurrency)
        self._writer = SupabaseWriter(client=supabase_client)

    async def run_items(
        self,
        items: list[LoadedItem],
        *,
        mode: Literal["realtime", "batch_api", "auto"] = "auto",
        input_filename: str | None = None,
        input_format: Literal["csv", "json"] | None = None,
    ) -> BatchRun:
        effective_mode = self._resolve_mode(mode, len(items))
        run = await self._create_run_record(
            items, effective_mode, input_filename, input_format,
        )

        await self._broker.emit(BatchProgressEvent(
            event_type="started", run_id=run.id, total=len(items),
        ))

        if effective_mode == "batch_api":
            # v1 stub: fall back to realtime for now
            logger.info("batch_api mode requested; v1 falls back to realtime")
            await self._run_realtime(run, items)
        else:
            await self._run_realtime(run, items)

        await self._finalize_run(run)
        await self._broker.emit(BatchProgressEvent(
            event_type="completed", run_id=run.id,
            processed=run.processed_count, total=run.total_urls,
        ))
        return run

    def _resolve_mode(
        self, mode: Literal["realtime", "batch_api", "auto"], n_items: int,
    ) -> Literal["realtime", "batch_api"]:
        if mode == "auto":
            threshold = self._config.gemini.batch_api.threshold
            return "batch_api" if n_items >= threshold else "realtime"
        return mode

    async def _create_run_record(
        self,
        items: list[LoadedItem],
        mode: Literal["realtime", "batch_api"],
        input_filename: str | None,
        input_format: Literal["csv", "json"] | None,
    ) -> BatchRun:
        run_id = uuid4()
        run = BatchRun(
            id=run_id, user_id=self._user_id,
            status=BatchRunStatus.RUNNING,
            input_filename=input_filename, input_format=input_format,
            mode=mode, total_urls=len(items),
            started_at=datetime.now(timezone.utc),
        )
        row = {
            "id": str(run.id), "user_id": str(run.user_id),
            "status": run.status.value, "input_filename": run.input_filename,
            "input_format": run.input_format, "mode": run.mode,
            "total_urls": run.total_urls, "started_at": run.started_at.isoformat(),
        }
        try:
            self._sb.table("summarization_batch_runs").insert(row).execute()
        except Exception as exc:
            logger.warning("failed to create batch_run record: %s", exc)
        return run

    async def _run_realtime(self, run: BatchRun, items: list[LoadedItem]) -> None:
        tasks = [self._process_one(run, item) for item in items]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _process_one(self, run: BatchRun, item: LoadedItem) -> None:
        async with self._sem:
            item_id = uuid4()
            self._insert_item_record(run, item, item_id, "ingesting")
            await self._broker.emit(BatchProgressEvent(
                event_type="item_status", run_id=run.id,
                item_url=item.url, item_status="ingesting",
                processed=run.processed_count, total=run.total_urls,
            ))
            try:
                result = await summarize_url(
                    item.url, user_id=self._user_id, gemini_client=self._gemini,
                )
                # Merge user_tags into result.tags (deduped)
                if item.user_tags:
                    seen = set(result.tags)
                    for t in item.user_tags:
                        if t not in seen:
                            result.tags.append(t)
                            seen.add(t)

                write_result = await self._writer.write(result=result, user_id=self._user_id)
                self._update_item_record(
                    item_id, status="succeeded", node_id=write_result.node_id,
                    tokens=result.metadata.total_tokens_used,
                    latency_ms=result.metadata.total_latency_ms,
                )
                run.success_count += 1
                run.processed_count += 1
                await self._broker.emit(BatchProgressEvent(
                    event_type="item_status", run_id=run.id,
                    item_url=item.url, item_status="succeeded",
                    processed=run.processed_count, total=run.total_urls,
                ))
            except Exception as exc:
                logger.exception("batch item failed url=%s", item.url)
                self._update_item_record(
                    item_id, status="failed",
                    error_code=type(exc).__name__,
                    error_message=str(exc)[:500],
                )
                run.failed_count += 1
                run.processed_count += 1
                await self._broker.emit(BatchProgressEvent(
                    event_type="item_status", run_id=run.id,
                    item_url=item.url, item_status="failed",
                    processed=run.processed_count, total=run.total_urls,
                    message=str(exc)[:200],
                ))

    def _insert_item_record(
        self, run: BatchRun, item: LoadedItem, item_id: UUID, status: str,
    ) -> None:
        row = {
            "id": str(item_id),
            "run_id": str(run.id),
            "user_id": str(run.user_id),
            "url": item.url,
            "status": status,
            "user_tags": item.user_tags,
            "user_note": item.user_note,
        }
        try:
            self._sb.table("summarization_batch_items").insert(row).execute()
        except Exception as exc:
            logger.warning("failed to insert batch_item record: %s", exc)

    def _update_item_record(
        self, item_id: UUID, *, status: str,
        node_id: str | None = None, tokens: int | None = None,
        latency_ms: int | None = None,
        error_code: str | None = None, error_message: str | None = None,
    ) -> None:
        update: dict[str, Any] = {
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if node_id is not None:
            update["node_id"] = node_id
        if tokens is not None:
            update["tokens_used"] = tokens
        if latency_ms is not None:
            update["latency_ms"] = latency_ms
        if error_code:
            update["error_code"] = error_code
        if error_message:
            update["error_message"] = error_message
        try:
            self._sb.table("summarization_batch_items").update(update).eq(
                "id", str(item_id),
            ).execute()
        except Exception as exc:
            logger.warning("failed to update batch_item record: %s", exc)

    async def _finalize_run(self, run: BatchRun) -> None:
        run.completed_at = datetime.now(timezone.utc)
        if run.failed_count == 0:
            run.status = BatchRunStatus.COMPLETED
        elif run.success_count == 0:
            run.status = BatchRunStatus.FAILED
        else:
            run.status = BatchRunStatus.PARTIAL_SUCCESS
        update = {
            "status": run.status.value,
            "processed_count": run.processed_count,
            "success_count": run.success_count,
            "failed_count": run.failed_count,
            "skipped_count": run.skipped_count,
            "completed_at": run.completed_at.isoformat(),
        }
        try:
            self._sb.table("summarization_batch_runs").update(update).eq(
                "id", str(run.id),
            ).execute()
        except Exception as exc:
            logger.warning("failed to finalize batch_run: %s", exc)
```

- [ ] **Step 4: Run tests**

Run: `pytest website/features/summarization_engine/tests/unit/test_batch_processor.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/batch/processor.py website/features/summarization_engine/tests/unit/test_batch_processor.py
git commit -m "feat(engine): implement batch processor with concurrency + progress"
```

---

## Phase 10: API Routes (`/api/v2/*`)

### Task 10.1: API request/response models

**Files:**
- Create: `website/features/summarization_engine/api/__init__.py` (overwrite empty with package marker)
- Create: `website/features/summarization_engine/api/schemas.py`

- [ ] **Step 1: Create api/__init__.py and schemas.py**

`website/features/summarization_engine/api/__init__.py` stays empty.

Create `website/features/summarization_engine/api/schemas.py`:

```python
"""Request and response Pydantic schemas for /api/v2/* endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from website.features.summarization_engine.core.models import SummaryResult


class SummarizeRequest(BaseModel):
    url: str
    tier: Literal["pro", "flash", "tiered"] | None = None


class SummarizeResponse(BaseModel):
    summary: SummaryResult
    kg_node_id: str
    tokens_used: int
    latency_ms: int


class BatchRunCreated(BaseModel):
    run_id: UUID
    total_urls: int
    mode: Literal["realtime", "batch_api"]
    started_at: datetime


class BatchItemSummary(BaseModel):
    url: str
    status: str
    node_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class BatchRunStatus(BaseModel):
    run_id: UUID
    status: str
    total_urls: int
    processed_count: int
    success_count: int
    failed_count: int
    skipped_count: int
    mode: str
    started_at: datetime
    completed_at: datetime | None = None
    items: list[BatchItemSummary] = Field(default_factory=list)
    progress: float = 0.0


class BatchRunSummary(BaseModel):
    run_id: UUID
    status: str
    total_urls: int
    success_count: int
    failed_count: int
    started_at: datetime
    completed_at: datetime | None = None
```

- [ ] **Step 2: Commit**

```bash
git add website/features/summarization_engine/api/schemas.py
git commit -m "feat(engine): add API request/response schemas"
```

### Task 10.2: API routes

**Files:**
- Create: `website/features/summarization_engine/api/routes.py`
- Create: `website/features/summarization_engine/tests/unit/test_api_routes.py`

- [ ] **Step 1: Write failing test**

Create `website/features/summarization_engine/tests/unit/test_api_routes.py`:

```python
"""API routes smoke tests using TestClient + mocks."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from website.features.summarization_engine.api.routes import router
from website.features.summarization_engine.core.models import (
    DetailedSummarySection,
    SourceType,
    SummaryMetadata,
    SummaryResult,
)


@pytest.fixture
def app_with_mocks(monkeypatch):
    app = FastAPI()
    app.include_router(router)

    fake_user_id = UUID("00000000-0000-0000-0000-000000000001")

    async def fake_current_user(*args, **kwargs):
        from website.features.summarization_engine.api.routes import AuthenticatedUser
        return AuthenticatedUser(user_id=fake_user_id)

    monkeypatch.setattr(
        "website.features.summarization_engine.api.routes.get_current_user",
        fake_current_user,
    )
    return app


def _fake_summary(url: str) -> SummaryResult:
    meta = SummaryMetadata(
        source_type=SourceType.WEB, url=url,
        extraction_confidence="high", confidence_reason="ok",
        total_tokens_used=100, gemini_pro_tokens=80, gemini_flash_tokens=20,
        total_latency_ms=200, cod_iterations_used=2,
        self_check_missing_count=0, patch_applied=False,
    )
    return SummaryResult(
        mini_title="Fake title",
        brief_summary="Fake summary.",
        tags=["a", "b", "c", "d", "e", "f", "g", "h"],
        detailed_summary=[DetailedSummarySection(heading="h", bullets=["b"])],
        metadata=meta,
    )


def test_summarize_endpoint(app_with_mocks):
    async def fake_summarize(url, **kwargs):
        return _fake_summary(url)
    fake_write = AsyncMock()
    fake_write.return_value = MagicMock(node_id="fake-id", success=True)

    with patch(
        "website.features.summarization_engine.api.routes.summarize_url",
        side_effect=fake_summarize,
    ), patch(
        "website.features.summarization_engine.api.routes.SupabaseWriter",
    ) as SW, patch(
        "website.features.summarization_engine.api.routes._get_gemini_client",
        return_value=MagicMock(),
    ), patch(
        "website.features.summarization_engine.api.routes._get_supabase_client",
        return_value=MagicMock(),
    ):
        SW.return_value = MagicMock(write=fake_write)
        client = TestClient(app_with_mocks)
        resp = client.post("/api/v2/summarize", json={"url": "https://example.com"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["mini_title"] == "Fake title"
    assert body["kg_node_id"] == "fake-id"
```

- [ ] **Step 2: Run test (fail)**

Run: `pytest website/features/summarization_engine/tests/unit/test_api_routes.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement routes.py**

Create `website/features/summarization_engine/api/routes.py`:

```python
"""FastAPI routes for /api/v2/* endpoints.

Exposes the summarization engine via:
- POST /api/v2/summarize       — single URL, real-time
- POST /api/v2/batch           — multipart CSV/JSON upload
- GET  /api/v2/batch           — list recent runs for user
- GET  /api/v2/batch/{run_id}  — polled status
- GET  /api/v2/batch/{run_id}/stream — SSE progress stream
- POST /api/v2/batch/{run_id}/cancel — cancel in-progress run
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sse_starlette.sse import EventSourceResponse

from website.features.summarization_engine.api.schemas import (
    BatchItemSummary,
    BatchRunCreated,
    BatchRunStatus,
    BatchRunSummary,
    SummarizeRequest,
    SummarizeResponse,
)
from website.features.summarization_engine.batch.input_loader import (
    detect_format,
    load_input,
)
from website.features.summarization_engine.batch.processor import BatchProcessor
from website.features.summarization_engine.batch.progress import get_global_broker
from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.core.errors import EngineError
from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.core.orchestrator import summarize_url
from website.features.summarization_engine.writers.supabase_writer import (
    SupabaseWriter,
)

logger = logging.getLogger("summarization_engine.api")

router = APIRouter(prefix="/api/v2", tags=["summarization-engine-v2"])


@dataclass
class AuthenticatedUser:
    user_id: UUID


async def get_current_user() -> AuthenticatedUser:
    """Placeholder — integrate with website's existing JWT auth."""
    raise HTTPException(status_code=501, detail="Auth not wired in v2 stub")


def _get_supabase_client() -> Any:
    """Import and return the website's existing Supabase client."""
    from website.core.supabase_kg.client import get_supabase_client
    return get_supabase_client()


def _get_gemini_client() -> Any:
    """Build the TieredGeminiClient from the existing key pool."""
    from website.features.api_key_switching import get_key_pool
    pool = get_key_pool()
    return TieredGeminiClient(pool, load_config())


@router.post("/summarize", response_model=SummarizeResponse)
async def summarize_one(
    body: SummarizeRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> SummarizeResponse:
    """Summarize a single URL in real-time."""
    start = time.perf_counter()
    try:
        gemini_client = _get_gemini_client()
        result = await summarize_url(
            body.url,
            user_id=user.user_id,
            gemini_client=gemini_client,
        )
    except EngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    sb = _get_supabase_client()
    writer = SupabaseWriter(client=sb)
    write_result = await writer.write(result=result, user_id=user.user_id)

    latency_ms = int((time.perf_counter() - start) * 1000)
    return SummarizeResponse(
        summary=result,
        kg_node_id=write_result.node_id,
        tokens_used=result.metadata.total_tokens_used,
        latency_ms=latency_ms,
    )


@router.post("/batch", response_model=BatchRunCreated)
async def start_batch(
    file: UploadFile = File(...),
    use_batch_api: bool = Form(default=True),
    user: AuthenticatedUser = Depends(get_current_user),
) -> BatchRunCreated:
    """Upload a CSV or JSON batch input file."""
    config = load_config()
    content = await file.read()
    max_bytes = config.batch.max_input_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail="Input file too large")

    fmt = detect_format(file.filename or "", content)
    try:
        items = load_input(content, fmt=fmt)
    except EngineError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not items:
        raise HTTPException(status_code=400, detail="No valid URLs in input file")

    sb = _get_supabase_client()
    gemini = _get_gemini_client()
    processor = BatchProcessor(
        user_id=user.user_id, supabase_client=sb, gemini_client=gemini,
    )
    mode = "auto" if use_batch_api else "realtime"

    # Fire-and-forget: start the run, return immediately
    async def _run():
        try:
            await processor.run_items(
                items, mode=mode, input_filename=file.filename, input_format=fmt,
            )
        except Exception:
            logger.exception("batch run failed")

    task = asyncio.create_task(_run())
    # Wait a tiny moment so the run record exists
    await asyncio.sleep(0.1)

    # The processor assigns run.id internally; we need a handle
    # For v1, fetch the most recent run for this user
    recent = (
        sb.table("summarization_batch_runs")
        .select("id,total_urls,mode,started_at")
        .eq("user_id", str(user.user_id))
        .order("started_at", desc=True)
        .limit(1)
        .execute()
    )
    row = (recent.data or [{}])[0]
    return BatchRunCreated(
        run_id=UUID(row.get("id")) if row.get("id") else UUID(int=0),
        total_urls=row.get("total_urls", len(items)),
        mode=row.get("mode", "realtime"),
        started_at=row.get("started_at") or "1970-01-01T00:00:00Z",
    )


@router.get("/batch/{run_id}", response_model=BatchRunStatus)
async def get_batch_status(
    run_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
) -> BatchRunStatus:
    sb = _get_supabase_client()
    run_resp = (
        sb.table("summarization_batch_runs")
        .select("*")
        .eq("id", str(run_id))
        .eq("user_id", str(user.user_id))
        .single()
        .execute()
    )
    run = run_resp.data or {}
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    items_resp = (
        sb.table("summarization_batch_items")
        .select("url,status,node_id,error_code,error_message")
        .eq("run_id", str(run_id))
        .execute()
    )
    items = [
        BatchItemSummary(
            url=i["url"], status=i["status"],
            node_id=i.get("node_id"), error_code=i.get("error_code"),
            error_message=i.get("error_message"),
        )
        for i in (items_resp.data or [])
    ]
    total = int(run.get("total_urls", 0))
    processed = int(run.get("processed_count", 0))
    progress = (processed / total) if total else 0.0

    return BatchRunStatus(
        run_id=UUID(run["id"]),
        status=run["status"],
        total_urls=total,
        processed_count=processed,
        success_count=int(run.get("success_count", 0)),
        failed_count=int(run.get("failed_count", 0)),
        skipped_count=int(run.get("skipped_count", 0)),
        mode=run.get("mode", "realtime"),
        started_at=run.get("started_at"),
        completed_at=run.get("completed_at"),
        items=items,
        progress=progress,
    )


@router.get("/batch/{run_id}/stream")
async def stream_batch_progress(
    run_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
) -> EventSourceResponse:
    broker = get_global_broker()
    queue = broker.subscribe(run_id)

    async def event_generator() -> AsyncGenerator[dict, None]:
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": json.dumps({"ts": time.time()})}
                    continue
                yield {
                    "event": event.event_type,
                    "data": json.dumps(event.to_dict()),
                }
                if event.event_type in ("completed", "error"):
                    break
        finally:
            broker.unsubscribe(run_id, queue)

    return EventSourceResponse(event_generator())


@router.get("/batch", response_model=list[BatchRunSummary])
async def list_batches(
    limit: int = 20,
    user: AuthenticatedUser = Depends(get_current_user),
) -> list[BatchRunSummary]:
    sb = _get_supabase_client()
    resp = (
        sb.table("summarization_batch_runs")
        .select("id,status,total_urls,success_count,failed_count,started_at,completed_at")
        .eq("user_id", str(user.user_id))
        .order("started_at", desc=True)
        .limit(limit)
        .execute()
    )
    rows = resp.data or []
    return [
        BatchRunSummary(
            run_id=UUID(r["id"]), status=r["status"],
            total_urls=int(r.get("total_urls", 0)),
            success_count=int(r.get("success_count", 0)),
            failed_count=int(r.get("failed_count", 0)),
            started_at=r.get("started_at"),
            completed_at=r.get("completed_at"),
        )
        for r in rows
    ]


@router.post("/batch/{run_id}/cancel", response_model=BatchRunStatus)
async def cancel_batch(
    run_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
) -> BatchRunStatus:
    sb = _get_supabase_client()
    # v1: mark the run as cancelled; in-flight items finish
    sb.table("summarization_batch_runs").update({"status": "cancelled"}).eq(
        "id", str(run_id),
    ).eq("user_id", str(user.user_id)).execute()
    return await get_batch_status(run_id, user=user)
```

- [ ] **Step 4: Run smoke test**

Run: `pytest website/features/summarization_engine/tests/unit/test_api_routes.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/api/routes.py website/features/summarization_engine/tests/unit/test_api_routes.py
git commit -m "feat(engine): add /api/v2/* FastAPI routes"
```

### Task 10.3: Mount engine router in website/app.py

**Files:**
- Modify: `website/app.py`

- [ ] **Step 1: Read current app.py to find the right insertion point**

Run: `grep -n "include_router\|APIRouter" website/app.py`
Expected: find where existing routers are included.

- [ ] **Step 2: Add the import and include_router call**

Add near the top of `website/app.py` (or wherever existing routers are imported):

```python
from website.features.summarization_engine.api.routes import router as engine_v2_router
```

And where existing `app.include_router(...)` calls live, add:

```python
app.include_router(engine_v2_router)
```

- [ ] **Step 3: Verify it mounts**

Run: `python -c "from website.app import app; print([r.path for r in app.routes if '/api/v2' in getattr(r, 'path', '')])"`
Expected: list of 6 `/api/v2/...` routes.

- [ ] **Step 4: Commit**

```bash
git add website/app.py
git commit -m "feat(engine): mount /api/v2 router in website app"
```

---

## Phase 11: UI Dashboard

### Task 11.1: Batch dashboard HTML + CSS + JS

**Files:**
- Create: `website/features/summarization_engine/ui/index.html`
- Create: `website/features/summarization_engine/ui/css/engine.css`
- Create: `website/features/summarization_engine/ui/js/engine.js`

- [ ] **Step 1: Create index.html**

Create `website/features/summarization_engine/ui/index.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Summarization Engine v2 — Batch Dashboard</title>
  <link rel="stylesheet" href="/v2/batch/css/engine.css" />
</head>
<body>
  <header class="eng-header">
    <h1>Summarization Engine v2</h1>
    <p class="eng-subtitle">Batch dashboard — paste a URL or upload a CSV/JSON file</p>
  </header>

  <main class="eng-main">
    <section class="eng-card">
      <h2>Single URL</h2>
      <form id="single-form" class="eng-form">
        <input type="url" id="single-url" placeholder="https://example.com/article" required />
        <button type="submit">Summarize</button>
      </form>
      <div id="single-result" class="eng-result-card" hidden></div>
    </section>

    <section class="eng-card">
      <h2>Batch upload</h2>
      <form id="batch-form" class="eng-form" enctype="multipart/form-data">
        <input type="file" id="batch-file" accept=".csv,.json" required />
        <label><input type="checkbox" id="use-batch-api" checked /> Use Gemini Batch API for ≥50 URLs (50% cheaper)</label>
        <button type="submit">Start batch</button>
      </form>
      <div id="batch-status" class="eng-batch-status" hidden>
        <h3>Run <span id="run-id"></span></h3>
        <div class="eng-progress-bar"><div class="eng-progress-fill" id="progress-fill"></div></div>
        <p id="progress-text">0 / 0</p>
        <table class="eng-items-table">
          <thead><tr><th>URL</th><th>Status</th><th>Node</th></tr></thead>
          <tbody id="items-tbody"></tbody>
        </table>
      </div>
    </section>

    <section class="eng-card">
      <h2>Recent runs</h2>
      <div class="eng-filters">
        <input type="search" id="filter-text" placeholder="Filter by URL or tag..." />
        <select id="filter-source">
          <option value="">All sources</option>
          <option value="github">GitHub</option>
          <option value="newsletter">Newsletter</option>
          <option value="reddit">Reddit</option>
          <option value="youtube">YouTube</option>
          <option value="hackernews">HackerNews</option>
          <option value="linkedin">LinkedIn</option>
          <option value="arxiv">arXiv</option>
          <option value="podcast">Podcast</option>
          <option value="twitter">Twitter</option>
          <option value="web">Web</option>
        </select>
      </div>
      <table class="eng-runs-table">
        <thead><tr><th>Run</th><th>Status</th><th>Success</th><th>Failed</th><th>Started</th></tr></thead>
        <tbody id="runs-tbody"></tbody>
      </table>
    </section>
  </main>

  <script src="/v2/batch/js/engine.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create engine.css**

Create `website/features/summarization_engine/ui/css/engine.css`:

```css
/* Summarization Engine v2 — Batch Dashboard styles.
   NOTE: No purple, violet, or lavender per project CLAUDE.md rule.
   Accent: teal. */
:root {
  --accent-color: #16A89C;
  --accent-color-dark: #0E7E75;
  --bg-color: #FAFBFC;
  --card-bg: #FFFFFF;
  --text-color: #1A1F2E;
  --text-muted: #6B7280;
  --border-color: #E5E7EB;
  --success-color: #10B981;
  --error-color: #EF4444;
  --warn-color: #F59E0B;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: var(--bg-color);
  color: var(--text-color);
  line-height: 1.5;
}

.eng-header {
  padding: 24px 32px;
  border-bottom: 1px solid var(--border-color);
  background: var(--card-bg);
}

.eng-header h1 { margin: 0; font-size: 24px; color: var(--accent-color); }
.eng-subtitle { margin: 4px 0 0; color: var(--text-muted); }

.eng-main {
  max-width: 1100px;
  margin: 32px auto;
  padding: 0 16px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.eng-card {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 24px;
}

.eng-card h2 { margin-top: 0; font-size: 18px; }

.eng-form {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}

.eng-form input[type="url"],
.eng-form input[type="search"],
.eng-form select {
  flex: 1;
  min-width: 260px;
  padding: 10px 14px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font-size: 14px;
}

.eng-form button {
  padding: 10px 20px;
  background: var(--accent-color);
  color: #fff;
  border: none;
  border-radius: 6px;
  font-weight: 600;
  cursor: pointer;
}

.eng-form button:hover { background: var(--accent-color-dark); }

.eng-result-card {
  margin-top: 16px;
  padding: 16px;
  background: #F3F4F6;
  border-radius: 6px;
  white-space: pre-wrap;
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 13px;
}

.eng-progress-bar {
  height: 8px;
  background: #E5E7EB;
  border-radius: 4px;
  overflow: hidden;
  margin-top: 12px;
}
.eng-progress-fill {
  height: 100%;
  width: 0%;
  background: var(--accent-color);
  transition: width 200ms ease-out;
}

.eng-items-table,
.eng-runs-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 12px;
}
.eng-items-table th,
.eng-items-table td,
.eng-runs-table th,
.eng-runs-table td {
  text-align: left;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-color);
  font-size: 13px;
}
.status-succeeded { color: var(--success-color); font-weight: 600; }
.status-failed { color: var(--error-color); font-weight: 600; }
.status-running { color: var(--warn-color); }

.eng-filters {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}
```

- [ ] **Step 3: Create engine.js**

Create `website/features/summarization_engine/ui/js/engine.js`:

```javascript
// Summarization Engine v2 — Batch Dashboard client-side logic.
// Vanilla JS, no framework.

(function () {
  const singleForm = document.getElementById("single-form");
  const singleUrl = document.getElementById("single-url");
  const singleResult = document.getElementById("single-result");

  const batchForm = document.getElementById("batch-form");
  const batchFile = document.getElementById("batch-file");
  const useBatchApi = document.getElementById("use-batch-api");
  const batchStatusEl = document.getElementById("batch-status");
  const runIdSpan = document.getElementById("run-id");
  const progressFill = document.getElementById("progress-fill");
  const progressText = document.getElementById("progress-text");
  const itemsTbody = document.getElementById("items-tbody");

  const runsTbody = document.getElementById("runs-tbody");
  const filterText = document.getElementById("filter-text");
  const filterSource = document.getElementById("filter-source");

  singleForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    singleResult.hidden = false;
    singleResult.textContent = "Processing…";
    try {
      const resp = await fetch("/api/v2/summarize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: singleUrl.value }),
      });
      if (!resp.ok) {
        singleResult.textContent = `Error ${resp.status}: ${await resp.text()}`;
        return;
      }
      const data = await resp.json();
      singleResult.textContent = JSON.stringify(data.summary, null, 2);
    } catch (err) {
      singleResult.textContent = "Network error: " + err.message;
    }
  });

  batchForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!batchFile.files.length) return;
    const fd = new FormData();
    fd.append("file", batchFile.files[0]);
    fd.append("use_batch_api", useBatchApi.checked ? "true" : "false");

    const resp = await fetch("/api/v2/batch", { method: "POST", body: fd });
    if (!resp.ok) {
      alert(`Error ${resp.status}: ${await resp.text()}`);
      return;
    }
    const data = await resp.json();
    subscribeToBatch(data.run_id, data.total_urls);
  });

  function subscribeToBatch(runId, total) {
    batchStatusEl.hidden = false;
    runIdSpan.textContent = runId;
    progressFill.style.width = "0%";
    progressText.textContent = `0 / ${total}`;
    itemsTbody.innerHTML = "";

    const es = new EventSource(`/api/v2/batch/${runId}/stream`);

    es.addEventListener("item_status", (ev) => {
      const data = JSON.parse(ev.data);
      progressText.textContent = `${data.processed} / ${data.total}`;
      progressFill.style.width = `${(data.processed / data.total) * 100}%`;

      const existing = itemsTbody.querySelector(`[data-url="${data.item_url}"]`);
      if (existing) {
        existing.querySelector(".status-cell").textContent = data.item_status;
        existing.querySelector(".status-cell").className = `status-cell status-${data.item_status}`;
      } else {
        const tr = document.createElement("tr");
        tr.dataset.url = data.item_url;
        tr.innerHTML = `<td>${escapeHtml(data.item_url || "")}</td>
          <td class="status-cell status-${data.item_status}">${data.item_status}</td>
          <td></td>`;
        itemsTbody.appendChild(tr);
      }
    });

    es.addEventListener("completed", () => {
      es.close();
      loadRecentRuns();
    });

    es.addEventListener("error", () => {
      es.close();
    });
  }

  async function loadRecentRuns() {
    try {
      const resp = await fetch("/api/v2/batch?limit=20");
      if (!resp.ok) return;
      const rows = await resp.json();
      renderRuns(rows);
    } catch (_) { /* ignore */ }
  }

  function renderRuns(rows) {
    runsTbody.innerHTML = "";
    const filter = (filterText.value || "").toLowerCase();
    const sourceFilter = filterSource.value || "";
    for (const r of rows) {
      if (filter && !String(r.run_id).toLowerCase().includes(filter)) continue;
      // source filter is a placeholder for when run_id → source_type is joined
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><a href="#${r.run_id}">${r.run_id.slice(0, 8)}…</a></td>
        <td class="status-${r.status}">${r.status}</td>
        <td>${r.success_count}/${r.total_urls}</td>
        <td>${r.failed_count}</td>
        <td>${r.started_at || ""}</td>`;
      runsTbody.appendChild(tr);
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  filterText.addEventListener("input", loadRecentRuns);
  filterSource.addEventListener("change", loadRecentRuns);

  loadRecentRuns();
})();
```

- [ ] **Step 4: Mount static files in website/app.py**

Read `website/app.py` to find how existing features are served as static (look for `StaticFiles` or `FileResponse`), then add:

```python
from fastapi.staticfiles import StaticFiles

app.mount(
    "/v2/batch/css",
    StaticFiles(directory="website/features/summarization_engine/ui/css"),
    name="engine-v2-css",
)
app.mount(
    "/v2/batch/js",
    StaticFiles(directory="website/features/summarization_engine/ui/js"),
    name="engine-v2-js",
)

@app.get("/v2/batch")
async def engine_v2_batch_ui():
    from fastapi.responses import FileResponse
    return FileResponse("website/features/summarization_engine/ui/index.html")
```

- [ ] **Step 5: Smoke-test the route**

Run: `python -c "from website.app import app; print([r.path for r in app.routes if 'v2' in getattr(r, 'path', '')])"`
Expected: shows `/v2/batch` plus the `/api/v2/*` routes.

- [ ] **Step 6: Commit**

```bash
git add website/features/summarization_engine/ui/ website/app.py
git commit -m "feat(engine): add batch dashboard UI with SSE progress"
```

---

## Phase 12: Live Tests + CI

### Task 12.1: Live test suite

**Files:**
- Create: `website/features/summarization_engine/tests/live/test_live_ingestors.py`

- [ ] **Step 1: Create live ingestor tests**

Create `website/features/summarization_engine/tests/live/test_live_ingestors.py`:

```python
"""Live ingestor tests — require --live flag.

Each test hits a real public URL and verifies basic extraction works.
Tolerant of transient failures: a test may be marked expected-fail if
the upstream is known-flaky (Nitter, LinkedIn).
"""
import pytest

from website.features.summarization_engine.source_ingest import get_ingestor
from website.features.summarization_engine.core.models import SourceType

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_live_github_public_repo():
    ingestor_cls = get_ingestor(SourceType.GITHUB)
    ingestor = ingestor_cls()
    result = await ingestor.ingest(
        "https://github.com/python/cpython",
        config={"fetch_issues": True, "max_issues": 5, "fetch_commits": True, "max_commits": 5},
    )
    assert "cpython" in result.raw_text.lower() or "python" in result.raw_text.lower()
    assert result.extraction_confidence in ("high", "medium")


@pytest.mark.asyncio
async def test_live_hackernews():
    ingestor_cls = get_ingestor(SourceType.HACKERNEWS)
    ingestor = ingestor_cls()
    result = await ingestor.ingest(
        "https://news.ycombinator.com/item?id=1",
        config={"max_comments": 10, "comment_min_points": 0, "include_linked_article": False},
    )
    assert result.metadata.get("points") is not None


@pytest.mark.asyncio
async def test_live_arxiv():
    ingestor_cls = get_ingestor(SourceType.ARXIV)
    ingestor = ingestor_cls()
    result = await ingestor.ingest(
        "https://arxiv.org/abs/2310.11511",
        config={"prefer_html_version": True, "pdf_parser": "pymupdf", "rate_limit_delay_sec": 3.0},
    )
    assert result.metadata.get("arxiv_id") == "2310.11511"
    assert result.extraction_confidence in ("high", "medium")


@pytest.mark.asyncio
async def test_live_twitter_oembed():
    ingestor_cls = get_ingestor(SourceType.TWITTER)
    ingestor = ingestor_cls()
    # Use a tweet from a verified account known to be public
    try:
        result = await ingestor.ingest(
            "https://twitter.com/jack/status/20",
            config={"use_oembed": True, "use_nitter_fallback": False, "nitter_instances": []},
        )
    except Exception as exc:
        pytest.xfail(f"Twitter oEmbed may be flaky: {exc}")
    assert result.metadata.get("author_name")
```

- [ ] **Step 2: Run (skipped without --live)**

Run: `pytest website/features/summarization_engine/tests/live/ -v`
Expected: all marked skipped (no --live flag).

- [ ] **Step 3: Commit**

```bash
git add website/features/summarization_engine/tests/live/test_live_ingestors.py
git commit -m "test(engine): add live ingestor tests (--live opt-in)"
```

### Task 12.2: Full-pipeline live test

**Files:**
- Create: `website/features/summarization_engine/tests/live/test_live_pipeline.py`

- [ ] **Step 1: Create live pipeline test**

Create `website/features/summarization_engine/tests/live/test_live_pipeline.py`:

```python
"""End-to-end live test with real Gemini. Requires --live + api_env file."""
from uuid import UUID

import pytest

from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.core.orchestrator import summarize_url

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_live_pipeline_github():
    try:
        from website.features.api_key_switching import get_key_pool
        pool = get_key_pool()
    except Exception as exc:
        pytest.skip(f"No Gemini key pool available: {exc}")

    client = TieredGeminiClient(pool, load_config())

    result = await summarize_url(
        "https://github.com/anthropic-ai/anthropic-sdk-python",
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        gemini_client=client,
    )

    assert len(result.mini_title.split()) <= 5
    assert len(result.brief_summary.split()) <= 50
    assert 8 <= len(result.tags) <= 15
    assert len(result.detailed_summary) >= 1
    assert result.metadata.cod_iterations_used >= 1
    assert result.metadata.total_tokens_used > 0
```

- [ ] **Step 2: Commit**

```bash
git add website/features/summarization_engine/tests/live/test_live_pipeline.py
git commit -m "test(engine): add end-to-end live pipeline test"
```

### Task 12.3: CI workflow for live tests (weekly)

**Files:**
- Create: `.github/workflows/engine-live-tests.yml`

- [ ] **Step 1: Create the workflow**

Create `.github/workflows/engine-live-tests.yml`:

```yaml
name: Engine v2 Live Tests

on:
  schedule:
    - cron: '0 6 * * 1'   # weekly Monday 06:00 UTC
  workflow_dispatch:

jobs:
  live:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install -r ops/requirements.txt
      - name: Write api_env from secret
        run: |
          printf '%s\n' "${{ secrets.GEMINI_API_KEYS }}" > api_env
      - name: Run live tests
        env:
          GITHUB_TOKEN: ${{ secrets.GH_READ_TOKEN }}
        run: |
          pytest website/features/summarization_engine/tests/live/ -v --live
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/engine-live-tests.yml
git commit -m "ci(engine): weekly live tests workflow"
```

### Task 12.4: Final full-suite test run

- [ ] **Step 1: Run the entire engine test suite (unit + integration, no live)**

Run: `pytest website/features/summarization_engine/ -v --tb=short`
Expected: all unit + integration tests pass. No live tests run.

- [ ] **Step 2: Run with coverage**

Run: `pytest website/features/summarization_engine/ --cov=website.features.summarization_engine --cov-report=term-missing`
Expected: ≥80% coverage on core modules.

- [ ] **Step 3: Final commit / tag**

```bash
git tag engine-v2.0.0-rc1
git commit --allow-empty -m "chore(engine): v2.0.0-rc1 full suite passing"
```

---

## Plan complete

All 12 phases are now defined. Next: see the self-review section below, then use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement.

