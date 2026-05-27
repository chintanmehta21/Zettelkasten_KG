"""FastAPI dependencies for the feedback module.

Kept narrow: settings access, rate-limit gating, cookie issuance helpers.
"""
from __future__ import annotations

from functools import lru_cache

from fastapi import HTTPException

from website.features.feedback.intake.rate_limit import (
    FeedbackRateLimiter,
    RateLimitExceeded,
    RateLimitKey,
)

DEFAULT_DAILY_CAP = 10
DEFAULT_WINDOW_SECONDS = 24 * 60 * 60  # 1 day


@lru_cache(maxsize=1)
def get_feedback_rate_limiter() -> FeedbackRateLimiter:
    return FeedbackRateLimiter(
        daily_cap=DEFAULT_DAILY_CAP,
        window_seconds=DEFAULT_WINDOW_SECONDS,
    )


def enforce_rate_limit_or_429(
    *,
    limiter: FeedbackRateLimiter,
    user_id: str | None,
    cookie_value: str | None,
    client_ip: str | None,
) -> None:
    """Apply the per-user OR (per-cookie + per-IP) daily budget.

    Authenticated requests are checked against `user_id` only.
    Anonymous requests are checked against BOTH the signed cookie value and
    the client IP — whichever overflows first triggers 429.
    """
    keys: list[RateLimitKey] = []
    if user_id:
        keys.append(RateLimitKey(scope="user", value=user_id))
    else:
        if cookie_value:
            keys.append(RateLimitKey(scope="cookie", value=cookie_value))
        if client_ip:
            keys.append(RateLimitKey(scope="ip", value=client_ip))

    for key in keys:
        try:
            limiter.consume(key)
        except RateLimitExceeded as exc:
            raise HTTPException(
                status_code=429,
                detail="Daily feedback limit reached. Please try again tomorrow.",
                headers={"Retry-After": str(exc.retry_after_seconds)},
            )
