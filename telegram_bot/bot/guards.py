"""Chat-ID guard helpers for the Telegram bot.

The guard restricts every handler to the single allowed chat so that the bot
ignores requests from unknown users/groups.
"""

from __future__ import annotations

from telegram.ext import filters


def get_chat_filter(chat_id: int) -> filters.Chat:
    """Return a PTB ``filters.Chat`` instance restricted to *chat_id*.

    Use this when registering handlers so PTB silently discards updates that
    originate from any other chat.

    Args:
        chat_id: The Telegram chat ID to allow.

    Returns:
        A :class:`telegram.ext.filters.Chat` filter instance.
    """
    return filters.Chat(chat_id=chat_id)
