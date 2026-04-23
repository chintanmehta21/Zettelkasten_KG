from unittest.mock import AsyncMock

import pytest

from website.features.summarization_engine.source_ingest.youtube.tiers import (
    TierName,
    TierResult,
    TranscriptChain,
)


@pytest.mark.asyncio
async def test_chain_calls_tiers_in_order_until_success():
    t1 = AsyncMock(
        return_value=TierResult(
            tier=TierName.YTDLP_PLAYER_ROTATION,
            transcript="",
            success=False,
        )
    )
    t2 = AsyncMock(
        return_value=TierResult(
            tier=TierName.TRANSCRIPT_API_DIRECT,
            transcript="hello",
            success=True,
        )
    )
    t3 = AsyncMock(
        return_value=TierResult(
            tier=TierName.PIPED_POOL,
            transcript="x",
            success=True,
        )
    )

    chain = TranscriptChain(tiers=[t1, t2, t3], budget_ms=60000)
    result = await chain.run(video_id="x", config={})

    assert result.tier == TierName.TRANSCRIPT_API_DIRECT
    t1.assert_called_once()
    t2.assert_called_once()
    t3.assert_not_called()


@pytest.mark.asyncio
async def test_chain_stops_when_budget_exceeded():
    import asyncio

    async def slow_tier(video_id, config):
        await asyncio.sleep(0.3)
        return TierResult(
            tier=TierName.YTDLP_PLAYER_ROTATION,
            transcript="",
            success=False,
        )

    chain = TranscriptChain(tiers=[slow_tier, slow_tier, slow_tier], budget_ms=500)
    result = await chain.run(video_id="x", config={})

    assert not result.success
