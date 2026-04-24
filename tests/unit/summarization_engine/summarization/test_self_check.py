import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from website.features.summarization_engine.core.config import EngineConfig
from website.features.summarization_engine.summarization.common import self_check as sc_mod
from website.features.summarization_engine.summarization.common.self_check import (
    InvertedFactScoreSelfCheck,
)


@pytest.fixture(autouse=True)
def _skip_sleep(monkeypatch):
    """Collapse retry sleeps so tests finish fast but still exercise the path."""
    slept: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(sc_mod.asyncio, "sleep", _fake_sleep)
    return slept


def _gen_ok(text: str = '{"missing": []}'):
    return SimpleNamespace(text=text, input_tokens=10, output_tokens=5)


@pytest.mark.asyncio
async def test_self_check_degrades_on_generation_failure(_skip_sleep):
    """Legacy test: a persistent TimeoutError still fails open after retries."""

    class Client:
        generate = AsyncMock(side_effect=TimeoutError("upstream timeout"))

    result = await InvertedFactScoreSelfCheck(Client(), EngineConfig()).check(
        "source",
        "summary",
    )

    assert result.missing == []
    assert result.pro_tokens == 0
    # Two retries were attempted (3 total calls) before giving up.
    assert Client.generate.await_count == 3
    assert _skip_sleep == [2.0, 5.0]


@pytest.mark.asyncio
async def test_self_check_504_then_success(_skip_sleep, caplog):
    """504 on first call, success on second: succeeds, 1 retry logged."""

    class FakeGAPIError(Exception):
        """Stand-in for a transient Gemini 504 before google-api-core classes."""

    # Use a message that looks like a 504 so the fallback pattern matches even
    # if google.api_core.exceptions.DeadlineExceeded is not matched by isinstance.
    transient = FakeGAPIError("504 Deadline exceeded upstream")

    class Client:
        generate = AsyncMock(
            side_effect=[transient, _gen_ok('{"missing": []}')]
        )

    with caplog.at_level(logging.INFO, logger=sc_mod.logger.name):
        result = await InvertedFactScoreSelfCheck(Client(), EngineConfig()).check(
            "source", "summary"
        )

    assert Client.generate.await_count == 2
    assert result.pro_tokens == 15
    assert _skip_sleep == [2.0]  # exactly one retry slept
    retry_logs = [r for r in caplog.records if "self_check.retry" in r.message]
    assert len(retry_logs) == 1


@pytest.mark.asyncio
async def test_self_check_504_three_times_fails_open(_skip_sleep):
    """504 x 3: falls open after 2 retries, summary still completes."""

    class FakeGAPIError(Exception):
        pass

    transient = FakeGAPIError("504 Deadline exceeded")

    class Client:
        generate = AsyncMock(side_effect=[transient, transient, transient])

    result = await InvertedFactScoreSelfCheck(Client(), EngineConfig()).check(
        "source", "summary"
    )

    assert result.missing == []
    assert result.pro_tokens == 0
    assert Client.generate.await_count == 3  # initial + 2 retries
    assert _skip_sleep == [2.0, 5.0]


@pytest.mark.asyncio
async def test_self_check_400_no_retry(_skip_sleep, caplog):
    """400 / invalid-argument: no retry, fails open immediately."""
    try:
        from google.api_core.exceptions import InvalidArgument
    except Exception:  # pragma: no cover
        pytest.skip("google-api-core not available")

    bad = InvalidArgument("bad input")

    class Client:
        generate = AsyncMock(side_effect=bad)

    with caplog.at_level(logging.INFO, logger=sc_mod.logger.name):
        result = await InvertedFactScoreSelfCheck(Client(), EngineConfig()).check(
            "source", "summary"
        )

    assert result.missing == []
    assert Client.generate.await_count == 1  # no retry
    assert _skip_sleep == []  # never slept
    fail_logs = [r for r in caplog.records if "self_check.fail_open" in r.message]
    assert any(fail_logs)


@pytest.mark.asyncio
async def test_self_check_timeout_then_success(_skip_sleep):
    """TimeoutError on first, success on second: succeeds with 1 retry."""

    class Client:
        generate = AsyncMock(
            side_effect=[TimeoutError("timeout"), _gen_ok('{"missing": []}')]
        )

    result = await InvertedFactScoreSelfCheck(Client(), EngineConfig()).check(
        "source", "summary"
    )

    assert result.pro_tokens == 15
    assert Client.generate.await_count == 2
    assert _skip_sleep == [2.0]


@pytest.mark.asyncio
async def test_self_check_uses_async_sleep(monkeypatch):
    """Regression guard: retries must use asyncio.sleep, not time.sleep."""
    import time as _time

    calls = {"time_sleep": 0, "async_sleep": 0}

    def _bad_sleep(_):
        calls["time_sleep"] += 1

    async def _fake_asleep(seconds: float) -> None:  # noqa: ARG001
        calls["async_sleep"] += 1

    monkeypatch.setattr(_time, "sleep", _bad_sleep)
    monkeypatch.setattr(sc_mod.asyncio, "sleep", _fake_asleep)

    class Client:
        generate = AsyncMock(
            side_effect=[TimeoutError("t"), _gen_ok('{"missing": []}')]
        )

    await InvertedFactScoreSelfCheck(Client(), EngineConfig()).check(
        "source", "summary"
    )

    assert calls["async_sleep"] == 1
    assert calls["time_sleep"] == 0
