"""Telegram command and message handlers for the Zettelkasten capture bot.

Handlers are kept thin: they validate user input and delegate all heavy
lifting to :func:`~zettelkasten_bot.pipeline.orchestrator.process_url`.

Registered commands
-------------------
/start      — welcome message
/reddit     — capture a Reddit post
/yt         — capture a YouTube video
/newsletter — capture a newsletter article
/github     — capture a GitHub repository/issue
/force      — reprocess a URL even if already captured

Plus a bare-URL ``MessageHandler`` that auto-detects the source type.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from zettelkasten_bot.models.capture import SourceType
from zettelkasten_bot.pipeline.orchestrator import process_url
from zettelkasten_bot.utils.url_utils import validate_url

logger = logging.getLogger("bot.handlers")

_WELCOME = (
    "👋 *Zettelkasten Capture Bot*\n\n"
    "Send me any URL and I'll capture it automatically, or use a command to "
    "force a specific source type:\n\n"
    "• `/reddit <url>` — Reddit post/thread\n"
    "• `/yt <url>` — YouTube video\n"
    "• `/newsletter <url>` — Newsletter article\n"
    "• `/github <url>` — GitHub repo/issue/PR\n"
    "• `/force <url>` — Re-capture even if already seen\n\n"
    "Just paste a bare URL to auto-detect the source type."
)


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — send the welcome message."""
    await update.effective_message.reply_text(_WELCOME, parse_mode="Markdown")


async def handle_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    source_type: SourceType,
) -> None:
    """Shared handler logic used by the typed-source command handlers.

    Validates the URL argument and delegates to the pipeline orchestrator.
    """
    args = context.args or []
    if not args:
        cmd = update.effective_message.text.split()[0].lstrip("/")
        await update.effective_message.reply_text(f"Usage: /{cmd} <url>")
        return

    url = args[0]
    if not validate_url(url):
        await update.effective_message.reply_text("❌ Invalid URL")
        return

    logger.info("Command handler — source_type=%s url=%s", source_type, url)
    await process_url(
        context.bot,
        update.effective_chat.id,
        url,
        source_type,
        force=False,
    )


async def handle_reddit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/reddit <url> — capture a Reddit post."""
    await handle_command(update, context, SourceType.REDDIT)


async def handle_yt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/yt <url> — capture a YouTube video."""
    await handle_command(update, context, SourceType.YOUTUBE)


async def handle_newsletter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/newsletter <url> — capture a newsletter article."""
    await handle_command(update, context, SourceType.NEWSLETTER)


async def handle_github(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/github <url> — capture a GitHub repository or issue."""
    await handle_command(update, context, SourceType.GITHUB)


async def handle_force(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/force <url> — reprocess a URL even if already captured."""
    args = context.args or []
    if not args:
        await update.effective_message.reply_text("Usage: /force <url>")
        return

    url = args[0]
    if not validate_url(url):
        await update.effective_message.reply_text("❌ Invalid URL")
        return

    logger.info("Force handler — url=%s", url)
    await process_url(
        context.bot,
        update.effective_chat.id,
        url,
        None,  # auto-detect source type
        force=True,
    )


async def handle_bare_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """MessageHandler for plain-text messages that contain a bare URL.

    Extracts the first whitespace-separated token and treats it as a URL.
    If it is not a valid URL the message is silently ignored (no reply).
    """
    text = (update.effective_message.text or "").strip()
    # Use the first token; extra words after the URL are ignored
    candidate = text.split()[0] if text else ""

    if not candidate or not validate_url(candidate):
        # Not a URL — ignore silently
        return

    logger.info("Bare-URL handler — url=%s", candidate)
    await process_url(
        context.bot,
        update.effective_chat.id,
        candidate,
        None,  # auto-detect
        force=False,
    )
