"""iter-09 RES-7 / Q10: anchor-seed RPC client tests."""
import pytest

from website.features.rag_pipeline.retrieval.anchor_seed import fetch_anchor_seeds


class _Stub:
    def __init__(self, rows):
        self._rows = rows
        self.last_call: tuple[str, dict] | None = None

    def rpc(self, name, params):
        self.last_call = (name, params)
        assert name == "rag_fetch_anchor_seeds"
        assert "p_sandbox_id" in params and "p_anchor_nodes" in params and "p_query_embedding" in params
        return self

    def execute(self):
        rows = self._rows

        class R:
            data = rows

        return R()


@pytest.mark.asyncio
async def test_returns_seeds_when_rpc_succeeds():
    stub = _Stub([{"node_id": "yt-x", "score": 0.42}])
    seeds = await fetch_anchor_seeds(
        ["jobs"],
        "00000000-0000-0000-0000-000000000000",
        [0.1] * 768,
        stub,
    )
    assert seeds == [{"node_id": "yt-x", "score": 0.42}]


@pytest.mark.asyncio
async def test_empty_anchors_returns_empty():
    stub = _Stub([{"node_id": "yt-x", "score": 0.42}])
    seeds = await fetch_anchor_seeds(
        [],
        "00000000-0000-0000-0000-000000000000",
        [0.1] * 768,
        stub,
    )
    assert seeds == []


@pytest.mark.asyncio
async def test_rpc_exception_returns_empty():
    class Bad:
        def rpc(self, *a, **k):
            raise RuntimeError("boom")

    seeds = await fetch_anchor_seeds(
        ["jobs"],
        "00000000-0000-0000-0000-000000000000",
        [0.1] * 768,
        Bad(),
    )
    assert seeds == []
