"""Live Slack delivery test. Skipped unless --live passed.

Requires SLACK_BOT_TOKEN_FEEDBACK + SLACK_CHANNEL_FEEDBACK to be set in env;
posts a real message to the configured channel. Run only against a test/dev
Slack workspace.
"""
from __future__ import annotations

import os

import pytest

from website.features.feedback.slack.client import build_production_client


pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_real_chat_postMessage() -> None:
    token = os.environ.get("SLACK_BOT_TOKEN_FEEDBACK", "")
    channel = os.environ.get("SLACK_CHANNEL_FEEDBACK", "")
    if not token or not channel:
        pytest.skip("Slack creds not set in env")

    client = build_production_client(token=token, channel=channel)
    ts = await client.post_message(
        blocks=[
            {"type": "header", "text": {"type": "plain_text",
             "text": "\U0001F4E3 LIVE TEST — feedback feature smoke"}},
            {"type": "section", "text": {"type": "mrkdwn",
             "text": "Posted from `tests/live/test_slack_live.py` — ignore."}},
        ],
        fallback_text="LIVE TEST — feedback feature smoke",
    )
    assert ts and "." in ts
