"""Telegram /ask command backed by the shared web RAG orchestrator."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from website.features.rag_pipeline.service import get_rag_runtime
from website.features.rag_pipeline.types import ChatQuery

logger = logging.getLogger("bot.ask_handler")


async def handle_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    question = " ".join(context.args or []).strip()
    if not question:
        await update.effective_message.reply_text("Usage: /ask <question>")
        return

    await update.effective_message.reply_text("Searching your saved zettels...")

    try:
        runtime = get_rag_runtime(None)
        turn = await runtime.orchestrator.answer(
            query=ChatQuery(content=question, quality="fast", stream=False),
            user_id=runtime.kg_user_id,
        )
    except Exception as exc:
        logger.exception("Telegram /ask failed")
        await update.effective_message.reply_text(f"RAG is unavailable right now: {exc}")
        return

    lines = [turn.content.strip() or "I could not find an answer in your saved zettels."]
    if turn.citations:
        lines.append("")
        lines.append("Sources:")
        for citation in turn.citations[:5]:
            lines.append(f"- {citation.title}")

    await update.effective_message.reply_text("\n".join(lines))

