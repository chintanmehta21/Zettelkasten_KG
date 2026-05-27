"""Tests for FastAPI dependencies (rate-limit gate, cookie issuer, settings)."""
from __future__ import annotations

import pytest

from website.features.feedback.api.deps import (
    DEFAULT_DAILY_CAP,
    enforce_rate_limit_or_429,
    get_feedback_rate_limiter,
)
from website.features.feedback.intake.rate_limit import (
    FeedbackRateLimiter,
)


@pytest.fixture(autouse=True)
def _reset_limiter_cache():
    # Defensive: lru_cache singleton leaks state across tests if not cleared.
    get_feedback_rate_limiter.cache_clear()
    yield
    get_feedback_rate_limiter.cache_clear()


def test_default_cap_is_ten() -> None:
    assert DEFAULT_DAILY_CAP == 10


def test_rate_limiter_singleton_is_cached() -> None:
    a = get_feedback_rate_limiter()
    b = get_feedback_rate_limiter()
    assert a is b


def test_enforce_rate_limit_returns_when_under_cap() -> None:
    limiter = FeedbackRateLimiter(daily_cap=2, window_seconds=60)
    # Both consume calls happen inside enforce; should not raise on first two.
    enforce_rate_limit_or_429(
        limiter=limiter,
        user_id="u-1", cookie_value=None, client_ip="1.2.3.4",
    )
    enforce_rate_limit_or_429(
        limiter=limiter,
        user_id="u-1", cookie_value=None, client_ip="1.2.3.4",
    )


def test_enforce_rate_limit_raises_http_429_when_over_cap() -> None:
    from fastapi import HTTPException
    limiter = FeedbackRateLimiter(daily_cap=1, window_seconds=60)
    enforce_rate_limit_or_429(
        limiter=limiter,
        user_id="u-1", cookie_value=None, client_ip="1.2.3.4",
    )
    with pytest.raises(HTTPException) as excinfo:
        enforce_rate_limit_or_429(
            limiter=limiter,
            user_id="u-1", cookie_value=None, client_ip="1.2.3.4",
        )
    assert excinfo.value.status_code == 429
    assert "Retry-After" in excinfo.value.headers
