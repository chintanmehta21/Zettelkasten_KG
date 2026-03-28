"""Application entry point for the Zettelkasten Telegram bot.

Loads settings, configures logging, builds the PTB Application, registers
all command and message handlers with the chat-ID guard, then starts either
polling (default) or webhook mode based on :data:`Settings.webhook_mode`.

In webhook mode, a FastAPI application serves both the web UI and the
Telegram webhook on the same port, enabling coexistence on Render's free
tier (single service).
"""

from __future__ import annotations

import asyncio
import logging
import traceback

from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from zettelkasten_bot.bot.guards import get_chat_filter
from zettelkasten_bot.bot.handlers import (
    handle_about,
    handle_bare_url,
    handle_force,
    handle_github,
    handle_newsletter,
    handle_reddit,
    handle_start,
    handle_status,
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


async def _post_init(application: Application) -> None:
    """Register the bot command menu with Telegram on startup."""
    await application.bot.set_my_commands([
        BotCommand("start", "Welcome message and usage guide"),
        BotCommand("about", "What this bot does"),
        BotCommand("help", "Show available commands"),
        BotCommand("status", "Bot health and statistics"),
        BotCommand("reddit", "Capture a Reddit post"),
        BotCommand("yt", "Capture a YouTube video"),
        BotCommand("newsletter", "Capture a newsletter or article"),
        BotCommand("github", "Capture a GitHub repo or issue"),
        BotCommand("force", "Re-capture a URL (skip duplicate check)"),
    ])
    logger.info("Bot command menu registered with Telegram")


def _build_ptb_app(settings) -> Application:
    """Build and configure the PTB Application with all handlers."""
    app: Application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .build()
    )

    chat_filter = get_chat_filter(settings.allowed_chat_id)

    # ── Register handlers ─────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",      handle_start,      filters=chat_filter))
    app.add_handler(CommandHandler("about",      handle_about,      filters=chat_filter))
    app.add_handler(CommandHandler("help",       handle_start,      filters=chat_filter))
    app.add_handler(CommandHandler("status",     handle_status,     filters=chat_filter))
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
    return app


def _run_webhook(settings) -> None:
    """Run in webhook mode: FastAPI serves web UI + Telegram webhook.

    Uses the official PTB custom webhook pattern:
    https://github.com/python-telegram-bot/python-telegram-bot/wiki/Webhooks
    """
    import uvicorn
    from contextlib import asynccontextmanager
    from fastapi import Request, Response

    from website.app import create_app

    ptb_app = _build_ptb_app(settings)

    @asynccontextmanager
    async def lifespan(app):
        await ptb_app.initialize()
        await ptb_app.start()
        try:
            await ptb_app.bot.set_webhook(
                url=settings.webhook_url,
                secret_token=settings.webhook_secret or None,
            )
            logger.info("PTB started, webhook set to %s", settings.webhook_url)
        except Exception:
            logger.warning("Failed to set webhook URL — bot may not receive updates")
        yield
        await ptb_app.stop()
        await ptb_app.shutdown()

    web_app = create_app(lifespan=lifespan)

    # Telegram webhook endpoint
    token_path = f"/{settings.telegram_bot_token}"

    @web_app.post(token_path)
    async def telegram_webhook(request: Request) -> Response:
        """Forward Telegram updates to PTB via update queue.

        Returns 200 immediately — PTB processes the update in the
        background.  This prevents Telegram's ~60 s webhook timeout
        from killing long-running pipelines (YouTube extraction can
        take 30–60 s on Render's free tier).
        """
        if settings.webhook_secret:
            header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if header_secret != settings.webhook_secret:
                return Response(status_code=403)

        data = await request.json()
        update = Update.de_json(data, ptb_app.bot)
        await ptb_app.update_queue.put(update)
        return Response(status_code=200)

    logger.info(
        "Webhook mode — serving web UI + bot on 0.0.0.0:%d",
        settings.webhook_port,
    )

    uvicorn.run(
        web_app,
        host="0.0.0.0",
        port=settings.webhook_port,
        log_level="info",
    )


def _run_polling(settings) -> None:
    """Run in polling mode (local dev)."""
    ptb_app = _build_ptb_app(settings)
    logger.info("Polling mode — starting long-poll loop")
    ptb_app.run_polling(allowed_updates=Update.ALL_TYPES)


def main() -> None:
    """Build the PTB application and start the bot."""
    settings = get_settings()

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger.info("Starting Zettelkasten bot (webhook_mode=%s)", settings.webhook_mode)

    if settings.webhook_mode:
        _run_webhook(settings)
    else:
        _run_polling(settings)


if __name__ == "__main__":
    main()
