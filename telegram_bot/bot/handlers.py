"""Telegram command and message handlers for the Zettelkasten capture bot.

Handlers are kept thin: they validate user input and delegate all heavy
lifting to :func:`~telegram_bot.pipeline.orchestrator.process_url`.

Registered commands
-------------------
/start      — welcome message
/help       — alias for /start
/about      — what this bot does
/status     — bot health, seen URL count, KG note count
/reddit     — capture a Reddit post
/yt         — capture a YouTube video
/newsletter — capture a newsletter article
/github     — capture a GitHub repository/issue
/force      — reprocess a URL even if already captured

Plus a bare-URL ``MessageHandler`` that auto-detects the source type.
"""

from __future__ import annotations

import logging
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from telegram_bot.config.settings import get_settings
from telegram_bot.models.capture import SourceType
from telegram_bot.pipeline.duplicate import DuplicateStore
from telegram_bot.pipeline.orchestrator import process_url
from telegram_bot.utils.url_utils import validate_url

logger = logging.getLogger("bot.handlers")

_WELCOME = (
    "👋 *Zettelkasten Capture Bot*\n\n"
    "Send me any URL and I'll capture it automatically, or use a command to "
    "force a specific source type:\n\n"
    "• `/reddit <url>` — Reddit post/thread\n"
    "• `/yt <url>` — YouTube video\n"
    "• `/newsletter <url>` — Newsletter article\n"
    "• `/github <url>` — GitHub repo/issue/PR\n"
    "• `/ask <question>` — Ask across saved zettels\n"
    "• `/force <url>` — Re-capture even if already seen\n"
    "• `/status` — Bot health and stats\n\n"
    "Just paste a bare URL to auto-detect the source type."
)


_ABOUT = (
    "🧠 *About Zettelkasten Capture Bot*\n\n"
    "I turn URLs into structured Obsidian notes using AI. "
    "Send me any link — Reddit, YouTube, GitHub, newsletters, or any webpage — "
    "and I'll extract the content, summarize it with Gemini AI, "
    "generate tags, and save a formatted Markdown note to your knowledge graph. "
    "Supports duplicate detection, source auto-detection, and bidirectional backlinks."
)


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — send the welcome message."""
    await update.effective_message.reply_text(_WELCOME, parse_mode="Markdown")


async def handle_about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/about — explain what the bot does."""
    await update.effective_message.reply_text(_ABOUT, parse_mode="Markdown")


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
        data_dir=get_settings().data_dir,
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
        data_dir=get_settings().data_dir,
    )


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/status — show bot health, seen URL count, and KG note count."""
    settings = get_settings()

    # Count seen URLs
    try:
        store = DuplicateStore(settings.data_dir)
        seen_count = len(store._seen)
    except Exception:
        seen_count = "?"

    # Count KG notes
    try:
        kg_path = Path(settings.kg_directory)
        note_count = len(list(kg_path.glob("*.md"))) if kg_path.exists() else 0
    except Exception:
        note_count = "?"

    status_text = (
        "📊 *Bot Status*\n\n"
        f"• Status: Running\n"
        f"• URLs captured: {seen_count}\n"
        f"• Notes in KG: {note_count}\n"
        f"• AI model: {settings.model_name}\n"
        f"• KG directory: `{settings.kg_directory}`\n"
        f"• Mode: {'Webhook' if settings.webhook_mode else 'Polling'}"
    )
    await update.effective_message.reply_text(status_text, parse_mode="Markdown")


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
        data_dir=get_settings().data_dir,
    )
