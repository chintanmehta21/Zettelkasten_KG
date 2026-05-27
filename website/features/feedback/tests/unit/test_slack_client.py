"""Tests for the Slack client wrapper (files_upload_v2 + chat.postMessage)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from website.features.feedback.slack.client import (
    FeedbackSlackClient,
    SlackPostError,
)


@pytest.fixture
def mock_sdk_client() -> MagicMock:
    sdk = MagicMock()
    sdk.files_upload_v2 = AsyncMock(return_value={
        "ok": True, "file": {"id": "F123ABC"}
    })
    sdk.chat_postMessage = AsyncMock(return_value={"ok": True, "ts": "1716800000.001"})
    return sdk


@pytest.mark.asyncio
async def test_upload_image_returns_file_id(mock_sdk_client: MagicMock) -> None:
    client = FeedbackSlackClient(
        sdk_client=mock_sdk_client, channel="C09TEST"
    )
    file_id = await client.upload_image(b"fake-bytes", filename="shot.jpg")
    assert file_id == "F123ABC"
    mock_sdk_client.files_upload_v2.assert_awaited_once()


@pytest.mark.asyncio
async def test_post_message_returns_ts(mock_sdk_client: MagicMock) -> None:
    client = FeedbackSlackClient(
        sdk_client=mock_sdk_client, channel="C09TEST"
    )
    ts = await client.post_message(blocks=[{"type": "section"}], fallback_text="hi")
    assert ts == "1716800000.001"
    mock_sdk_client.chat_postMessage.assert_awaited_once_with(
        channel="C09TEST", blocks=[{"type": "section"}], text="hi",
    )


@pytest.mark.asyncio
async def test_upload_raises_on_ok_false() -> None:
    sdk = MagicMock()
    sdk.files_upload_v2 = AsyncMock(return_value={"ok": False, "error": "no_scope"})
    client = FeedbackSlackClient(sdk_client=sdk, channel="C09TEST")
    with pytest.raises(SlackPostError, match="no_scope"):
        await client.upload_image(b"x", filename="x.jpg")


@pytest.mark.asyncio
async def test_post_raises_on_ok_false() -> None:
    sdk = MagicMock()
    sdk.chat_postMessage = AsyncMock(return_value={"ok": False, "error": "channel_not_found"})
    client = FeedbackSlackClient(sdk_client=sdk, channel="C09TEST")
    with pytest.raises(SlackPostError, match="channel_not_found"):
        await client.post_message(blocks=[], fallback_text="x")
