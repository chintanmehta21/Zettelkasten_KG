import pytest
from unittest.mock import AsyncMock, patch
from website.features.rag_pipeline.query.transformer import QueryTransformer
from website.features.rag_pipeline.types import QueryClass

@pytest.mark.asyncio
async def test_thematic_default_is_n_3():
    """iter-08 Phase 1: THEMATIC default n is 3, not 5."""
    t = QueryTransformer()
    captured = {}
    async def fake_multi(query, n, entities=None):
        captured["n"] = n
        return [f"variant{i}" for i in range(n)]
    with patch.object(t, "_multi_query", AsyncMock(side_effect=fake_multi)):
        await t.transform("test thematic query", QueryClass.THEMATIC)
    assert captured["n"] == 3, f"expected default n=3, got {captured['n']}"
