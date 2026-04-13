"""Live integration test for the cascade reranker."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from website.features.rag_pipeline.rerank.cascade import CascadeReranker
from website.features.rag_pipeline.types import ChunkKind, RetrievalCandidate, SourceType


pytestmark = pytest.mark.live


def _candidate(
    node_id: str,
    content: str,
    *,
    rrf: float = 0.3,
    graph: float = 0.2,
    source_type: SourceType = SourceType.WEB,
) -> RetrievalCandidate:
    candidate = RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id=node_id,
        chunk_id=uuid4(),
        chunk_idx=0,
        name=f"Note: {node_id}",
        source_type=source_type,
        url=f"https://example.com/{node_id}",
        content=content,
        rrf_score=rrf,
    )
    candidate.graph_score = graph
    return candidate


@pytest.fixture(scope="module")
def model_dir() -> str:
    value = os.environ.get("RAG_MODEL_DIR")
    if not value:
        pytest.skip("Set RAG_MODEL_DIR to a directory containing FlashRank and exported BGE ONNX models.")
    return value


@pytest.mark.asyncio
async def test_live_rerank_prefers_relevant_transformer_content(model_dir: str) -> None:
    reranker = CascadeReranker(model_dir=model_dir, stage1_k=4)
    candidates = [
        _candidate(
            "relevant",
            "Transformers use self-attention to let each token attend to every other token in the sequence.",
            rrf=0.2,
            source_type=SourceType.WEB,
        ),
        _candidate(
            "irrelevant",
            "Spring weather in Paris is mild and rainy, with temperatures around fifteen degrees Celsius.",
            rrf=0.5,
            source_type=SourceType.REDDIT,
        ),
    ]

    ranked = await reranker.rerank("How does self-attention work in transformers?", candidates, top_k=2)

    assert len(ranked) == 2
    assert ranked[0].node_id == "relevant"
    assert all(candidate.final_score is not None for candidate in ranked)
