from website.features.rag_pipeline.ingest import chunker as chunker_module
from website.features.rag_pipeline.ingest.chunker import Chunk, ZettelChunker
from website.features.rag_pipeline.types import ChunkType, SourceType


def test_reddit_chunk_is_atomic_with_entity_prefix() -> None:
    chunker = ZettelChunker()

    chunks = chunker.chunk(
        source_type=SourceType.REDDIT,
        title="Thoughts on transformers",
        raw_text="This is a Reddit post about attention mechanisms.",
        tags=["transformers", "ml"],
        extra_metadata={"subreddit": "MachineLearning", "mentions": ["vaswani"]},
    )

    assert len(chunks) == 1
    assert chunks[0].chunk_type is ChunkType.ATOMIC
    assert "[Thoughts on transformers]" in chunks[0].content
    assert "#transformers #ml" in chunks[0].content
    assert "@MachineLearning" in chunks[0].content
    assert "@vaswani" in chunks[0].content
    assert "This is a Reddit post" in chunks[0].content


def test_youtube_long_form_uses_semantic_fallback_when_no_late_embedder(monkeypatch) -> None:
    chunker = ZettelChunker()
    expected = [
        Chunk(chunk_idx=0, content="semantic", chunk_type=ChunkType.SEMANTIC, token_count=1)
    ]
    monkeypatch.setattr(chunker, "_semantic_chunk", lambda raw_text, metadata: expected)

    chunks = chunker.chunk(
        source_type=SourceType.YOUTUBE,
        title="Video",
        raw_text="Long transcript",
        tags=[],
        extra_metadata={},
    )

    assert chunks == expected


def test_long_form_falls_through_to_recursive_if_semantic_fails(monkeypatch) -> None:
    chunker = ZettelChunker()
    expected = [
        Chunk(chunk_idx=0, content="recursive", chunk_type=ChunkType.RECURSIVE, token_count=1)
    ]
    monkeypatch.setattr(chunker, "_semantic_chunk", lambda raw_text, metadata: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(chunker, "_recursive_chunk", lambda raw_text, metadata: expected)

    chunks = chunker.chunk(
        source_type=SourceType.WEB,
        title="Article",
        raw_text="Long article body",
        tags=[],
        extra_metadata={},
    )

    assert chunks == expected


def test_long_form_falls_through_to_token_if_recursive_fails(monkeypatch) -> None:
    chunker = ZettelChunker()
    expected = [
        Chunk(chunk_idx=0, content="token", chunk_type=ChunkType.RECURSIVE, token_count=1)
    ]
    monkeypatch.setattr(chunker, "_semantic_chunk", lambda raw_text, metadata: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(chunker, "_recursive_chunk", lambda raw_text, metadata: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(chunker, "_token_chunk", lambda raw_text, metadata: expected)

    chunks = chunker.chunk(
        source_type=SourceType.MEDIUM,
        title="Essay",
        raw_text="Long essay body",
        tags=[],
        extra_metadata={},
    )

    assert chunks == expected


def test_short_form_never_uses_late_chunker(monkeypatch) -> None:
    chunker = ZettelChunker(embedder_for_late_chunking=object())
    monkeypatch.setattr(chunker, "_late_chunk", lambda raw_text, metadata: (_ for _ in ()).throw(AssertionError("late chunking should not run")))

    chunks = chunker.chunk(
        source_type=SourceType.GITHUB,
        title="Issue",
        raw_text="Bug report body",
        tags=["bug"],
        extra_metadata={},
    )

    assert len(chunks) == 1
    assert chunks[0].chunk_type is ChunkType.ATOMIC


def test_constructor_degrades_when_semantic_chunker_dependency_is_unavailable(monkeypatch) -> None:
    class BrokenSemanticChunker:
        def __init__(self, *args, **kwargs) -> None:
            raise ImportError("sentence_transformers unavailable")

    monkeypatch.setattr(chunker_module, "SemanticChunker", BrokenSemanticChunker)

    chunker = chunker_module.ZettelChunker()
    expected = [
        Chunk(chunk_idx=0, content="recursive", chunk_type=ChunkType.RECURSIVE, token_count=1)
    ]
    monkeypatch.setattr(chunker, "_recursive_chunk", lambda raw_text, metadata: expected)

    chunks = chunker.chunk(
        source_type=SourceType.WEB,
        title="Article",
        raw_text="Long article body",
        tags=[],
        extra_metadata={},
    )

    assert chunks == expected


def test_constructor_degrades_when_late_chunker_dependency_is_unavailable(monkeypatch) -> None:
    class BrokenLateChunker:
        def __init__(self, *args, **kwargs) -> None:
            raise ImportError("late chunker unavailable")

    monkeypatch.setattr(chunker_module, "LateChunker", BrokenLateChunker)

    chunker = chunker_module.ZettelChunker(embedder_for_late_chunking=object())
    expected = [
        Chunk(chunk_idx=0, content="recursive", chunk_type=ChunkType.RECURSIVE, token_count=1)
    ]
    monkeypatch.setattr(chunker, "_recursive_chunk", lambda raw_text, metadata: expected)

    chunks = chunker.chunk(
        source_type=SourceType.YOUTUBE,
        title="Transcript",
        raw_text="Long transcript body",
        tags=[],
        extra_metadata={},
    )

    assert chunks == expected
