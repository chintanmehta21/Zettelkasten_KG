"""Tests for the per-day sliding-window rate limiter."""
from __future__ import annotations

import time

import pytest

from website.features.feedback.intake.rate_limit import (
    FeedbackRateLimiter,
    RateLimitExceeded,
    RateLimitKey,
)


def test_under_limit_allows() -> None:
    limiter = FeedbackRateLimiter(daily_cap=3, window_seconds=86400)
    key = RateLimitKey(scope="user", value="u-1")
    for _ in range(3):
        limiter.consume(key)
    # 3rd was the limit; 4th must fail
    with pytest.raises(RateLimitExceeded):
        limiter.consume(key)


def test_separate_keys_independent() -> None:
    limiter = FeedbackRateLimiter(daily_cap=1, window_seconds=86400)
    limiter.consume(RateLimitKey(scope="user", value="u-1"))
    limiter.consume(RateLimitKey(scope="user", value="u-2"))
    limiter.consume(RateLimitKey(scope="cookie", value="u-1"))  # different scope, OK


def test_window_expiry() -> None:
    """Past entries fall out of the window after window_seconds."""
    limiter = FeedbackRateLimiter(daily_cap=2, window_seconds=2)
    key = RateLimitKey(scope="ip", value="1.2.3.4")
    limiter.consume(key)
    limiter.consume(key)
    with pytest.raises(RateLimitExceeded):
        limiter.consume(key)
    time.sleep(2.2)
    # Window cleared — should allow again
    limiter.consume(key)


def test_rate_limit_exceeded_carries_retry_after() -> None:
    limiter = FeedbackRateLimiter(daily_cap=1, window_seconds=60)
    key = RateLimitKey(scope="user", value="u-1")
    limiter.consume(key)
    with pytest.raises(RateLimitExceeded) as excinfo:
        limiter.consume(key)
    assert excinfo.value.retry_after_seconds > 0
    assert excinfo.value.retry_after_seconds <= 60
