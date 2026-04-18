from __future__ import annotations

from website.core.settings import Settings, get_settings


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
