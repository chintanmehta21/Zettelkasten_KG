"""Tests for the metadata header prepended to cross-encoder passage text."""

from __future__ import annotations

from website.features.rag_pipeline.rerank.cascade import _passage_text
from website.features.rag_pipeline.types import ChunkKind, RetrievalCandidate, SourceType


def _make(
    source: SourceType,
    author: str | None,
    ts: str | None,
    tags: list[str],
    name: str,
    content: str,
) -> RetrievalCandidate:
    metadata: dict = {}
    if author is not None:
        metadata["author"] = author
    if ts is not None:
        metadata["timestamp"] = ts
    return RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id="n",
        chunk_idx=0,
        name=name,
        source_type=source,
        url="https://example.test/x",
        content=content,
        tags=tags,
        metadata=metadata,
    )


def test_header_includes_source_author_date_tags():
    c = _make(
        SourceType.YOUTUBE,
        "Andrej Karpathy",
        "2023-10-12",
        ["transformers", "vision"],
        "AKL Talk",
        "Body content here.",
    )
    text = _passage_text(c)
    first_line = text.split("\n")[0]
    assert first_line.startswith("[")
    assert first_line.endswith("]")
    assert "source=youtube" in first_line
    assert "author=Andrej Karpathy" in first_line
    assert "date=2023-10-12" in first_line
    assert "tags=transformers,vision" in first_line


def test_header_present_with_minimal_metadata():
    c = _make(SourceType.WEB, None, None, [], "Page", "x")
    text = _passage_text(c)
    first_line = text.split("\n")[0]
    assert first_line.startswith("[source=web")
    # No broken `None` tokens for missing fields.
    assert "None" not in first_line
    assert "author=" not in first_line
    assert "date=" not in first_line
    assert "tags=" not in first_line


def test_body_preserved_after_header():
    body = "This is the verbatim body content that must survive."
    c = _make(SourceType.GITHUB, "octocat", "2024-01-02T03:04:05Z", ["ml"], "Repo", body)
    text = _passage_text(c)
    # Body must appear verbatim somewhere after the header.
    assert body in text
    # Header is the first line and body is not the first line.
    assert text.split("\n", 1)[0].startswith("[")
    # Date is truncated to YYYY-MM-DD slice.
    assert "date=2024-01-02" in text.split("\n")[0]


def test_header_is_deterministic():
    c1 = _make(
        SourceType.SUBSTACK,
        "Jane Doe",
        "2025-03-04",
        ["ai", "policy"],
        "Note",
        "Body.",
    )
    c2 = _make(
        SourceType.SUBSTACK,
        "Jane Doe",
        "2025-03-04",
        ["ai", "policy"],
        "Note",
        "Body.",
    )
    assert _passage_text(c1) == _passage_text(c2)


def test_channel_used_when_author_missing():
    c = RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id="n",
        chunk_idx=0,
        name="Vid",
        source_type=SourceType.YOUTUBE,
        url="https://youtu.be/x",
        content="Body.",
        tags=[],
        metadata={"channel": "Lex Fridman"},
    )
    first_line = _passage_text(c).split("\n")[0]
    assert "author=Lex Fridman" in first_line


def test_tags_capped_at_five():
    c = _make(
        SourceType.WEB,
        None,
        None,
        ["a", "b", "c", "d", "e", "f", "g"],
        "T",
        "Body",
    )
    first_line = _passage_text(c).split("\n")[0]
    assert "tags=a,b,c,d,e" in first_line
    assert ",f" not in first_line
