"""Tests for feature-local FeedbackSettings."""
from __future__ import annotations

import pytest
from collections.abc import Iterator

from website.features.feedback.core.settings import (
    FeedbackSettings,
    get_feedback_settings,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    get_feedback_settings.cache_clear()
    yield
    get_feedback_settings.cache_clear()


def test_defaults_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "SLACK_BOT_TOKEN_FEEDBACK",
        "SLACK_CHANNEL_FEEDBACK",
        "SECRET_FEEDBACK_COOKIE",
        "FEEDBACK_REQUIRE_TURNSTILE",
    ):
        monkeypatch.delenv(var, raising=False)
    s = FeedbackSettings(_env_file=None)
    assert s.slack_bot_token_feedback == ""
    assert s.slack_channel_feedback == ""
    assert s.secret_feedback_cookie == ""
    assert s.feedback_require_turnstile is False


def test_loads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLACK_BOT_TOKEN_FEEDBACK", "xoxb-abc")
    monkeypatch.setenv("SLACK_CHANNEL_FEEDBACK", "C09ABC")
    monkeypatch.setenv("SECRET_FEEDBACK_COOKIE", "deadbeef" * 8)
    monkeypatch.setenv("FEEDBACK_REQUIRE_TURNSTILE", "true")
    s = FeedbackSettings()
    assert s.slack_bot_token_feedback == "xoxb-abc"
    assert s.slack_channel_feedback == "C09ABC"
    assert s.secret_feedback_cookie == "deadbeef" * 8
    assert s.feedback_require_turnstile is True


def test_get_feedback_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLACK_BOT_TOKEN_FEEDBACK", "first")
    a = get_feedback_settings()
    monkeypatch.setenv("SLACK_BOT_TOKEN_FEEDBACK", "second")
    b = get_feedback_settings()
    assert a is b  # cached — second env value not seen
