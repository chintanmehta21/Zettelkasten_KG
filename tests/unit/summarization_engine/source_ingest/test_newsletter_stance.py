from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from website.features.summarization_engine.source_ingest.newsletter.stance import (
    classify_stance,
)


@pytest.mark.asyncio
async def test_classify_stance_returns_valid_enum(tmp_path: Path):
    client = MagicMock()
    client.generate = AsyncMock(
        return_value=MagicMock(text='{"stance": "skeptical", "confidence": 0.8}')
    )
    stance = await classify_stance(
        client=client,
        body_text="The whole AI hype is overblown.",
        cache_root=tmp_path,
        url="https://example.com/x",
    )
    assert stance == "skeptical"


@pytest.mark.asyncio
async def test_classify_stance_cache_hit(tmp_path: Path):
    from website.features.summarization_engine.core.cache import FsContentCache

    cache = FsContentCache(root=tmp_path, namespace="newsletter_stance")
    cache.put(("https://example.com/x", "stance.v1"), {"stance": "cautionary"})
    client = MagicMock()
    client.generate = AsyncMock()
    stance = await classify_stance(
        client=client,
        body_text="...",
        cache_root=tmp_path,
        url="https://example.com/x",
    )
    assert stance == "cautionary"
    client.generate.assert_not_called()


@pytest.mark.asyncio
async def test_classify_stance_invalid_enum_falls_back_to_neutral(tmp_path: Path):
    client = MagicMock()
    client.generate = AsyncMock(
        return_value=MagicMock(text='{"stance": "bullish", "confidence": 0.3}')
    )
    stance = await classify_stance(
        client=client,
        body_text="...",
        cache_root=tmp_path,
        url="https://example.com/y",
    )
    assert stance == "neutral"
