"""Schema-routing coverage for StructuredExtractor.

These tests protect the iter-01 baseline for the 4 major sources by asserting
that the source-specific payload class drives the prompt + response schema,
that valid Gemini output yields a populated SummaryResult (no schema fallback),
and that the `_schema_fallback_` marker appears when parsing fails.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.summarization.common import structured
from website.features.summarization_engine.summarization.common.structured import (
    StructuredExtractor,
    _apply_identifier_hints,
    _coerce_detailed_summary,
    _normalize_tags,
)
from website.features.summarization_engine.summarization.github.schema import GitHubStructuredPayload
from website.features.summarization_engine.summarization.reddit.schema import RedditStructuredPayload
from website.features.summarization_engine.summarization.youtube.schema import YouTubeStructuredPayload


def _make_ingest(source_type: SourceType, url: str) -> IngestResult:
    from datetime import datetime, timezone

    return IngestResult(
        source_type=source_type,
        url=url,
        original_url=url,
        raw_text="source raw",
        sections={"Body": "source raw"},
        metadata={"title": "Ingest Title"},
        extraction_confidence="high",
        confidence_reason="test fixture",
        fetched_at=datetime.now(timezone.utc),
    )


def _mock_client_returning(json_payload: dict | str):
    text = json.dumps(json_payload) if isinstance(json_payload, dict) else json_payload
    result = SimpleNamespace(text=text, input_tokens=10, output_tokens=20, model_used="gemini-flash")
    client = SimpleNamespace(generate=AsyncMock(return_value=result))
    return client


def test_identifier_hints_github_patches_mini_title_from_full_name():
    ingest = _make_ingest(SourceType.GITHUB, "https://github.com/fastapi/fastapi")
    ingest.metadata["full_name"] = "fastapi/fastapi"
    raw = {"mini_title": "fastapi.repository", "brief_summary": "x"}
    out = _apply_identifier_hints(raw, ingest)
    assert out["mini_title"] == "fastapi/fastapi"


def test_identifier_hints_reddit_prepends_subreddit_when_missing():
    ingest = _make_ingest(SourceType.REDDIT, "https://reddit.com/r/IAmA/comments/x/")
    ingest.metadata["subreddit"] = "IAmA"
    raw = {"mini_title": "heroin-once", "brief_summary": "x"}
    out = _apply_identifier_hints(raw, ingest)
    assert out["mini_title"].startswith("r/IAmA ")


def test_identifier_hints_reddit_keeps_already_prefixed_title():
    ingest = _make_ingest(SourceType.REDDIT, "https://reddit.com/r/india/comments/y/")
    ingest.metadata["subreddit"] = "india"
    raw = {"mini_title": "r/india stock market thread", "brief_summary": "x"}
    out = _apply_identifier_hints(raw, ingest)
    assert out["mini_title"] == "r/india stock market thread"


def test_normalize_tags_strips_boilerplate_unless_allowed():
    assert _normalize_tags(["foo", "Bar Baz"], 2, 10) == ["foo", "bar-baz"]
    assert _normalize_tags(["foo"], 5, 10) == ["foo"], "should NOT pad when allow_boilerplate_pad=False"
    padded = _normalize_tags(["foo"], 5, 10, allow_boilerplate_pad=True, source_type_value="youtube")
    assert "_schema_fallback_" not in padded
    assert padded[0] == "foo"
    assert len(padded) >= 5


def test_coerce_handles_list_of_sections():
    class Dummy:
        detailed_summary = [
            {"heading": "A", "bullets": ["a1"]},
            {"heading": "B", "bullets": []},
        ]

    out = _coerce_detailed_summary(Dummy())
    assert len(out) == 2
    assert out[0].heading == "A"
    assert out[1].bullets == ["B"]


def test_coerce_handles_nested_object_payload():
    yt = YouTubeStructuredPayload(
        mini_title="Short title",
        brief_summary="brief",
        tags=["a", "b", "c", "d", "e", "f", "g"],
        speakers=["Alice"],
        guests=None,
        entities_discussed=[],
        detailed_summary={
            "thesis": "x",
            "format": "lecture",
            "chapters_or_segments": [{"timestamp": "0:00", "title": "intro", "bullets": ["b"]}],
            "demonstrations": [],
            "closing_takeaway": "end",
        },
    )
    sections = _coerce_detailed_summary(yt)
    headings = {s.heading for s in sections}
    assert "thesis" in headings
    assert "chapters_or_segments" in headings
    assert "closing_takeaway" in headings


@pytest.mark.asyncio
async def test_extract_success_youtube_populates_structured_payload():
    client = _mock_client_returning(
        {
            "mini_title": "DMT explainer",
            "brief_summary": "Short brief of the DMT video.",
            "tags": ["dmt", "neuroscience", "psychedelics", "pharmacology", "serotonin", "consciousness", "science"],
            "speakers": ["Dr. Smith"],
            "guests": None,
            "entities_discussed": ["DMT"],
            "detailed_summary": {
                "thesis": "DMT binds serotonin receptors.",
                "format": "lecture",
                "chapters_or_segments": [
                    {"timestamp": "0:00", "title": "Chemistry", "bullets": ["indole ring"]}
                ],
                "demonstrations": [],
                "closing_takeaway": "More research needed.",
            },
        }
    )
    cfg = load_config()
    ext = StructuredExtractor(client, cfg, payload_class=YouTubeStructuredPayload)
    ingest = _make_ingest(SourceType.YOUTUBE, "https://www.youtube.com/watch?v=x")

    result = await ext.extract(
        ingest,
        summary_text="Patched summary prose.",
        pro_tokens=100,
        flash_tokens=0,
        latency_ms=123,
        cod_iterations_used=2,
        self_check_missing_count=0,
        patch_applied=False,
    )

    assert result.metadata.is_schema_fallback is False
    assert result.metadata.structured_payload is not None
    assert "thesis" in result.metadata.structured_payload["detailed_summary"]
    assert result.tags[0] == "dmt"
    assert "_schema_fallback_" not in result.tags
    assert "zettelkasten" not in result.tags
    # detailed_summary coerced via compose_youtube_detailed: hierarchical composed shape
    headings = {s.heading for s in result.detailed_summary}
    assert "Overview" in headings
    assert "Closing remarks" in headings
    assert "Chapter walkthrough" in headings


@pytest.mark.asyncio
async def test_extract_success_reddit_preserves_rich_payload():
    client = _mock_client_returning(
        {
            "mini_title": "r/india GMP-Rajkot claim disputed",
            "brief_summary": "OP claims Rajkot drives IPO GMP; replies disagree.",
            "tags": ["india", "ipo", "gmp", "rajkot", "reddit-india", "investing", "grey-market"],
            "detailed_summary": {
                "op_intent": "seek validation",
                "reply_clusters": [{"theme": "skeptical", "reasoning": "no data", "examples": []}],
                "counterarguments": ["Mumbai GMP > Rajkot"],
                "unresolved_questions": [],
                "moderation_context": None,
            },
        }
    )
    cfg = load_config()
    ext = StructuredExtractor(client, cfg, payload_class=RedditStructuredPayload)
    ingest = _make_ingest(SourceType.REDDIT, "https://www.reddit.com/r/india/comments/abc/")

    result = await ext.extract(
        ingest,
        summary_text="patched text",
        pro_tokens=100,
        flash_tokens=0,
        latency_ms=50,
        cod_iterations_used=1,
        self_check_missing_count=0,
        patch_applied=False,
    )

    assert result.metadata.is_schema_fallback is False
    assert result.metadata.structured_payload["detailed_summary"]["op_intent"] == "seek validation"
    assert result.mini_title.startswith("r/india")


@pytest.mark.asyncio
async def test_extract_success_github_list_detailed_summary():
    client = _mock_client_returning(
        {
            "mini_title": "fastapi/fastapi",
            "architecture_overview": "FastAPI is an ASGI framework using pydantic + starlette under the hood for type-safe APIs.",
            "brief_summary": "High-perf Python API framework.",
            "tags": ["fastapi", "python", "asgi", "starlette", "pydantic", "openapi", "webdev"],
            "benchmarks_tests_examples": None,
            "detailed_summary": [
                {
                    "heading": "routing",
                    "bullets": ["APIRouter", "decorators"],
                    "module_or_feature": "routing",
                    "main_stack": ["starlette"],
                    "public_interfaces": ["APIRouter"],
                    "usability_signals": ["type-hints"],
                }
            ],
        }
    )
    cfg = load_config()
    ext = StructuredExtractor(client, cfg, payload_class=GitHubStructuredPayload)
    ingest = _make_ingest(SourceType.GITHUB, "https://github.com/fastapi/fastapi")

    result = await ext.extract(
        ingest,
        summary_text="patched",
        pro_tokens=100,
        flash_tokens=0,
        latency_ms=50,
        cod_iterations_used=1,
        self_check_missing_count=0,
        patch_applied=False,
    )

    assert result.metadata.is_schema_fallback is False
    assert result.mini_title == "fastapi/fastapi"
    headings = {s.heading for s in result.detailed_summary}
    assert "Overview" in headings
    assert "Features and modules" in headings
    assert "Closing remarks" in headings
    features = next(s for s in result.detailed_summary if s.heading == "Features and modules")
    assert "routing" in features.sub_sections


@pytest.mark.asyncio
async def test_extract_schema_fallback_marks_metadata_and_tag():
    client = _mock_client_returning("not json at all — fallback path")
    cfg = load_config()
    ext = StructuredExtractor(client, cfg, payload_class=YouTubeStructuredPayload)
    ingest = _make_ingest(SourceType.YOUTUBE, "https://www.youtube.com/watch?v=x")

    result = await ext.extract(
        ingest,
        summary_text="some summary text here",
        pro_tokens=100,
        flash_tokens=0,
        latency_ms=50,
        cod_iterations_used=1,
        self_check_missing_count=0,
        patch_applied=False,
    )

    assert result.metadata.is_schema_fallback is True
    assert result.metadata.structured_payload is None
    # Sentinel tag is stripped from the user-facing list (never reaches Obsidian
    # notes / KG nodes); fallback is detectable via metadata.is_schema_fallback.
    assert "_schema_fallback_" not in result.tags
    # Boilerplate padding is allowed on fallback path to keep tags within min/max.
    assert len(result.tags) >= cfg.structured_extract.tags_min


@pytest.mark.asyncio
async def test_extract_retries_once_before_schema_fallback():
    bad = SimpleNamespace(
        text='{"mini_title":"DMT explainer"',
        input_tokens=10,
        output_tokens=20,
        model_used="gemini-flash",
    )
    good = SimpleNamespace(
        text=json.dumps(
            {
                "mini_title": "DMT explainer",
                "brief_summary": "Short brief of the DMT video.",
                "tags": [
                    "dmt",
                    "neuroscience",
                    "psychedelics",
                    "pharmacology",
                    "serotonin",
                    "consciousness",
                    "science",
                ],
                "speakers": ["Dr. Smith"],
                "guests": None,
                "entities_discussed": ["DMT"],
                "detailed_summary": {
                    "thesis": "DMT binds serotonin receptors.",
                    "format": "lecture",
                    "chapters_or_segments": [
                        {"timestamp": "0:00", "title": "Chemistry", "bullets": ["indole ring"]}
                    ],
                    "demonstrations": [],
                    "closing_takeaway": "More research needed.",
                },
            }
        ),
        input_tokens=11,
        output_tokens=21,
        model_used="gemini-flash",
    )
    client = SimpleNamespace(generate=AsyncMock(side_effect=[bad, good]))
    cfg = load_config()
    ext = StructuredExtractor(client, cfg, payload_class=YouTubeStructuredPayload)
    ingest = _make_ingest(SourceType.YOUTUBE, "https://www.youtube.com/watch?v=x")

    result = await ext.extract(
        ingest,
        summary_text="Patched summary prose with [00:42] grounding markers.",
        pro_tokens=100,
        flash_tokens=0,
        latency_ms=123,
        cod_iterations_used=2,
        self_check_missing_count=0,
        patch_applied=False,
    )

    assert client.generate.await_count == 2
    assert result.metadata.is_schema_fallback is False
    assert result.metadata.structured_payload is not None
    assert result.tags[0] == "dmt"


@pytest.mark.asyncio
async def test_extract_fallback_does_not_happen_on_missing_optional_fields():
    """Optional fields (guests=null, entities_discussed=[]) must not trigger fallback."""
    client = _mock_client_returning(
        {
            "mini_title": "Short",
            "brief_summary": "Brief.",
            "tags": ["t1", "t2", "t3", "t4", "t5", "t6", "t7"],
            "speakers": ["Alice"],
            "guests": None,
            "entities_discussed": [],
            "detailed_summary": {
                "thesis": "t",
                "format": "vlog",
                "chapters_or_segments": [{"timestamp": "0:00", "title": "c", "bullets": ["b"]}],
                "demonstrations": [],
                "closing_takeaway": "end",
            },
        }
    )
    cfg = load_config()
    ext = StructuredExtractor(client, cfg, payload_class=YouTubeStructuredPayload)
    ingest = _make_ingest(SourceType.YOUTUBE, "https://www.youtube.com/watch?v=x")
    result = await ext.extract(
        ingest, summary_text="s", pro_tokens=0, flash_tokens=0, latency_ms=0,
        cod_iterations_used=0, self_check_missing_count=0, patch_applied=False,
    )
    assert result.metadata.is_schema_fallback is False


def test_prompt_includes_payload_class_schema():
    cfg = load_config()
    ext = StructuredExtractor(client=None, config=cfg, payload_class=YouTubeStructuredPayload)
    snippet = ext._schema_snippet()
    assert "chapters_or_segments" in snippet
    assert "closing_takeaway" in snippet
    assert "speakers" in snippet

    ext2 = StructuredExtractor(client=None, config=cfg, payload_class=RedditStructuredPayload)
    snippet2 = ext2._schema_snippet()
    assert "reply_clusters" in snippet2
    assert "op_intent" in snippet2
