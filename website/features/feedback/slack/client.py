"""Async Slack client wrapper for the feedback feature.

Uses the official `slack_sdk` AsyncWebClient. Provides two narrow methods —
upload_image and post_message — instead of exposing the full SDK surface.

The slack_sdk library already handles HTTP retries on 429 + 5xx with
exponential backoff via its built-in `RetryHandler`s. We pass them in
when constructing the client.
"""
from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger("feedback.slack")


class SlackPostError(Exception):
    """Raised when Slack returns ok=False (incl. 429 after retries exhausted)."""


class _SlackSDKProtocol(Protocol):
    async def files_upload_v2(self, **kwargs): ...
    async def chat_postMessage(self, **kwargs): ...


class FeedbackSlackClient:
    """Thin wrapper. The SDK client may be the real AsyncWebClient or a mock."""

    def __init__(self, *, sdk_client: _SlackSDKProtocol, channel: str) -> None:
        self._sdk = sdk_client
        self._channel = channel

    async def upload_image(self, content: bytes, *, filename: str) -> str:
        """Upload one image; return the Slack file ID like 'F123ABC'."""
        try:
            res = await self._sdk.files_upload_v2(
                channel=self._channel,
                content=content,
                filename=filename,
                title=filename,
            )
        except Exception as exc:
            raise SlackPostError(f"files_upload_v2 failed: {exc}") from exc
        if not res.get("ok"):
            err = res.get("error", "unknown")
            raise SlackPostError(f"files_upload_v2 failed: {err}")
        return res["file"]["id"]

    async def post_message(self, *, blocks: list[dict], fallback_text: str) -> str:
        """Post a Block Kit message; return the message ts."""
        try:
            res = await self._sdk.chat_postMessage(
                channel=self._channel, blocks=blocks, text=fallback_text,
            )
        except Exception as exc:
            raise SlackPostError(f"chat.postMessage failed: {exc}") from exc
        if not res.get("ok"):
            err = res.get("error", "unknown")
            raise SlackPostError(f"chat.postMessage failed: {err}")
        return res["ts"]


def build_production_client(*, token: str, channel: str) -> FeedbackSlackClient:
    """Construct a real Slack-backed client. Lazy-imports slack_sdk."""
    from slack_sdk.web.async_client import AsyncWebClient
    from slack_sdk.http_retry.builtin_async_handlers import (
        AsyncRateLimitErrorRetryHandler,
        AsyncServerErrorRetryHandler,
    )
    sdk = AsyncWebClient(
        token=token,
        retry_handlers=[
            AsyncRateLimitErrorRetryHandler(max_retry_count=3),
            AsyncServerErrorRetryHandler(max_retry_count=3),
        ],
    )
    return FeedbackSlackClient(sdk_client=sdk, channel=channel)
