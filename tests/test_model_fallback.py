"""Tests for the model fallback chain and rate-limit cooldown logic.

Covers:
  - _is_rate_limited detection (ClientError 429, string patterns, negatives)
  - _build_model_chain ordering and cooldown filtering
  - _generate_with_fallback cascade on 429, non-429 raise, all-exhausted
  - Per-instance cooldown memory (skip exhausted models on subsequent calls)
  - Cooldown expiry (models return to the chain after TTL)
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from google.genai.errors import ClientError

from telegram_bot.pipeline.summarizer import (
    GeminiSummarizer,
    _MODEL_FALLBACK_CHAIN,
    _RATE_LIMIT_COOLDOWN_SECS,
    _is_rate_limited,
)

_PATCH_TARGET = "telegram_bot.pipeline.summarizer.genai.Client"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_summarizer(model_name: str = "gemini-2.5-flash") -> GeminiSummarizer:
    """Create a GeminiSummarizer with a mocked genai.Client."""
    with patch(_PATCH_TARGET):
        return GeminiSummarizer(api_key="fake-key", model_name=model_name)


def _make_429_error(msg: str = "RESOURCE_EXHAUSTED") -> ClientError:
    """Build a ClientError that looks like a Gemini 429."""
    return ClientError(
        code=429,
        response_json={"error": {"message": msg, "status": "RESOURCE_EXHAUSTED"}},
    )


def _make_client_error(code: int, msg: str = "Bad Request") -> ClientError:
    """Build a ClientError with an arbitrary status code."""
    return ClientError(
        code=code,
        response_json={"error": {"message": msg}},
    )


# ── _is_rate_limited ─────────────────────────────────────────────────────────


def test_is_rate_limited_client_error_429():
    """ClientError with code=429 is detected as rate-limited."""
    assert _is_rate_limited(_make_429_error()) is True


def test_is_rate_limited_string_pattern():
    """Exception whose str contains '429' and 'RESOURCE_EXHAUSTED' matches."""
    exc = Exception("429 RESOURCE_EXHAUSTED: too many requests")
    assert _is_rate_limited(exc) is True


def test_is_rate_limited_non_429_client_error():
    """ClientError with non-429 code is NOT rate-limited."""
    exc = _make_client_error(400, "Bad Request")
    assert _is_rate_limited(exc) is False


def test_is_rate_limited_generic_exception():
    """Plain Exception without 429/RESOURCE_EXHAUSTED is NOT rate-limited."""
    assert _is_rate_limited(Exception("API error")) is False


def test_is_rate_limited_partial_string_no_match():
    """'429' alone without 'RESOURCE_EXHAUSTED' is not enough."""
    assert _is_rate_limited(Exception("429 unknown")) is False


# ── _build_model_chain ───────────────────────────────────────────────────────


def test_build_chain_default_order():
    """Default chain starts with configured model, then fallback chain order."""
    s = _make_summarizer("gemini-2.5-flash")
    chain = s._build_model_chain()
    assert chain == _MODEL_FALLBACK_CHAIN


def test_build_chain_custom_primary():
    """Custom primary model appears first, followed by remaining chain models."""
    s = _make_summarizer("gemini-2.0-flash")
    chain = s._build_model_chain()
    assert chain[0] == "gemini-2.0-flash"
    assert "gemini-2.5-flash" in chain
    assert "gemini-2.5-flash-lite" in chain


def test_build_chain_custom_model_not_in_fallback():
    """A model outside the fallback chain appears first, then the full chain."""
    s = _make_summarizer("gemini-pro")
    chain = s._build_model_chain()
    assert chain[0] == "gemini-pro"
    for m in _MODEL_FALLBACK_CHAIN:
        assert m in chain


def test_build_chain_skips_cooled_down_models():
    """Models on cooldown are excluded from the chain."""
    s = _make_summarizer()
    s._cooldowns["gemini-2.5-flash"] = time.monotonic() + 300
    chain = s._build_model_chain()
    assert "gemini-2.5-flash" not in chain
    assert "gemini-2.0-flash" in chain


def test_build_chain_expired_cooldown_restored():
    """Models whose cooldown has expired are included again."""
    s = _make_summarizer()
    s._cooldowns["gemini-2.5-flash"] = time.monotonic() - 1  # already expired
    chain = s._build_model_chain()
    assert "gemini-2.5-flash" in chain


def test_build_chain_all_on_cooldown_returns_full():
    """If every model is on cooldown, the full chain is returned."""
    s = _make_summarizer()
    far_future = time.monotonic() + 9999
    for m in _MODEL_FALLBACK_CHAIN:
        s._cooldowns[m] = far_future
    chain = s._build_model_chain()
    assert chain == _MODEL_FALLBACK_CHAIN


# ── _generate_with_fallback ──────────────────────────────────────────────────


async def test_fallback_succeeds_on_first_model():
    """First model succeeds → returns response and model name, no cascade."""
    s = _make_summarizer()
    mock_response = MagicMock()

    s._aio_models.generate_content = AsyncMock(return_value=mock_response)

    response, model_used = await s._generate_with_fallback("test prompt")
    assert response is mock_response
    assert model_used == "gemini-2.5-flash"
    assert s._aio_models.generate_content.call_count == 1


async def test_fallback_cascades_on_429():
    """429 on first model → tries second model → succeeds."""
    s = _make_summarizer()
    mock_response = MagicMock()

    s._aio_models.generate_content = AsyncMock(
        side_effect=[_make_429_error(), mock_response]
    )

    response, model_used = await s._generate_with_fallback("test prompt")
    assert response is mock_response
    assert model_used == "gemini-2.0-flash"
    assert s._aio_models.generate_content.call_count == 2


async def test_fallback_cascades_through_all_models():
    """429 on first two models → third succeeds."""
    s = _make_summarizer()
    mock_response = MagicMock()

    s._aio_models.generate_content = AsyncMock(
        side_effect=[_make_429_error(), _make_429_error(), mock_response]
    )

    response, model_used = await s._generate_with_fallback("test prompt")
    assert response is mock_response
    assert model_used == "gemini-2.5-flash-lite"
    assert s._aio_models.generate_content.call_count == 3


async def test_fallback_all_models_429_raises_last():
    """429 on every model → raises the last 429 exception."""
    s = _make_summarizer()

    errs = [_make_429_error(f"model-{i}") for i in range(3)]
    s._aio_models.generate_content = AsyncMock(side_effect=errs)

    with pytest.raises(ClientError, match="model-2"):
        await s._generate_with_fallback("test prompt")
    assert s._aio_models.generate_content.call_count == 3


async def test_fallback_non_429_raises_immediately():
    """Non-rate-limit error on first model → raises immediately, no cascade."""
    s = _make_summarizer()
    auth_error = Exception("403 Permission Denied")

    s._aio_models.generate_content = AsyncMock(side_effect=auth_error)

    with pytest.raises(Exception, match="403 Permission Denied"):
        await s._generate_with_fallback("test prompt")
    # Only one call — did not try the next model
    assert s._aio_models.generate_content.call_count == 1


async def test_fallback_records_cooldown_on_429():
    """After a 429, the model is placed on cooldown for subsequent calls."""
    s = _make_summarizer()
    mock_response = MagicMock()

    s._aio_models.generate_content = AsyncMock(
        side_effect=[_make_429_error(), mock_response]
    )

    await s._generate_with_fallback("test prompt")

    # gemini-2.5-flash should now be on cooldown
    assert "gemini-2.5-flash" in s._cooldowns
    assert s._cooldowns["gemini-2.5-flash"] > time.monotonic()


async def test_cooldown_skips_model_on_next_call():
    """Second call skips the cooled-down model entirely."""
    s = _make_summarizer()
    mock_response_1 = MagicMock(name="resp1")
    mock_response_2 = MagicMock(name="resp2")

    # First call: 429 on model 1, success on model 2
    s._aio_models.generate_content = AsyncMock(
        side_effect=[_make_429_error(), mock_response_1]
    )
    _, model1 = await s._generate_with_fallback("call 1")
    assert model1 == "gemini-2.0-flash"

    # Second call: model 1 should be skipped (on cooldown)
    s._aio_models.generate_content = AsyncMock(return_value=mock_response_2)
    _, model2 = await s._generate_with_fallback("call 2")
    assert model2 == "gemini-2.0-flash"  # Starts from model 2 directly

    # Only 1 API call on second invocation (no wasted retry on model 1)
    assert s._aio_models.generate_content.call_count == 1


async def test_cooldown_expires_model_returns():
    """After cooldown expires, the model is tried again."""
    s = _make_summarizer()
    mock_response = MagicMock()

    # Simulate an expired cooldown
    s._cooldowns["gemini-2.5-flash"] = time.monotonic() - 1

    s._aio_models.generate_content = AsyncMock(return_value=mock_response)
    _, model_used = await s._generate_with_fallback("test prompt")

    # Expired cooldown was purged — primary model tried first again
    assert model_used == "gemini-2.5-flash"


async def test_fallback_passes_correct_model_names_to_api():
    """Each attempt in the cascade passes the correct model name."""
    s = _make_summarizer()
    mock_response = MagicMock()
    calls = []

    async def capture_call(**kwargs):
        calls.append(kwargs.get("model"))
        if len(calls) < 3:
            raise _make_429_error()
        return mock_response

    s._aio_models.generate_content = capture_call

    await s._generate_with_fallback("test")
    assert calls == [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.5-flash-lite",
    ]
