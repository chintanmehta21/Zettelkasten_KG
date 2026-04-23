from unittest.mock import AsyncMock

import pytest

from website.features.summarization_engine.core.config import EngineConfig
from website.features.summarization_engine.summarization.common.self_check import (
    InvertedFactScoreSelfCheck,
)


@pytest.mark.asyncio
async def test_self_check_degrades_on_generation_failure():
    class Client:
        generate = AsyncMock(side_effect=TimeoutError("upstream timeout"))

    result = await InvertedFactScoreSelfCheck(Client(), EngineConfig()).check(
        "source",
        "summary",
    )

    assert result.missing == []
    assert result.pro_tokens == 0
