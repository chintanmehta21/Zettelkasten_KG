"""Tests for the top-level orchestrator."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from website.features.feedback.core.identity import Identity
from website.features.feedback.intake.models import (
    FeedbackIntent, FeedbackSubmitRequest,
)
from website.features.feedback.service import (
    FeedbackService,
)


@pytest.fixture
def identity() -> Identity:
    return Identity(
        full_name="Naruto Uzumaki",
        email="naruto@konoha.jp",
        country_label="India (IN)",   # operator preference 2026-05-27 (parens, not em-dash)
        is_anonymous=False,
    )


@pytest.fixture
def valid_request() -> FeedbackSubmitRequest:
    return FeedbackSubmitRequest(
        intent=FeedbackIntent.ISSUE,
        subject="Add Zettel fails on long videos",
        description="The /api/zettels/add endpoint returns 504 after 90s.",
        follow_up_email=True,
    )


@pytest.fixture
def mock_slack() -> MagicMock:
    m = MagicMock()
    m.upload_image = AsyncMock(side_effect=lambda content, filename: f"F{filename}")
    m.post_message = AsyncMock(return_value="1716800000.001")
    return m


@pytest.mark.asyncio
async def test_submit_calls_upload_per_image_then_post(
    identity: Identity, valid_request: FeedbackSubmitRequest, mock_slack: MagicMock,
) -> None:
    service = FeedbackService(slack_client=mock_slack)
    fid = await service.submit(
        request=valid_request,
        identity=identity,
        processed_images=[
            ("aaaa.jpg", b"fake-jpeg-bytes-1"),
            ("bbbb.png", b"fake-png-bytes-2"),
        ],
    )
    assert fid.startswith("FB-")
    assert mock_slack.upload_image.await_count == 2
    mock_slack.post_message.assert_awaited_once()
    # Verify the posted blocks reference the uploaded file IDs
    posted_blocks = mock_slack.post_message.call_args.kwargs["blocks"]
    image_blocks = [b for b in posted_blocks if b["type"] == "image"]
    assert {b["slack_file"]["id"] for b in image_blocks} == {"Faaaa.jpg", "Fbbbb.png"}


@pytest.mark.asyncio
async def test_submit_with_no_images(
    identity: Identity, valid_request: FeedbackSubmitRequest, mock_slack: MagicMock,
) -> None:
    service = FeedbackService(slack_client=mock_slack)
    await service.submit(request=valid_request, identity=identity, processed_images=[])
    mock_slack.upload_image.assert_not_awaited()
    mock_slack.post_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_submit_returns_stable_id_format(
    identity: Identity, valid_request: FeedbackSubmitRequest, mock_slack: MagicMock,
) -> None:
    import re
    service = FeedbackService(slack_client=mock_slack)
    fid = await service.submit(request=valid_request, identity=identity, processed_images=[])
    assert re.match(r"^FB-[A-Z2-7]{4}$", fid)
