from uuid import uuid4

from website.features.rag_pipeline.types import (
    ChatQuery,
    ChunkKind,
    QueryClass,
    RetrievalCandidate,
    ScopeFilter,
    SourceType,
)


def test_queryclass_values() -> None:
    assert {query_class.value for query_class in QueryClass} == {
        "lookup",
        "vague",
        "multi_hop",
        "thematic",
        "step_back",
    }


def test_scope_filter_default_tag_mode_is_all() -> None:
    assert ScopeFilter().tag_mode == "all"


def test_retrieval_candidate_fields() -> None:
    candidate = RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id="node-1",
        chunk_id=uuid4(),
        chunk_idx=0,
        name="Transformers",
        source_type=SourceType.WEB,
        url="https://example.com",
        content="content",
        rrf_score=0.5,
    )
    assert candidate.name == "Transformers"
    assert candidate.source_type is SourceType.WEB


def test_chat_query_default_quality_is_fast() -> None:
    query = ChatQuery(content="What did I save about embeddings?")
    assert query.quality == "fast"
    assert query.stream is True

