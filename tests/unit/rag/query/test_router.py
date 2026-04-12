import pytest

from website.features.rag_pipeline.query.router import QueryRouter
from website.features.rag_pipeline.types import QueryClass


@pytest.mark.asyncio
async def test_classify_lookup_for_entity_query() -> None:
    class _Pool:
        async def generate_content(self, contents, **kwargs):
            return '{"class":"lookup"}'

    assert await QueryRouter(pool=_Pool()).classify("Who wrote this post?") is QueryClass.LOOKUP


@pytest.mark.asyncio
async def test_classify_thematic_for_broad_query() -> None:
    class _Pool:
        async def generate_content(self, contents, **kwargs):
            return '{"class":"thematic"}'

    assert await QueryRouter(pool=_Pool()).classify("What themes show up across my AI notes?") is QueryClass.THEMATIC


@pytest.mark.asyncio
async def test_fallback_to_lookup_on_parse_error() -> None:
    class _Pool:
        async def generate_content(self, contents, **kwargs):
            return 'not json'

    assert await QueryRouter(pool=_Pool()).classify("What is RRF?") is QueryClass.LOOKUP


@pytest.mark.asyncio
async def test_classify_returns_one_of_five_classes() -> None:
    class _Pool:
        async def generate_content(self, contents, **kwargs):
            return '{"class":"step_back"}'

    result = await QueryRouter(pool=_Pool()).classify("How does this specific paper connect to the broader field?")
    assert result in set(QueryClass)

