"""Application entry point for the Zettelkasten Telegram bot.

Loads settings, configures logging, builds the PTB Application, registers
all command and message handlers with the chat-ID guard, then starts either
polling (default) or webhook mode based on :data:`Settings.webhook_mode`.
"""

from __future__ import annotations

import logging
import traceback

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from zettelkasten_bot.bot.guards import get_chat_filter
from zettelkasten_bot.bot.handlers import (
    handle_bare_url,
    handle_force,
    handle_github,
    handle_newsletter,
    handle_reddit,
    handle_start,
    handle_yt,
)
from zettelkasten_bot.config.settings import get_settings

logger = logging.getLogger("bot.main")


async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log unhandled exceptions and notify the user when possible."""
    logger.error(
        "Unhandled exception while processing update %s:\n%s",
        update,
        traceback.format_exc(),
    )
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                update.effective_chat.id,
                "An unexpected error occurred. Please try again.",
            )
        except Exception:
            logger.error("Failed to send error notification to user")


def main() -> None:
    """Build the PTB application and start the bot."""
    settings = get_settings()

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger.info("Starting Zettelkasten bot (webhook_mode=%s)", settings.webhook_mode)

    app: Application = Application.builder().token(settings.telegram_bot_token).build()

    chat_filter = get_chat_filter(settings.allowed_chat_id)

    # ── Register handlers ─────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",      handle_start,      filters=chat_filter))
    app.add_handler(CommandHandler("reddit",     handle_reddit,     filters=chat_filter))
    app.add_handler(CommandHandler("yt",         handle_yt,         filters=chat_filter))
    app.add_handler(CommandHandler("newsletter", handle_newsletter, filters=chat_filter))
    app.add_handler(CommandHandler("github",     handle_github,     filters=chat_filter))
    app.add_handler(CommandHandler("force",      handle_force,      filters=chat_filter))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & chat_filter, handle_bare_url)
    )

    # ── Global error handler ──────────────────────────────────────────────
    app.add_error_handler(_error_handler)

    # ── Start ─────────────────────────────────────────────────────────────
    if settings.webhook_mode:
        logger.info(
            "Webhook mode — listening on 0.0.0.0:%d, path=/%s",
            settings.webhook_port,
            settings.telegram_bot_token,
        )
        app.run_webhook(
            listen="0.0.0.0",
            port=settings.webhook_port,
            url_path=settings.telegram_bot_token,
            webhook_url=settings.webhook_url,
            secret_token=settings.webhook_secret,
        )
    else:
        logger.info("Polling mode — starting long-poll loop")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
