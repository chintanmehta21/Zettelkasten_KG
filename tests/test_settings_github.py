"""Tests for GitHub-related settings fields."""

from telegram_bot.config.settings import Settings


class TestGitHubSettings:
    def test_github_fields_default_empty(self):
        """GitHub fields default to empty strings / 'main'."""
        s = Settings(
            telegram_bot_token="test-token",
            allowed_chat_id=12345,
        )
        assert s.github_token == ""
        assert s.github_repo == ""
        assert s.github_branch == "main"

    def test_github_fields_from_constructor(self):
        """GitHub fields can be set via constructor."""
        s = Settings(
            telegram_bot_token="test-token",
            allowed_chat_id=12345,
            github_token="ghp_abc123",
            github_repo="user/repo",
            github_branch="notes",
        )
        assert s.github_token == "ghp_abc123"
        assert s.github_repo == "user/repo"
        assert s.github_branch == "notes"

    def test_github_enabled_property(self):
        """github_enabled is True only when both token and repo are set."""
        s_disabled = Settings(
            telegram_bot_token="test-token",
            allowed_chat_id=12345,
        )
        assert s_disabled.github_enabled is False

        s_enabled = Settings(
            telegram_bot_token="test-token",
            allowed_chat_id=12345,
            github_token="ghp_abc123",
            github_repo="user/repo",
        )
        assert s_enabled.github_enabled is True

        s_partial = Settings(
            telegram_bot_token="test-token",
            allowed_chat_id=12345,
            github_token="ghp_abc123",
            github_repo="",
        )
        assert s_partial.github_enabled is False
