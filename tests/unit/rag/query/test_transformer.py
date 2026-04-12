import pytest

from website.features.rag_pipeline.query.transformer import QueryTransformer
from website.features.rag_pipeline.types import QueryClass


@pytest.mark.asyncio
async def test_lookup_returns_original_only() -> None:
    assert await QueryTransformer(pool=None).transform("What is RRF?", QueryClass.LOOKUP) == ["What is RRF?"]


@pytest.mark.asyncio
async def test_vague_generates_hyde_variant() -> None:
    class _Pool:
        async def generate_content(self, contents, **kwargs):
            return "Hypothetical answer"

    variants = await QueryTransformer(pool=_Pool()).transform("Tell me about attention", QueryClass.VAGUE)
    assert variants == ["Tell me about attention", "Hypothetical answer"]


@pytest.mark.asyncio
async def test_multi_hop_decomposes_into_n_subqueries() -> None:
    class _Pool:
        async def generate_content(self, contents, **kwargs):
            return "sub-1\nsub-2\nsub-3"

    variants = await QueryTransformer(pool=_Pool()).transform("How are X and Y related?", QueryClass.MULTI_HOP)
    assert variants == ["How are X and Y related?", "sub-1", "sub-2", "sub-3"]


@pytest.mark.asyncio
async def test_thematic_generates_n_reformulations() -> None:
    class _Pool:
        async def generate_content(self, contents, **kwargs):
            return "alt-1\nalt-2\nalt-3"

    variants = await QueryTransformer(pool=_Pool()).transform("What patterns are in my notes?", QueryClass.THEMATIC)
    assert variants == ["What patterns are in my notes?", "alt-1", "alt-2", "alt-3"]


@pytest.mark.asyncio
async def test_step_back_generates_broader_form() -> None:
    class _Pool:
        async def generate_content(self, contents, **kwargs):
            return "broader question"

    variants = await QueryTransformer(pool=_Pool()).transform("How does this exact embedding config behave?", QueryClass.STEP_BACK)
    assert variants == ["How does this exact embedding config behave?", "broader question"]

