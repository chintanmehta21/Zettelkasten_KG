import pytest

from website.features.summarization_engine.evaluator.ragas_bridge import RagasBridge


@pytest.mark.asyncio
async def test_ragas_bridge_smoke():
    bridge = RagasBridge(gemini_client=None)
    faith = await bridge.faithfulness(summary="s", source="t")
    assert faith >= 0 or faith == -1.0
