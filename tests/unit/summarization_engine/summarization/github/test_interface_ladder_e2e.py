"""Headline Wave-2 tests (Sol 3): the verified fabricated tokens are never
elevated to 'must-preserve'; a real manifest bin surfaces real commands; a
thin-API library lands on the defensible refusal-first overview."""
from __future__ import annotations

from website.features.summarization_engine.summarization.github.archetype import (
    RepoArchetype,
)
from website.features.summarization_engine.summarization.github.manifest_signals import (
    build_interface_verdict,
)
from website.features.summarization_engine.summarization.github.prompts import (
    source_context_for,
)
from website.features.summarization_engine.summarization.github.readme_signals import (
    extract_signals,
)

# A README that produces the verified fabrication tokens via the regexes.
_TOXIC_README = """Repository
ow/thin
README
# Thin

<sub>note</sub> <center>logo</center>

Please cite this work. See /center for details.
"""


def test_fabricated_tokens_not_must_preserve_for_thin_api_repo():
    signals = extract_signals(raw_text=_TOXIC_README, metadata={"language": "Python"})
    # No manifest -> refusal-first verdict.
    verdict = build_interface_verdict({}).as_metadata()
    ctx = source_context_for(RepoArchetype.LIBRARY_THIN, signals, verified_interface=verdict)
    lowered = ctx.lower()
    # The fabricated tokens must NOT be framed as must-preserve / verbatim.
    assert "must be preserved verbatim" not in lowered
    # If a fabricated token leaks into the heuristic block at all, it is
    # explicitly labelled optional ("include ONLY if ... otherwise OMIT").
    if "/sub" in ctx or "--please" in lowered or "/center" in ctx:
        assert "include only if" in lowered
    # And the authoritative interface statement is refusal-first.
    assert "no verified interface artifact" in lowered


def test_real_package_json_bin_surfaces_real_command():
    verdict = build_interface_verdict(
        {"package.json": '{"name": "eslint", "bin": "bin/eslint.js"}'}
    ).as_metadata()
    ctx = source_context_for(RepoArchetype.CLI_TOOL, None, verified_interface=verdict)
    assert "eslint" in ctx
    assert "verified cli interface" in ctx.lower()


def test_requests_like_library_lands_on_defensible_overview():
    # `requests`: real HTTP library, NO manifest bin -> refusal-first overview.
    requests_readme = """Repository
psf/requests
README
# Requests
Requests is a simple, yet elegant, HTTP library.
```python
import requests
r = requests.get('https://example.com')
```
Install with `pip install requests`.
"""
    signals = extract_signals(raw_text=requests_readme, metadata={"language": "Python"})
    verdict = build_interface_verdict({}).as_metadata()  # no machine-verified CLI/HTTP artifact
    ctx = source_context_for(RepoArchetype.LIBRARY_THIN, signals, verified_interface=verdict)
    lowered = ctx.lower()
    assert "no verified interface artifact" in lowered
    # Install command is still surfaced (legitimate, low-fabrication signal).
    assert "pip install requests" in ctx
