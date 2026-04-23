from __future__ import annotations

import logging

import pytest

from website.core import settings as settings_module
from website.core.settings import Settings, get_settings, validate_reddit_credentials


def test_github_enabled_requires_both_token_and_repo() -> None:
    enabled = Settings(github_token=" token ", github_repo=" repo ")
    disabled_without_repo = Settings(github_token=" token ", github_repo="")
    disabled_without_token = Settings(github_token="", github_repo=" repo ")

    assert enabled.github_enabled is True
    assert disabled_without_repo.github_enabled is False
    assert disabled_without_token.github_enabled is False


def test_settings_exposes_website_fields() -> None:
    settings = Settings()

    assert "substack.com" in settings.newsletter_domains
    assert isinstance(settings.rag_chunks_enabled, bool)


def test_get_settings_returns_singleton() -> None:
    get_settings.cache_clear()

    first = get_settings()
    second = get_settings()

    assert first is second
    assert isinstance(first, Settings)


# ─── Reddit OAuth credential validation ──────────────────────────────────────
# The warning is gated on webhook_mode (prod) and uses a module-level latch
# so it fires exactly once per process. Each test resets the latch first.


@pytest.fixture(autouse=False)
def reset_reddit_warning_latch() -> None:
    settings_module._reddit_warning_emitted = False
    yield
    settings_module._reddit_warning_emitted = False


def test_reddit_oauth_configured_true_when_both_present() -> None:
    s = Settings(
        reddit_client_id="sample-id",
        reddit_client_secret="sample-secret",
    )
    assert s.reddit_oauth_configured is True


def test_reddit_oauth_configured_false_when_secret_missing() -> None:
    s = Settings(reddit_client_id="sample-id", reddit_client_secret="")
    assert s.reddit_oauth_configured is False


def test_reddit_oauth_configured_false_when_id_missing() -> None:
    s = Settings(reddit_client_id="", reddit_client_secret="sample-secret")
    assert s.reddit_oauth_configured is False


def test_reddit_oauth_configured_false_when_whitespace_only() -> None:
    s = Settings(reddit_client_id="   ", reddit_client_secret="   ")
    assert s.reddit_oauth_configured is False


def test_warning_emitted_once_in_production_mode_with_missing_creds(
    caplog: pytest.LogCaptureFixture,
    reset_reddit_warning_latch: None,
) -> None:
    s = Settings(
        webhook_mode=True,
        reddit_client_id="",
        reddit_client_secret="",
    )
    with caplog.at_level(logging.WARNING, logger="website.core.settings"):
        validate_reddit_credentials(s)
        validate_reddit_credentials(s)
        validate_reddit_credentials(s)

    reddit_warnings = [
        rec for rec in caplog.records
        if rec.levelno == logging.WARNING
        and "Reddit OAuth credentials missing" in rec.getMessage()
    ]
    assert len(reddit_warnings) == 1
    msg = reddit_warnings[0].getMessage()
    assert "REDDIT_CLIENT_ID" in msg
    assert "REDDIT_CLIENT_SECRET" in msg
    assert "public JSON fallback" in msg


def test_warning_not_emitted_in_dev_mode_with_missing_creds(
    caplog: pytest.LogCaptureFixture,
    reset_reddit_warning_latch: None,
) -> None:
    s = Settings(
        webhook_mode=False,
        reddit_client_id="",
        reddit_client_secret="",
    )
    with caplog.at_level(logging.WARNING, logger="website.core.settings"):
        validate_reddit_credentials(s)

    reddit_warnings = [
        rec for rec in caplog.records
        if "Reddit OAuth credentials missing" in rec.getMessage()
    ]
    assert reddit_warnings == []


def test_warning_not_emitted_when_both_creds_present_in_production(
    caplog: pytest.LogCaptureFixture,
    reset_reddit_warning_latch: None,
) -> None:
    s = Settings(
        webhook_mode=True,
        reddit_client_id="sample-id",
        reddit_client_secret="sample-secret",
    )
    with caplog.at_level(logging.WARNING, logger="website.core.settings"):
        validate_reddit_credentials(s)

    reddit_warnings = [
        rec for rec in caplog.records
        if "Reddit OAuth credentials missing" in rec.getMessage()
    ]
    assert reddit_warnings == []
