"""Tests for the GitHub graceful-fallback payload builder.

Prior eval loops 05-09 showed that structured schema failure on repos like
`psf/requests` and `tiangolo/typer` zeroed the brief/detailed/tags (composite
~14-30) and dragged held-out means far below the 88 gate. This suite locks in
the graceful-fallback contract: on schema failure the summarizer must still
emit a canonical owner/repo label, README-grounded brief, archetype-appropriate
tags, and a valid GitHubStructuredPayload.
"""
from __future__ import annotations

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.summarization.github.archetype import (
    RepoArchetype,
)
from website.features.summarization_engine.summarization.github.readme_signals import (
    extract_signals,
)
from website.features.summarization_engine.summarization.github.schema import (
    GitHubStructuredPayload,
)
from website.features.summarization_engine.summarization.github.summarizer import (
    _build_graceful_fallback,
    _canonical_owner_repo,
    _fallback_tags,
)


def _ingest(url: str, *, metadata: dict, raw_text: str) -> IngestResult:
    return IngestResult(
        source_type=SourceType.GITHUB,
        url=url,
        original_url=url,
        raw_text=raw_text,
        extraction_confidence="high",
        confidence_reason="ok",
        fetched_at="2026-04-23T00:00:00+00:00",
        metadata=metadata,
    )


def test_canonical_owner_repo_prefers_metadata_full_name():
    ingest = _ingest(
        "https://github.com/psf/requests",
        metadata={"full_name": "psf/requests"},
        raw_text="",
    )
    assert _canonical_owner_repo(ingest) == "psf/requests"


def test_canonical_owner_repo_falls_back_to_url_parse():
    ingest = _ingest(
        "https://github.com/tiangolo/typer",
        metadata={},
        raw_text="",
    )
    assert _canonical_owner_repo(ingest) == "tiangolo/typer"


def test_fallback_tags_produce_language_and_archetype_tags():
    signals = extract_signals(
        raw_text="pip install requests\n\nimport requests",
        metadata={"language": "Python"},
    )
    tags = _fallback_tags(archetype=RepoArchetype.LIBRARY_THIN, signals=signals)
    assert "python" in tags
    assert "library" in tags
    assert 7 <= len(tags) <= 10


def test_graceful_fallback_produces_valid_payload_for_requests_like_repo():
    raw = """Repository
psf/requests
Python HTTP for Humans.

README
# Requests

Requests is a simple, yet elegant, HTTP library.

```python
import requests
r = requests.get('https://example.com')
```

Install with `pip install requests`.
"""
    ingest = _ingest(
        "https://github.com/psf/requests",
        metadata={"full_name": "psf/requests", "language": "Python"},
        raw_text=raw,
    )
    signals = extract_signals(raw_text=raw, metadata=ingest.metadata)

    payload = _build_graceful_fallback(
        ingest=ingest,
        summary_text="Requests is a simple HTTP library for Python.",
        archetype=RepoArchetype.LIBRARY_THIN,
        signals=signals,
    )

    assert isinstance(payload, GitHubStructuredPayload)
    assert payload.mini_title == "psf/requests"
    assert "python" in payload.tags
    assert "library" in payload.tags
    assert 7 <= len(payload.tags) <= 10
    assert len(payload.detailed_summary) >= 1
    # Brief must NOT be empty and must reference install or HTTP
    assert payload.brief_summary
    lower = payload.brief_summary.lower()
    assert "requests" in lower or "http" in lower or "pip install" in lower


def test_graceful_fallback_produces_valid_payload_for_cli_repo():
    raw = """Repository
tiangolo/typer
Typer, build great CLIs.

README
# Typer

Typer is a library for building CLI applications with Python type hints.

```python
import typer
app = typer.Typer()

@app.command()
def hello(name: str):
    typer.echo(f"Hello {name}")
```

Install with `pip install typer`. Run `script.py --help` to see usage.
"""
    ingest = _ingest(
        "https://github.com/tiangolo/typer",
        metadata={"full_name": "tiangolo/typer", "language": "Python"},
        raw_text=raw,
    )
    signals = extract_signals(raw_text=raw, metadata=ingest.metadata)

    payload = _build_graceful_fallback(
        ingest=ingest,
        summary_text="Typer is a CLI-building library based on Python type hints.",
        archetype=RepoArchetype.CLI_TOOL,
        signals=signals,
    )

    assert payload.mini_title == "tiangolo/typer"
    assert "cli-tool" in payload.tags
    assert payload.brief_summary
    # Detailed section must carry surfaces / install bullets
    assert payload.detailed_summary[0].bullets


def test_graceful_fallback_brief_stays_within_char_cap():
    ingest = _ingest(
        "https://github.com/owner/repo",
        metadata={"full_name": "owner/repo", "language": "Python"},
        raw_text="README\n# Project\n\nA small library.\n\n```python\nimport x\n```",
    )
    signals = extract_signals(raw_text=ingest.raw_text, metadata=ingest.metadata)
    payload = _build_graceful_fallback(
        ingest=ingest,
        summary_text="Minimal summary text.",
        archetype=RepoArchetype.LIBRARY_THIN,
        signals=signals,
    )
    # GitHubStructuredPayload does not hard-cap brief_summary, but the rebuilder
    # should stay within the rubric target window (<=400 chars).
    assert len(payload.brief_summary) <= 400
    # Architecture overview must satisfy the 50-500 char schema bound
    assert 50 <= len(payload.architecture_overview) <= 500
