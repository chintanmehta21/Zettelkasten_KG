from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from website.features.summarization_engine.evaluator.atomic_facts import (
    extract_atomic_facts,
)


@pytest.mark.asyncio
async def test_extract_atomic_facts_returns_list(tmp_path: Path):
    client = MagicMock()
    fake_result = MagicMock(
        text='[{"claim": "X is Y", "importance": 5}]',
        input_tokens=10,
        output_tokens=5,
    )
    client.generate = AsyncMock(return_value=fake_result)

    facts = await extract_atomic_facts(
        client=client,
        source_text="...",
        cache_root=tmp_path,
        url="https://a.com",
        ingestor_version="1.0.0",
    )

    assert facts == [{"claim": "X is Y", "importance": 5}]


@pytest.mark.asyncio
async def test_extract_atomic_facts_cache_hit(tmp_path: Path):
    client = MagicMock()
    client.generate = AsyncMock()

    from website.features.summarization_engine.core.cache import FsContentCache

    cache = FsContentCache(root=tmp_path, namespace="atomic_facts")
    cache.put(
        ("https://a.com", "1.0.0", "evaluator.v1"),
        {"facts": [{"claim": "cached", "importance": 3}]},
    )

    facts = await extract_atomic_facts(
        client=client,
        source_text="...",
        cache_root=tmp_path,
        url="https://a.com",
        ingestor_version="1.0.0",
    )

    assert facts == [{"claim": "cached", "importance": 3}]
    client.generate.assert_not_called()
