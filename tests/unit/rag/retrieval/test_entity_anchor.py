import pytest
from unittest.mock import MagicMock
from website.features.rag_pipeline.retrieval.entity_anchor import resolve_anchor_nodes


@pytest.mark.asyncio
async def test_resolve_anchor_walker():
    """'Walker' resolves to the yt-matt-walker-sleep-depriv zettel via fuzzy title match."""
    fake_supabase = MagicMock()
    fake_supabase.rpc.return_value.execute.return_value.data = [
        {"node_id": "yt-matt-walker-sleep-depriv", "title": "Matt Walker on Sleep Deprivation"},
    ]
    result = await resolve_anchor_nodes(["Walker"], sandbox_id="kasten1", supabase=fake_supabase)
    assert "yt-matt-walker-sleep-depriv" in result
