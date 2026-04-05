"""Comprehensive offline tests for GeminiSummarizer and build_tag_list.

Covers:
  R008 — Structured summarization (happy path, token count, fences, truncation)
  R022 — Graceful degradation (API exceptions, safety block, timeout, malformed JSON)
  R009 — Multi-dimensional tagging (all axes, source axis, empty tags, multi-domain,
           hierarchical format)
  Construction — empty API key, raw fallback truncation

All tests mock `telegram_bot.pipeline.summarizer.genai.Client` so zero
real API calls are made. asyncio_mode=auto is already set in pytest.ini, so
no @pytest.mark.asyncio decorators are needed.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from telegram_bot.models.capture import ExtractedContent, SourceType
from telegram_bot.pipeline.summarizer import (
    GeminiSummarizer,
    SummarizationResult,
    build_tag_list,
)

# ── Helpers ──────────────────────────────────────────────────────────────────

_PATCH_TARGET = "telegram_bot.pipeline.summarizer.genai.Client"


def make_content(
    body: str = "Some article body text.",
    title: str = "Test Article",
    url: str = "https://example.com/article",
    source_type: SourceType = SourceType.WEB,
) -> ExtractedContent:
    """Build an ExtractedContent with controllable fields."""
    return ExtractedContent(
        url=url,
        source_type=source_type,
        title=title,
        body=body,
    )


def make_mock_client(response_text: str, token_count: int = 500):
    """Return a (MockClient class, configured mock instance) pair.

    Patches genai.Client so that:
      - MockClient() returns mock_instance
      - mock_instance.aio.models.generate_content is an AsyncMock
        returning a response with .text = response_text and
        .usage_metadata.total_token_count = token_count
    """
    mock_response = MagicMock()
    mock_response.text = response_text
    mock_response.usage_metadata = MagicMock()
    mock_response.usage_metadata.total_token_count = token_count

    mock_aio = MagicMock()
    mock_aio.models.generate_content = AsyncMock(return_value=mock_response)

    mock_instance = MagicMock()
    mock_instance.aio = mock_aio

    return mock_instance, mock_response


def _valid_json_text(
    summary: str = "A structured summary.",
    tags: dict | None = None,
    one_line: str = "Key takeaway here.",
) -> str:
    if tags is None:
        tags = {
            "domain": ["AI"],
            "type": ["Research"],
            "difficulty": ["Intermediate"],
            "keywords": ["transformer", "attention"],
        }
    return json.dumps({"summary": summary, "tags": tags, "one_line_summary": one_line})


# ── R008: Structured summarization ───────────────────────────────────────────


async def test_summarize_happy_path():
    """Valid JSON response → SummarizationResult with all fields populated."""
    content = make_content()
    json_text = _valid_json_text(
        summary="## Section\n- point one",
        one_line="Key takeaway here.",
        tags={
            "domain": ["AI"],
            "type": ["Research"],
            "difficulty": ["Advanced"],
            "keywords": ["neural", "net"],
        },
    )

    with patch(_PATCH_TARGET) as MockClient:
        mock_instance, _ = make_mock_client(response_text=json_text, token_count=123)
        MockClient.return_value = mock_instance

        summarizer = GeminiSummarizer(api_key="fake-key")
        result = await summarizer.summarize(content)

    assert isinstance(result, SummarizationResult)
    assert result.summary == "## Section\n- point one"
    assert result.one_line_summary == "Key takeaway here."
    assert result.tags["domain"] == ["AI"]
    assert result.tags["type"] == ["Research"]
    assert result.tags["difficulty"] == ["Advanced"]
    assert result.is_raw_fallback is False
    assert result.latency_ms >= 0


async def test_summarize_preserves_token_count():
    """usage_metadata.total_token_count flows through into result.tokens_used."""
    content = make_content()
    json_text = _valid_json_text()

    with patch(_PATCH_TARGET) as MockClient:
        mock_instance, _ = make_mock_client(response_text=json_text, token_count=999)
        MockClient.return_value = mock_instance

        summarizer = GeminiSummarizer(api_key="fake-key")
        result = await summarizer.summarize(content)

    assert result.tokens_used == 999


async def test_summarize_markdown_fence_stripped():
    """Response wrapped in ```json ... ``` fences still parses correctly."""
    content = make_content()
    inner = _valid_json_text(summary="Fenced summary")
    fenced_text = f"```json\n{inner}\n```"

    with patch(_PATCH_TARGET) as MockClient:
        mock_instance, _ = make_mock_client(response_text=fenced_text)
        MockClient.return_value = mock_instance

        summarizer = GeminiSummarizer(api_key="fake-key")
        result = await summarizer.summarize(content)

    assert result.summary == "Fenced summary"
    assert result.is_raw_fallback is False


async def test_summarize_body_truncated_to_15000_chars():
    """Body > 15 000 chars is capped: the prompt sent to generate_content must
    contain only the first 15 000 characters of the body, not the full 20 000."""
    long_body = "Z" * 20_000  # unique char unlikely to appear in the prompt template
    content = make_content(body=long_body)
    json_text = _valid_json_text()

    with patch(_PATCH_TARGET) as MockClient:
        mock_instance, _ = make_mock_client(response_text=json_text)
        MockClient.return_value = mock_instance

        summarizer = GeminiSummarizer(api_key="fake-key")
        await summarizer.summarize(content)

    # Retrieve the 'contents' kwarg passed to generate_content
    call_kwargs = mock_instance.aio.models.generate_content.call_args
    prompt_str: str = call_kwargs.kwargs.get("contents") or call_kwargs.args[1]

    # body[:15000] is 15 000 'Z's; body[15001:] is NOT in the prompt
    z_count = prompt_str.count("Z")
    assert z_count == 15_000, (
        f"Expected exactly 15 000 'Z' chars in prompt (body capped at 15 000), "
        f"got {z_count}"
    )


# ── R022: Graceful degradation ────────────────────────────────────────────────


async def test_summarize_api_exception_triggers_raw_fallback():
    """AsyncMock side_effect=Exception → is_raw_fallback=True, summary = body[:5000]."""
    body = "Article body " * 100
    content = make_content(body=body)

    with patch(_PATCH_TARGET) as MockClient:
        mock_aio = MagicMock()
        mock_aio.models.generate_content = AsyncMock(
            side_effect=Exception("API error")
        )
        mock_instance = MagicMock()
        mock_instance.aio = mock_aio
        MockClient.return_value = mock_instance

        summarizer = GeminiSummarizer(api_key="fake-key")
        result = await summarizer.summarize(content)

    assert result.is_raw_fallback is True
    assert result.summary == body[:5000]
    assert result.tokens_used == 0


async def test_summarize_safety_block_triggers_raw_fallback():
    """response.text = None (safety block) → is_raw_fallback=True."""
    content = make_content(body="Sensitive content body.")

    with patch(_PATCH_TARGET) as MockClient:
        mock_response = MagicMock()
        mock_response.text = None  # SDK returns None when blocked
        mock_response.usage_metadata = MagicMock()
        mock_response.usage_metadata.total_token_count = 0

        mock_aio = MagicMock()
        mock_aio.models.generate_content = AsyncMock(return_value=mock_response)
        mock_instance = MagicMock()
        mock_instance.aio = mock_aio
        MockClient.return_value = mock_instance

        summarizer = GeminiSummarizer(api_key="fake-key")
        result = await summarizer.summarize(content)

    assert result.is_raw_fallback is True


async def test_summarize_timeout_triggers_raw_fallback():
    """side_effect=TimeoutError → is_raw_fallback=True."""
    content = make_content()

    with patch(_PATCH_TARGET) as MockClient:
        mock_aio = MagicMock()
        mock_aio.models.generate_content = AsyncMock(
            side_effect=TimeoutError("Request timed out")
        )
        mock_instance = MagicMock()
        mock_instance.aio = mock_aio
        MockClient.return_value = mock_instance

        summarizer = GeminiSummarizer(api_key="fake-key")
        result = await summarizer.summarize(content)

    assert result.is_raw_fallback is True
    assert result.tokens_used == 0


async def test_summarize_malformed_json_triggers_partial_fallback():
    """Non-JSON text → is_raw_fallback=False (partial fallback), tags={}."""
    content = make_content()
    bad_text = "This is not JSON at all."

    with patch(_PATCH_TARGET) as MockClient:
        mock_instance, _ = make_mock_client(response_text=bad_text)
        MockClient.return_value = mock_instance

        summarizer = GeminiSummarizer(api_key="fake-key")
        result = await summarizer.summarize(content)

    # Malformed-JSON fallback: raw text is used as summary, tags={},
    # but is_raw_fallback stays False (distinct from API-error path).
    assert result.is_raw_fallback is False
    assert result.tags == {}
    assert result.summary == bad_text


# ── R009: Multi-dimensional tagging ──────────────────────────────────────────


def test_build_tag_list_all_axes():
    """All 6 axes are represented in the output tag list."""
    ai_tags = {
        "domain": ["AI"],
        "type": ["Research"],
        "difficulty": ["Advanced"],
        "keywords": ["transformer"],
    }
    tags = build_tag_list(SourceType.REDDIT, ai_tags)

    axes = {tag.split("/")[0] for tag in tags}
    assert "source" in axes
    assert "domain" in axes
    assert "type" in axes
    assert "difficulty" in axes
    assert "status" in axes
    assert "keyword" in axes


def test_build_tag_list_source_axis_uses_source_type():
    """Source tag is derived from SourceType.value, not from AI output."""
    ai_tags = {"domain": ["AI"], "type": ["Tutorial"]}
    tags = build_tag_list(SourceType.YOUTUBE, ai_tags)

    source_tags = [t for t in tags if t.startswith("source/")]
    assert len(source_tags) == 1
    assert source_tags[0] == f"source/{SourceType.YOUTUBE.value}"


def test_build_tag_list_empty_ai_tags():
    """Empty ai_tags dict → only source/X and status/Processed are emitted."""
    tags = build_tag_list(SourceType.GITHUB, {})

    assert f"source/{SourceType.GITHUB.value}" in tags
    assert "status/Processed" in tags
    # No domain, type, difficulty, or keyword tags should appear
    other = [t for t in tags if not t.startswith("source/") and t != "status/Processed"]
    assert other == []


def test_build_tag_list_multiple_domains():
    """Multiple domain values are all emitted with the domain/ prefix."""
    ai_tags = {
        "domain": ["AI", "ML", "Finance"],
        "type": [],
        "difficulty": [],
        "keywords": [],
    }
    tags = build_tag_list(SourceType.NEWSLETTER, ai_tags)

    domain_tags = [t for t in tags if t.startswith("domain/")]
    assert "domain/AI" in domain_tags
    assert "domain/ML" in domain_tags
    assert "domain/Finance" in domain_tags
    assert len(domain_tags) == 3


def test_build_tag_list_format_hierarchical():
    """Every tag in the output uses the axis/value hierarchical format."""
    ai_tags = {
        "domain": ["WebDev"],
        "type": ["Tutorial"],
        "difficulty": ["Beginner"],
        "keywords": ["flask", "api"],
    }
    tags = build_tag_list(SourceType.WEB, ai_tags)

    for tag in tags:
        assert "/" in tag, f"Tag '{tag}' is not hierarchical (missing '/')"
        axis, _, value = tag.partition("/")
        assert axis, f"Tag '{tag}' has empty axis"
        assert value, f"Tag '{tag}' has empty value"


def test_build_tag_list_string_difficulty_not_split():
    """Gemini may return difficulty as a bare string; must not iterate chars."""
    ai_tags = {
        "domain": ["AI"],
        "type": "Tutorial",
        "difficulty": "Intermediate",
        "keywords": ["test"],
    }
    tags = build_tag_list(SourceType.YOUTUBE, ai_tags)
    difficulty_tags = [t for t in tags if t.startswith("difficulty/")]
    assert difficulty_tags == ["difficulty/Intermediate"]
    type_tags = [t for t in tags if t.startswith("type/")]
    assert type_tags == ["type/Tutorial"]


# ── Construction ─────────────────────────────────────────────────────────────


def test_empty_api_key_raises():
    """GeminiSummarizer(api_key='') raises ValueError immediately."""
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiSummarizer(api_key="")


async def test_raw_fallback_summary_truncated_to_5000():
    """When API fails, result.summary == content.body[:5000] exactly."""
    long_body = "X" * 10_000
    content = make_content(body=long_body)

    with patch(_PATCH_TARGET) as MockClient:
        mock_aio = MagicMock()
        mock_aio.models.generate_content = AsyncMock(
            side_effect=Exception("simulated failure")
        )
        mock_instance = MagicMock()
        mock_instance.aio = mock_aio
        MockClient.return_value = mock_instance

        summarizer = GeminiSummarizer(api_key="fake-key")
        result = await summarizer.summarize(content)

    assert result.summary == long_body[:5000]
    assert len(result.summary) == 5000


def test_summarization_result_has_brief_summary():
    """SummarizationResult should have a brief_summary field."""
    result = SummarizationResult(
        summary="Detailed content here.",
        brief_summary="• Key point one\n• Key point two",
        tags={},
        one_line_summary="Takeaway.",
    )
    assert result.brief_summary == "• Key point one\n• Key point two"
    assert result.summary == "Detailed content here."


async def test_summarize_returns_both_brief_and_detailed():
    """Gemini JSON with brief_summary and detailed_summary populates both fields."""
    content = make_content()
    json_text = json.dumps({
        "brief_summary": "• Point one\n• Point two",
        "detailed_summary": "## Section A\n- Detail one\n- Detail two\n\n## Section B\n- Detail three",
        "tags": {
            "domain": ["AI"],
            "type": ["Research"],
            "difficulty": ["Intermediate"],
            "keywords": ["test"],
        },
        "one_line_summary": "A key takeaway.",
    })

    with patch(_PATCH_TARGET) as MockClient:
        mock_instance, _ = make_mock_client(response_text=json_text, token_count=200)
        MockClient.return_value = mock_instance

        summarizer = GeminiSummarizer(api_key="fake-key")
        result = await summarizer.summarize(content)

    assert result.brief_summary == "• Point one\n• Point two"
    assert result.summary == "## Section A\n- Detail one\n- Detail two\n\n## Section B\n- Detail three"
    assert result.one_line_summary == "A key takeaway."
    assert result.is_raw_fallback is False


async def test_summarize_legacy_single_summary_still_works():
    """Old-format JSON with only 'summary' field still populates result.summary."""
    content = make_content()
    json_text = json.dumps({
        "summary": "Legacy single summary.",
        "tags": {"domain": ["AI"], "type": ["Research"], "difficulty": ["Beginner"], "keywords": ["x"]},
        "one_line_summary": "Legacy takeaway.",
    })

    with patch(_PATCH_TARGET) as MockClient:
        mock_instance, _ = make_mock_client(response_text=json_text, token_count=100)
        MockClient.return_value = mock_instance

        summarizer = GeminiSummarizer(api_key="fake-key")
        result = await summarizer.summarize(content)

    assert result.summary == "Legacy single summary."
    assert result.brief_summary == ""
    assert result.one_line_summary == "Legacy takeaway."


async def test_raw_fallback_has_empty_brief_summary():
    """When API fails (R022), brief_summary should be empty string."""
    content = make_content(body="Some body text.")

    with patch(_PATCH_TARGET) as MockClient:
        mock_aio = MagicMock()
        mock_aio.models.generate_content = AsyncMock(
            side_effect=Exception("API error")
        )
        mock_instance = MagicMock()
        mock_instance.aio = mock_aio
        MockClient.return_value = mock_instance

        summarizer = GeminiSummarizer(api_key="fake-key")
        result = await summarizer.summarize(content)

    assert result.is_raw_fallback is True
    assert result.brief_summary == ""


async def test_empty_detailed_summary_not_replaced_by_raw():
    """Empty detailed_summary should remain empty, not fall back to raw text."""
    content = make_content()
    json_text = json.dumps({
        "brief_summary": "• Bullets here.",
        "detailed_summary": "",
        "tags": {"domain": ["AI"], "type": ["Research"], "difficulty": ["Beginner"], "keywords": ["x"]},
        "one_line_summary": "Takeaway.",
    })

    with patch(_PATCH_TARGET) as MockClient:
        mock_instance, _ = make_mock_client(response_text=json_text, token_count=100)
        MockClient.return_value = mock_instance

        summarizer = GeminiSummarizer(api_key="fake-key")
        result = await summarizer.summarize(content)

    assert result.summary == ""
    assert result.brief_summary == "• Bullets here."
