import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from website.features.summarization_engine.source_ingest.github.architecture import (
    extract_architecture_overview,
)


@pytest.mark.asyncio
async def test_extract_architecture_returns_prose(tmp_path: Path):
    client = MagicMock()
    client.generate = AsyncMock(
        return_value=MagicMock(
            text="The repo has modules A, B, C that interact via a central bus.",
            input_tokens=100,
            output_tokens=40,
        )
    )
    overview = await extract_architecture_overview(
        client=client,
        readme_text="# My repo\n## Architecture...",
        top_level_dirs=["src", "tests", "docs"],
        max_chars=500,
        cache_root=tmp_path,
        slug="a/b",
    )
    assert "modules A, B, C" in overview
    assert len(overview) <= 500


@pytest.mark.asyncio
async def test_extract_architecture_cache_hit(tmp_path: Path):
    from website.features.summarization_engine.core.cache import FsContentCache

    cache = FsContentCache(root=tmp_path, namespace="github_architecture")
    cache.put(("a/b", "arch.v1"), {"overview": "cached overview text"})
    client = MagicMock()
    client.generate = AsyncMock()
    overview = await extract_architecture_overview(
        client=client,
        readme_text="...",
        top_level_dirs=["src"],
        max_chars=500,
        cache_root=tmp_path,
        slug="a/b",
    )
    assert overview == "cached overview text"
    client.generate.assert_not_called()
