"""Tests for zettelkasten_bot.main — entry point.

Strategy
--------
- Patch ``Application`` at ``zettelkasten_bot.main.Application`` to avoid
  real network connections and PTB initialisation.
- Patch ``get_settings`` at ``zettelkasten_bot.main.get_settings`` (import
  site) so the lru_cache is bypassed and env-var validation is skipped.
- Patch ``logging.basicConfig`` where it matters to verify it is called.
- Call ``_validate_settings`` directly for the webhook-URL-guard tests.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, call, patch

import pytest
from telegram import Update

from zettelkasten_bot.config.settings import Settings, _validate_settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_polling_settings(**overrides) -> Settings:
    """Return a Settings instance suitable for polling-mode tests."""
    return Settings(
        telegram_bot_token="test-token",
        allowed_chat_id=12345,
        webhook_mode=False,
        webhook_url="",
        webhook_port=8443,
        webhook_secret="",
        **overrides,
    )


def _make_webhook_settings(**overrides) -> Settings:
    """Return a Settings instance suitable for webhook-mode tests."""
    return Settings(
        telegram_bot_token="test-token",
        allowed_chat_id=12345,
        webhook_mode=True,
        webhook_url="https://example.com/hook",
        webhook_port=8443,
        webhook_secret="secret123",
        **overrides,
    )


def _wire_app_mock() -> tuple[MagicMock, MagicMock]:
    """Return ``(MockApp_class, mock_app_instance)`` with the builder chain wired."""
    mock_app = MagicMock()
    MockApp = MagicMock()
    MockApp.builder.return_value.token.return_value.build.return_value = mock_app
    return MockApp, mock_app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPollingMode:
    def test_polling_mode_calls_run_polling(self) -> None:
        """main() in polling mode must call run_polling and NOT run_webhook."""
        from zettelkasten_bot.main import main

        MockApp, mock_app = _wire_app_mock()
        settings = _make_polling_settings()

        with (
            patch("zettelkasten_bot.main.Application", MockApp),
            patch("zettelkasten_bot.main.get_settings", return_value=settings),
        ):
            main()

        mock_app.run_polling.assert_called_once_with(allowed_updates=Update.ALL_TYPES)
        mock_app.run_webhook.assert_not_called()


class TestWebhookMode:
    def test_webhook_mode_calls_run_webhook(self) -> None:
        """main() in webhook mode must call run_webhook with the correct kwargs."""
        from zettelkasten_bot.main import main

        MockApp, mock_app = _wire_app_mock()
        settings = _make_webhook_settings()

        with (
            patch("zettelkasten_bot.main.Application", MockApp),
            patch("zettelkasten_bot.main.get_settings", return_value=settings),
        ):
            main()

        mock_app.run_webhook.assert_called_once_with(
            listen="0.0.0.0",
            port=8443,
            url_path="test-token",
            webhook_url="https://example.com/hook",
            secret_token="secret123",
        )
        mock_app.run_polling.assert_not_called()


class TestHandlerRegistration:
    def test_registers_exactly_seven_handlers(self) -> None:
        """main() must register exactly 7 handlers via add_handler."""
        from zettelkasten_bot.main import main

        MockApp, mock_app = _wire_app_mock()
        settings = _make_polling_settings()

        with (
            patch("zettelkasten_bot.main.Application", MockApp),
            patch("zettelkasten_bot.main.get_settings", return_value=settings),
        ):
            main()

        assert mock_app.add_handler.call_count == 7

    def test_registers_error_handler(self) -> None:
        """main() must register a global error handler."""
        from zettelkasten_bot.main import main

        MockApp, mock_app = _wire_app_mock()
        settings = _make_polling_settings()

        with (
            patch("zettelkasten_bot.main.Application", MockApp),
            patch("zettelkasten_bot.main.get_settings", return_value=settings),
        ):
            main()

        mock_app.add_error_handler.assert_called_once()


class TestWebhookValidation:
    def test_webhook_mode_missing_url_exits(self) -> None:
        """_validate_settings raises SystemExit when webhook_mode=True and webhook_url=''."""
        settings = Settings(
            telegram_bot_token="test-token",
            allowed_chat_id=12345,
            webhook_mode=True,
            webhook_url="",
        )
        with pytest.raises(SystemExit) as exc_info:
            _validate_settings(settings)
        assert exc_info.value.code == 1

    def test_webhook_mode_whitespace_url_exits(self) -> None:
        """_validate_settings raises SystemExit when webhook_mode=True and webhook_url is whitespace-only."""
        settings = Settings(
            telegram_bot_token="test-token",
            allowed_chat_id=12345,
            webhook_mode=True,
            webhook_url="   ",
        )
        with pytest.raises(SystemExit) as exc_info:
            _validate_settings(settings)
        assert exc_info.value.code == 1

    def test_valid_webhook_url_does_not_exit(self) -> None:
        """_validate_settings does NOT raise when webhook_mode=True with a valid webhook_url."""
        settings = Settings(
            telegram_bot_token="test-token",
            allowed_chat_id=12345,
            webhook_mode=True,
            webhook_url="https://example.com/hook",
        )
        # Should not raise
        _validate_settings(settings)


class TestLogging:
    def test_logging_configured(self) -> None:
        """main() must call logging.basicConfig with the settings log_level."""
        from zettelkasten_bot.main import main

        MockApp, mock_app = _wire_app_mock()
        settings = _make_polling_settings(log_level="DEBUG")

        with (
            patch("zettelkasten_bot.main.Application", MockApp),
            patch("zettelkasten_bot.main.get_settings", return_value=settings),
            patch("zettelkasten_bot.main.logging") as mock_logging,
        ):
            # Re-expose basicConfig so the module-level call succeeds
            mock_logging.basicConfig = MagicMock()
            mock_logging.getLogger.return_value = MagicMock()
            main()

        mock_logging.basicConfig.assert_called_once()
        call_kwargs = mock_logging.basicConfig.call_args.kwargs
        assert call_kwargs.get("level") == "DEBUG"
