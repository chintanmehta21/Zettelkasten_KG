"""Tests for telegram_bot.bot.handlers and telegram_bot.bot.guards.

Strategy
--------
All tests mock the Telegram API surface (Update, Message, Bot) and the
pipeline orchestrator so that no real HTTP connections or env-var validation
is needed.  pytest-asyncio runs the async handlers with asyncio_mode=auto
(configured in pytest.ini).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.ext import filters

from telegram_bot.bot.guards import get_chat_filter
from telegram_bot.bot.handlers import (
    handle_bare_url,
    handle_force,
    handle_github,
    handle_newsletter,
    handle_reddit,
    handle_start,
    handle_status,
    handle_yt,
)
from telegram_bot.models.capture import SourceType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_update(text: str = "", args: list[str] | None = None):
    """Return a mock Update with a reply_text spy."""
    update = MagicMock()
    update.effective_chat = MagicMock()
    update.effective_chat.id = 12345

    msg = AsyncMock()
    msg.text = text
    msg.reply_text = AsyncMock()
    update.effective_message = msg
    return update


def _make_context(args: list[str] | None = None):
    """Return a mock ContextTypes.DEFAULT_TYPE with .args and .bot."""
    ctx = MagicMock()
    ctx.args = args or []
    ctx.bot = AsyncMock()
    return ctx


# ---------------------------------------------------------------------------
# guard tests
# ---------------------------------------------------------------------------

class TestGetChatFilter:
    def test_returns_chat_filter_type(self):
        f = get_chat_filter(12345)
        assert isinstance(f, filters.Chat)

    def test_chat_id_stored(self):
        f = get_chat_filter(99999)
        # filters.Chat stores allowed IDs in its chat_ids attribute
        assert 99999 in f.chat_ids


# ---------------------------------------------------------------------------
# /start handler
# ---------------------------------------------------------------------------

class TestHandleStart:
    async def test_replies_with_welcome(self):
        update = _make_update()
        ctx = _make_context()
        await handle_start(update, ctx)
        update.effective_message.reply_text.assert_called_once()
        call_kwargs = update.effective_message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert "Zettelkasten" in text

    async def test_welcome_lists_commands(self):
        update = _make_update()
        ctx = _make_context()
        await handle_start(update, ctx)
        text = update.effective_message.reply_text.call_args.args[0]
        for cmd in ("/reddit", "/yt", "/newsletter", "/github", "/force"):
            assert cmd in text


# ---------------------------------------------------------------------------
# typed command handlers (/reddit, /yt, /newsletter, /github)
# ---------------------------------------------------------------------------

class TestHandleReddit:
    @patch("telegram_bot.bot.handlers.get_settings")
    @patch("telegram_bot.bot.handlers.process_url", new_callable=AsyncMock)
    async def test_valid_url_calls_process_url(self, mock_proc, mock_get_settings):
        mock_get_settings.return_value.data_dir = "./test-data"
        url = "https://www.reddit.com/r/python/comments/abc123/test/"
        update = _make_update(text=f"/reddit {url}")
        ctx = _make_context(args=[url])
        await handle_reddit(update, ctx)
        mock_proc.assert_called_once()
        _, call_args, call_kwargs = mock_proc.mock_calls[0]
        # positional: bot, chat_id, url, source_type, force
        assert call_args[2] == url
        assert call_args[3] == SourceType.REDDIT
        assert call_kwargs.get("force", call_args[4] if len(call_args) > 4 else False) is False
        assert call_kwargs.get("data_dir") == "./test-data"

    @patch("telegram_bot.bot.handlers.process_url", new_callable=AsyncMock)
    async def test_no_args_replies_usage(self, mock_proc):
        update = _make_update(text="/reddit")
        ctx = _make_context(args=[])
        await handle_reddit(update, ctx)
        mock_proc.assert_not_called()
        update.effective_message.reply_text.assert_called_once()
        text = update.effective_message.reply_text.call_args.args[0]
        assert "Usage" in text or "usage" in text

    @patch("telegram_bot.bot.handlers.process_url", new_callable=AsyncMock)
    async def test_invalid_url_replies_error(self, mock_proc):
        update = _make_update(text="/reddit not-a-url")
        ctx = _make_context(args=["not-a-url"])
        await handle_reddit(update, ctx)
        mock_proc.assert_not_called()
        text = update.effective_message.reply_text.call_args.args[0]
        assert "Invalid" in text or "invalid" in text


class TestHandleYt:
    @patch("telegram_bot.bot.handlers.process_url", new_callable=AsyncMock)
    async def test_valid_url_calls_process_url_with_youtube(self, mock_proc):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        update = _make_update(text=f"/yt {url}")
        ctx = _make_context(args=[url])
        await handle_yt(update, ctx)
        mock_proc.assert_called_once()
        _, call_args, _ = mock_proc.mock_calls[0]
        assert call_args[3] == SourceType.YOUTUBE

    @patch("telegram_bot.bot.handlers.process_url", new_callable=AsyncMock)
    async def test_no_args_replies_usage(self, mock_proc):
        update = _make_update(text="/yt")
        ctx = _make_context(args=[])
        await handle_yt(update, ctx)
        mock_proc.assert_not_called()
        text = update.effective_message.reply_text.call_args.args[0]
        assert "Usage" in text or "usage" in text


class TestHandleNewsletter:
    @patch("telegram_bot.bot.handlers.process_url", new_callable=AsyncMock)
    async def test_valid_url_calls_process_url_with_newsletter(self, mock_proc):
        url = "https://example.substack.com/p/article"
        update = _make_update(text=f"/newsletter {url}")
        ctx = _make_context(args=[url])
        await handle_newsletter(update, ctx)
        mock_proc.assert_called_once()
        _, call_args, _ = mock_proc.mock_calls[0]
        assert call_args[3] == SourceType.NEWSLETTER


class TestHandleGithub:
    @patch("telegram_bot.bot.handlers.process_url", new_callable=AsyncMock)
    async def test_valid_url_calls_process_url_with_github(self, mock_proc):
        url = "https://github.com/user/repo"
        update = _make_update(text=f"/github {url}")
        ctx = _make_context(args=[url])
        await handle_github(update, ctx)
        mock_proc.assert_called_once()
        _, call_args, _ = mock_proc.mock_calls[0]
        assert call_args[3] == SourceType.GITHUB


# ---------------------------------------------------------------------------
# /force handler
# ---------------------------------------------------------------------------

class TestHandleForce:
    @patch("telegram_bot.bot.handlers.get_settings")
    @patch("telegram_bot.bot.handlers.process_url", new_callable=AsyncMock)
    async def test_passes_force_true(self, mock_proc, mock_get_settings):
        mock_get_settings.return_value.data_dir = "./test-data"
        url = "https://www.reddit.com/r/python/comments/abc123/test/"
        update = _make_update(text=f"/force {url}")
        ctx = _make_context(args=[url])
        await handle_force(update, ctx)
        mock_proc.assert_called_once()
        _, call_args, call_kwargs = mock_proc.mock_calls[0]
        # force is the 5th positional arg (index 4)
        force_val = call_kwargs.get("force", call_args[4] if len(call_args) > 4 else None)
        assert force_val is True
        assert call_kwargs.get("data_dir") == "./test-data"

    @patch("telegram_bot.bot.handlers.process_url", new_callable=AsyncMock)
    async def test_source_type_is_none_for_auto_detect(self, mock_proc):
        url = "https://github.com/user/repo"
        update = _make_update(text=f"/force {url}")
        ctx = _make_context(args=[url])
        await handle_force(update, ctx)
        _, call_args, _ = mock_proc.mock_calls[0]
        assert call_args[3] is None  # auto-detect

    @patch("telegram_bot.bot.handlers.process_url", new_callable=AsyncMock)
    async def test_no_args_replies_usage(self, mock_proc):
        update = _make_update(text="/force")
        ctx = _make_context(args=[])
        await handle_force(update, ctx)
        mock_proc.assert_not_called()
        text = update.effective_message.reply_text.call_args.args[0]
        assert "Usage" in text or "usage" in text

    @patch("telegram_bot.bot.handlers.process_url", new_callable=AsyncMock)
    async def test_invalid_url_replies_error(self, mock_proc):
        update = _make_update(text="/force not-a-url")
        ctx = _make_context(args=["not-a-url"])
        await handle_force(update, ctx)
        mock_proc.assert_not_called()
        text = update.effective_message.reply_text.call_args.args[0]
        assert "Invalid" in text or "invalid" in text


# ---------------------------------------------------------------------------
# bare-URL handler
# ---------------------------------------------------------------------------

class TestHandleBareUrl:
    @patch("telegram_bot.bot.handlers.get_settings")
    @patch("telegram_bot.bot.handlers.process_url", new_callable=AsyncMock)
    async def test_valid_url_calls_process_url(self, mock_proc, mock_get_settings):
        mock_get_settings.return_value.data_dir = "./test-data"
        url = "https://example.com/article"
        update = _make_update(text=url)
        ctx = _make_context()
        await handle_bare_url(update, ctx)
        mock_proc.assert_called_once()
        _, call_args, call_kwargs = mock_proc.mock_calls[0]
        assert call_args[2] == url
        assert call_kwargs.get("data_dir") == "./test-data"

    @patch("telegram_bot.bot.handlers.process_url", new_callable=AsyncMock)
    async def test_valid_url_source_type_is_none(self, mock_proc):
        url = "https://example.com/article"
        update = _make_update(text=url)
        ctx = _make_context()
        await handle_bare_url(update, ctx)
        _, call_args, _ = mock_proc.mock_calls[0]
        assert call_args[3] is None  # auto-detect

    @patch("telegram_bot.bot.handlers.process_url", new_callable=AsyncMock)
    async def test_not_a_url_silently_ignored(self, mock_proc):
        update = _make_update(text="hello there, just chatting")
        ctx = _make_context()
        await handle_bare_url(update, ctx)
        mock_proc.assert_not_called()
        # Must NOT reply — silent ignore
        update.effective_message.reply_text.assert_not_called()

    @patch("telegram_bot.bot.handlers.process_url", new_callable=AsyncMock)
    async def test_empty_text_silently_ignored(self, mock_proc):
        update = _make_update(text="")
        ctx = _make_context()
        await handle_bare_url(update, ctx)
        mock_proc.assert_not_called()
        update.effective_message.reply_text.assert_not_called()

    @patch("telegram_bot.bot.handlers.process_url", new_callable=AsyncMock)
    async def test_multiple_tokens_uses_first_url(self, mock_proc):
        url = "https://example.com/article"
        update = _make_update(text=f"{url} some extra text")
        ctx = _make_context()
        await handle_bare_url(update, ctx)
        mock_proc.assert_called_once()
        _, call_args, _ = mock_proc.mock_calls[0]
        assert call_args[2] == url


# ---------------------------------------------------------------------------
# Negative tests per spec
# ---------------------------------------------------------------------------

class TestNegativeInputs:
    @patch("telegram_bot.bot.handlers.process_url", new_callable=AsyncMock)
    async def test_reddit_no_url_gives_usage(self, mock_proc):
        update = _make_update(text="/reddit")
        ctx = _make_context(args=[])
        await handle_reddit(update, ctx)
        mock_proc.assert_not_called()
        text = update.effective_message.reply_text.call_args.args[0]
        assert "reddit" in text.lower() or "Usage" in text

    @patch("telegram_bot.bot.handlers.process_url", new_callable=AsyncMock)
    async def test_reddit_invalid_url_gives_invalid_url_message(self, mock_proc):
        update = _make_update(text="/reddit not-a-url")
        ctx = _make_context(args=["not-a-url"])
        await handle_reddit(update, ctx)
        mock_proc.assert_not_called()
        text = update.effective_message.reply_text.call_args.args[0]
        assert "Invalid" in text

    @patch("telegram_bot.bot.handlers.process_url", new_callable=AsyncMock)
    async def test_force_no_url_gives_usage(self, mock_proc):
        update = _make_update(text="/force")
        ctx = _make_context(args=[])
        await handle_force(update, ctx)
        mock_proc.assert_not_called()
        text = update.effective_message.reply_text.call_args.args[0]
        assert "Usage" in text or "force" in text.lower()

    @patch("telegram_bot.bot.handlers.process_url", new_callable=AsyncMock)
    async def test_bare_message_not_url_no_reply(self, mock_proc):
        update = _make_update(text="just some random text")
        ctx = _make_context()
        await handle_bare_url(update, ctx)
        mock_proc.assert_not_called()
        update.effective_message.reply_text.assert_not_called()


# ---------------------------------------------------------------------------
# /status handler
# ---------------------------------------------------------------------------


class TestHandleStatus:
    @patch("telegram_bot.bot.handlers.DuplicateStore")
    @patch("telegram_bot.bot.handlers.get_settings")
    async def test_status_replies_with_stats(self, mock_get_settings, mock_store_cls):
        mock_settings = MagicMock()
        mock_settings.data_dir = "./test-data"
        mock_settings.kg_directory = "./nonexistent-kg"
        mock_settings.model_name = "gemini-2.5-flash"
        mock_settings.webhook_mode = False
        mock_get_settings.return_value = mock_settings

        mock_store = MagicMock()
        mock_store._seen = {"url1", "url2", "url3"}
        mock_store_cls.return_value = mock_store

        update = _make_update()
        ctx = _make_context()
        await handle_status(update, ctx)

        update.effective_message.reply_text.assert_called_once()
        text = update.effective_message.reply_text.call_args.args[0]
        assert "Bot Status" in text
        assert "3" in text  # 3 seen URLs
        assert "gemini-2.5-flash" in text
        assert "Polling" in text
