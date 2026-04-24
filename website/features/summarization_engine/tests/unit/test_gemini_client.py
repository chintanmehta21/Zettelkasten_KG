"""Tests for TieredGeminiClient."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.core.gemini_client import (
    GenerateResult,
    TieredGeminiClient,
)


@pytest.fixture
def fake_pool():
    pool = MagicMock()
    pool.generate_content = AsyncMock()
    return pool


@pytest.mark.asyncio
async def test_generate_pro_tier_calls_pool(fake_pool):
    response = MagicMock()
    response.text = '{"ok": true}'
    response.usage_metadata = MagicMock(
        prompt_token_count=100,
        candidates_token_count=50,
    )
    fake_pool.generate_content.return_value = (response, "gemini-2.5-pro", 0)

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
    response = MagicMock()
    response.text = "x"
    response.usage_metadata = MagicMock(prompt_token_count=10, candidates_token_count=5)
    fake_pool.generate_content.return_value = (response, "gemini-2.5-flash", 0)

    client = TieredGeminiClient(fake_pool, load_config())
    await client.generate("hi", tier="flash")

    _, kwargs = fake_pool.generate_content.call_args
    assert kwargs["starting_model"] == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_generate_passes_response_schema_for_structured(fake_pool):
    from pydantic import BaseModel

    class Out(BaseModel):
        value: str

    response = MagicMock()
    response.text = '{"value": "x"}'
    response.usage_metadata = MagicMock(prompt_token_count=10, candidates_token_count=5)
    fake_pool.generate_content.return_value = (response, "gemini-2.5-flash", 0)

    client = TieredGeminiClient(fake_pool, load_config())
    await client.generate("x", tier="flash", response_schema=Out)

    _, kwargs = fake_pool.generate_content.call_args
    assert kwargs["config"]["response_mime_type"] == "application/json"
    # response_schema is NOT passed to Gemini (additionalProperties unsupported)
    assert "response_schema" not in kwargs["config"]


@pytest.mark.asyncio
async def test_generate_multimodal_passes_contents_to_pool(fake_pool):
    response = MagicMock()
    response.text = "TITLE: Test Video\nCHANNEL: TestCh\nCONTENT:\nSome content"
    response.usage_metadata = MagicMock(
        prompt_token_count=200,
        candidates_token_count=80,
    )
    fake_pool.generate_content.return_value = (response, "gemini-2.5-flash", 1)

    client = TieredGeminiClient(fake_pool, load_config())
    # Simulate multimodal: a mock Part + text prompt
    mock_part = MagicMock()
    result = await client.generate_multimodal(
        [mock_part, "Analyze this video"],
        label="yt-test",
    )

    assert isinstance(result, GenerateResult)
    assert result.text == "TITLE: Test Video\nCHANNEL: TestCh\nCONTENT:\nSome content"
    assert result.model_used == "gemini-2.5-flash"
    assert result.input_tokens == 200
    assert result.output_tokens == 80
    assert result.key_index == 1

    _, kwargs = fake_pool.generate_content.call_args
    assert kwargs["contents"] == [mock_part, "Analyze this video"]
    assert kwargs["label"] == "yt-test"
    assert kwargs["starting_model"] == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_generate_multimodal_custom_starting_model(fake_pool):
    response = MagicMock()
    response.text = "ok"
    response.usage_metadata = None
    fake_pool.generate_content.return_value = (response, "gemini-2.5-pro", 0)

    client = TieredGeminiClient(fake_pool, load_config())
    result = await client.generate_multimodal(
        ["text content"],
        starting_model="gemini-2.5-pro",
    )

    assert result.model_used == "gemini-2.5-pro"
    assert result.input_tokens == 0  # usage_metadata is None
    _, kwargs = fake_pool.generate_content.call_args
    assert kwargs["starting_model"] == "gemini-2.5-pro"


# ── telemetry / model_used + fallback_reason plumbing ────────────────────────


def _fake_pool_success(
    *,
    response_text: str = "x",
    model_returned: str = "gemini-2.5-flash",
    input_tokens: int = 10,
    output_tokens: int = 5,
    sink_entry: dict | None = None,
):
    """Build an AsyncMock pool whose ``generate_content`` returns a response
    and optionally populates ``telemetry_sink`` with one attempt entry.
    """

    async def _call(*args, **kwargs):
        sink = kwargs.get("telemetry_sink")
        if sink is not None and sink_entry is not None:
            sink.append(dict(sink_entry))
        response = MagicMock()
        response.text = response_text
        response.usage_metadata = MagicMock(
            prompt_token_count=input_tokens,
            candidates_token_count=output_tokens,
        )
        return response, model_returned, 0

    pool = MagicMock()
    pool.generate_content = AsyncMock(side_effect=_call)
    return pool


@pytest.mark.asyncio
async def test_generate_surfaces_fallback_reason_from_sink():
    """When the pool reports a fallback attempt, ``fallback_reason`` surfaces."""
    pool = _fake_pool_success(
        sink_entry={
            "label": "engine-v2-flash",
            "model_used": "gemini-2.5-flash-lite",
            "starting_model": "gemini-2.5-flash",
            "key_index": 0,
            "fallback_reason": "gemini-2.5-flash-rate-limited",
            "failed_attempts": [
                {"model": "gemini-2.5-flash", "key_index": 0, "reason": "rate-limited"}
            ],
        },
        model_returned="gemini-2.5-flash-lite",
    )

    client = TieredGeminiClient(pool, load_config())
    result = await client.generate("x", tier="flash", role="summarizer")

    assert result.model_used == "gemini-2.5-flash-lite"
    assert result.fallback_reason == "gemini-2.5-flash-rate-limited"
    assert result.starting_model == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_generate_primary_path_has_no_fallback_reason():
    pool = _fake_pool_success(
        sink_entry={
            "label": "engine-v2-flash",
            "model_used": "gemini-2.5-flash",
            "starting_model": "gemini-2.5-flash",
            "key_index": 0,
            "fallback_reason": None,
            "failed_attempts": [],
        }
    )

    client = TieredGeminiClient(pool, load_config())
    result = await client.generate("x", tier="flash", role="summarizer")

    assert result.model_used == "gemini-2.5-flash"
    assert result.fallback_reason is None


@pytest.mark.asyncio
async def test_enable_and_drain_call_journal_captures_role_and_tokens():
    """The client-level journal is how phases.py builds telemetry.json."""
    pool = _fake_pool_success(
        sink_entry={
            "label": "engine-v2-flash",
            "model_used": "gemini-2.5-flash",
            "starting_model": "gemini-2.5-flash",
            "key_index": 0,
            "fallback_reason": None,
            "failed_attempts": [],
        },
        input_tokens=42,
        output_tokens=13,
    )

    client = TieredGeminiClient(pool, load_config())
    client.enable_call_journal()

    await client.generate("x", tier="flash", role="summarizer")
    await client.generate("y", tier="flash", role="rubric_evaluator")

    journal = client.drain_call_journal()
    assert len(journal) == 2
    # Roles propagated from caller into the journal
    assert [e["role"] for e in journal] == ["summarizer", "rubric_evaluator"]
    # Token counts propagated from usage_metadata into the journal entry
    for entry in journal:
        assert entry["input_tokens"] == 42
        assert entry["output_tokens"] == 13

    # drain is consuming — second drain returns []
    assert client.drain_call_journal() == []


@pytest.mark.asyncio
async def test_key_rotation_429_surfaces_model_downgrade():
    """Simulate the key pool rotating keys after 429 then downgrading model."""
    pool = _fake_pool_success(
        sink_entry={
            "label": "engine-v2-flash",
            "model_used": "gemini-2.5-flash-lite",
            "starting_model": "gemini-2.5-flash",
            "key_index": 3,
            "fallback_reason": "gemini-2.5-flash-rate-limited",
            "failed_attempts": [
                {"model": "gemini-2.5-flash", "key_index": 0, "reason": "rate-limited"},
                {"model": "gemini-2.5-flash", "key_index": 1, "reason": "rate-limited"},
            ],
        },
        model_returned="gemini-2.5-flash-lite",
    )

    client = TieredGeminiClient(pool, load_config())
    client.enable_call_journal()
    result = await client.generate("x", tier="flash", role="summarizer")

    assert result.model_used == "gemini-2.5-flash-lite"
    assert result.fallback_reason == "gemini-2.5-flash-rate-limited"

    journal = client.drain_call_journal()
    assert len(journal) == 1
    entry = journal[0]
    assert entry["model_used"] == "gemini-2.5-flash-lite"
    assert entry["starting_model"] == "gemini-2.5-flash"
    # Failed attempts chain is preserved for post-hoc analysis
    assert len(entry["failed_attempts"]) == 2
