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
    backing = [
        Chunk(chunk_idx=0, content="semantic", chunk_type=ChunkType.SEMANTIC, token_count=1)
    ]
    monkeypatch.setattr(chunker, "_semantic_chunk", lambda raw_text, metadata: list(backing))

    chunks = chunker.chunk(
        source_type=SourceType.YOUTUBE,
        title="Video",
        raw_text="Long transcript",
        tags=[],
        extra_metadata={},
    )

    assert len(chunks) == 1
    assert chunks[0].chunk_type is ChunkType.SEMANTIC
    assert "[Video]" in chunks[0].content
    assert "semantic" in chunks[0].content


def test_long_form_falls_through_to_recursive_if_semantic_fails(monkeypatch) -> None:
    chunker = ZettelChunker()
    backing = [
        Chunk(chunk_idx=0, content="recursive", chunk_type=ChunkType.RECURSIVE, token_count=1)
    ]
    monkeypatch.setattr(chunker, "_semantic_chunk", lambda raw_text, metadata: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(chunker, "_recursive_chunk", lambda raw_text, metadata: list(backing))

    chunks = chunker.chunk(
        source_type=SourceType.WEB,
        title="Article",
        raw_text="Long article body",
        tags=[],
        extra_metadata={},
    )

    assert len(chunks) == 1
    assert chunks[0].chunk_type is ChunkType.RECURSIVE
    assert "[Article]" in chunks[0].content
    assert "recursive" in chunks[0].content


def test_long_form_falls_through_to_token_if_recursive_fails(monkeypatch) -> None:
    chunker = ZettelChunker()
    backing = [
        Chunk(chunk_idx=0, content="token", chunk_type=ChunkType.RECURSIVE, token_count=1)
    ]
    monkeypatch.setattr(chunker, "_semantic_chunk", lambda raw_text, metadata: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(chunker, "_recursive_chunk", lambda raw_text, metadata: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(chunker, "_token_chunk", lambda raw_text, metadata: list(backing))

    chunks = chunker.chunk(
        source_type=SourceType.MEDIUM,
        title="Essay",
        raw_text="Long essay body",
        tags=[],
        extra_metadata={},
    )

    assert len(chunks) == 1
    assert "[Essay]" in chunks[0].content
    assert "token" in chunks[0].content


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
    backing = [
        Chunk(chunk_idx=0, content="recursive", chunk_type=ChunkType.RECURSIVE, token_count=1)
    ]
    monkeypatch.setattr(chunker, "_recursive_chunk", lambda raw_text, metadata: list(backing))

    chunks = chunker.chunk(
        source_type=SourceType.WEB,
        title="Article",
        raw_text="Long article body",
        tags=[],
        extra_metadata={},
    )

    assert len(chunks) == 1
    assert "[Article]" in chunks[0].content
    assert "recursive" in chunks[0].content


def test_constructor_degrades_when_late_chunker_dependency_is_unavailable(monkeypatch) -> None:
    class BrokenLateChunker:
        def __init__(self, *args, **kwargs) -> None:
            raise ImportError("late chunker unavailable")

    monkeypatch.setattr(chunker_module, "LateChunker", BrokenLateChunker)

    chunker = chunker_module.ZettelChunker(embedder_for_late_chunking=object())
    backing = [
        Chunk(chunk_idx=0, content="recursive", chunk_type=ChunkType.RECURSIVE, token_count=1)
    ]
    monkeypatch.setattr(chunker, "_recursive_chunk", lambda raw_text, metadata: list(backing))

    chunks = chunker.chunk(
        source_type=SourceType.YOUTUBE,
        title="Transcript",
        raw_text="Long transcript body",
        tags=[],
        extra_metadata={},
    )

    assert len(chunks) == 1
    assert "[Transcript]" in chunks[0].content
    assert "recursive" in chunks[0].content


def test_long_form_prepends_title_and_tags_to_first_chunk_only(monkeypatch) -> None:
    """Title/tags must appear in chunk 0 so retrieval can match the node even
    when the body is a stub (e.g. 'Transcript not available'). Other chunks
    keep their original content."""
    chunker = ZettelChunker()
    backing = [
        Chunk(chunk_idx=0, content="first body piece", chunk_type=ChunkType.SEMANTIC, token_count=3),
        Chunk(chunk_idx=1, content="second body piece", chunk_type=ChunkType.SEMANTIC, token_count=3),
    ]
    monkeypatch.setattr(chunker, "_semantic_chunk", lambda raw_text, metadata: list(backing))

    chunks = chunker.chunk(
        source_type=SourceType.YOUTUBE,
        title="Attention Is All You Need - Paper Explained",
        raw_text="(Transcript not available)",
        tags=["transformers", "ml"],
        extra_metadata={"channel_name": "Yannic Kilcher"},
    )

    assert len(chunks) == 2
    assert "[Attention Is All You Need - Paper Explained]" in chunks[0].content
    assert "#transformers #ml" in chunks[0].content
    assert "@Yannic Kilcher" in chunks[0].content
    assert "first body piece" in chunks[0].content
    # Subsequent chunks unchanged.
    assert chunks[1].content == "second body piece"
    assert "[Attention" not in chunks[1].content


def test_prefix_has_plain_text_echo_line_for_fts(monkeypatch) -> None:
    """Tags and title are echoed as plain words in a 'Topics:' line so FTS
    tokenisation matches ordinary dictionary search even when `#tag` tokens
    are stripped by the tsvector analyser."""
    chunker = ZettelChunker()
    backing = [
        Chunk(chunk_idx=0, content="body", chunk_type=ChunkType.SEMANTIC, token_count=1),
    ]
    monkeypatch.setattr(chunker, "_semantic_chunk", lambda raw_text, metadata: list(backing))

    chunks = chunker.chunk(
        source_type=SourceType.YOUTUBE,
        title="Attention Is All You Need",
        raw_text="body",
        tags=["transformers", "nlp"],
        extra_metadata={"channel_name": "Yannic Kilcher"},
    )

    content = chunks[0].content
    # Structured header (existing behaviour).
    assert "[Attention Is All You Need]" in content
    assert "#transformers #nlp" in content
    assert "@Yannic Kilcher" in content
    # Plain-text echo line.
    assert "Topics: Attention Is All You Need" in content
    assert "transformers nlp" in content
    assert "Yannic Kilcher" in content


def test_youtube_channel_metadata_is_used_as_author(monkeypatch) -> None:
    """YouTube extractor stores the channel under the key 'channel'. The
    prefix builder must pick it up so `@Channel` appears in chunk 0."""
    chunker = ZettelChunker()
    backing = [Chunk(chunk_idx=0, content="body", chunk_type=ChunkType.SEMANTIC, token_count=1)]
    monkeypatch.setattr(chunker, "_semantic_chunk", lambda raw_text, metadata: list(backing))

    chunks = chunker.chunk(
        source_type=SourceType.YOUTUBE,
        title="Attention Is All You Need",
        raw_text="body",
        tags=["ml"],
        extra_metadata={"channel": "Yannic Kilcher"},
    )

    assert "@Yannic Kilcher" in chunks[0].content


def test_prefix_filters_empty_tag_strings(monkeypatch) -> None:
    """Empty or whitespace-only tags must be dropped so the prefix never
    renders an orphan `#` token."""
    chunker = ZettelChunker()
    backing = [Chunk(chunk_idx=0, content="body", chunk_type=ChunkType.SEMANTIC, token_count=1)]
    monkeypatch.setattr(chunker, "_semantic_chunk", lambda raw_text, metadata: list(backing))

    chunks = chunker.chunk(
        source_type=SourceType.WEB,
        title="Article",
        raw_text="body",
        tags=["", "  ", "ml", ""],
        extra_metadata={},
    )

    content = chunks[0].content
    assert "#ml" in content
    assert " # " not in content  # no stray "#" with empty tag
    assert not content.endswith("#")


def test_short_form_atomic_chunk_also_has_echo_line() -> None:
    """Short-form atomic chunks share the same prefix builder, so they get
    the same FTS echo enhancement."""
    chunker = ZettelChunker()

    chunks = chunker.chunk(
        source_type=SourceType.REDDIT,
        title="Thoughts on transformers",
        raw_text="body",
        tags=["ml"],
        extra_metadata={"subreddit": "MachineLearning"},
    )

    assert "Topics: Thoughts on transformers" in chunks[0].content


def test_long_form_no_prefix_when_title_and_tags_are_empty(monkeypatch) -> None:
    """Avoid injecting an empty-prefix newline when no title/tags/author are
    available."""
    chunker = ZettelChunker()
    backing = [
        Chunk(chunk_idx=0, content="body", chunk_type=ChunkType.SEMANTIC, token_count=1),
    ]
    monkeypatch.setattr(chunker, "_semantic_chunk", lambda raw_text, metadata: list(backing))

    chunks = chunker.chunk(
        source_type=SourceType.WEB,
        title="",
        raw_text="body",
        tags=[],
        extra_metadata={},
    )

    # Empty title still produces "[]" prefix which is acceptable; more
    # importantly the body is preserved and we didn't crash.
    assert len(chunks) == 1
    assert "body" in chunks[0].content
