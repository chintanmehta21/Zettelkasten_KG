"""Feature-local Pydantic settings — reads env directly, does not modify
website/core/settings.py per the strict-containment rule.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class FeedbackSettings(BaseSettings):
    """Env-loaded config for the feedback module.

    Field names map to env vars via pydantic-settings's default behavior
    (UPPER_SNAKE_CASE). Values default to empty strings / false, meaning
    the feature degrades gracefully (route returns 503) if creds are missing
    rather than failing app boot.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    slack_bot_token_feedback: str = ""
    slack_channel_feedback: str = ""
    secret_feedback_cookie: str = ""
    feedback_require_turnstile: bool = False


@lru_cache(maxsize=1)
def get_feedback_settings() -> FeedbackSettings:
    """Return the cached singleton. Tests must call .cache_clear() between cases."""
    return FeedbackSettings()
