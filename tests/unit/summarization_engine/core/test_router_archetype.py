"""Tests for the archetype/format router wrappers.

Cover both happy paths (the underlying classifier emits a confident label)
and the safe no-op paths (None / empty input falls back to a documented
default). The underlying classifiers are deliberately NOT mocked — they are
deterministic and cheap, so calling them for real proves the wrapper actually
delegates correctly.
"""
from __future__ import annotations

from website.features.summarization_engine.core.router import (
    classify_github_archetype,
    classify_youtube_format,
)
from website.features.summarization_engine.summarization.youtube.format_classifier import (
    FORMAT_LABELS,
)


# ---------------------------------------------------------------------------
# YouTube format classifier wrapper
# ---------------------------------------------------------------------------


def test_classify_youtube_format_lecture_signal():
    transcript = (
        "Welcome to today's lecture. The professor will walk through the "
        "syllabus, the chapter on linear algebra, and the theorem we proved "
        "in seminar last week. Slides are available on the course site."
    )
    label, confidence = classify_youtube_format(transcript)
    assert label == "lecture"
    assert label in FORMAT_LABELS
    assert 0.0 < confidence <= 1.0


def test_classify_youtube_format_explainer_signal():
    transcript = (
        "In this tutorial we'll do a step-by-step walkthrough of how to "
        "configure the tool. This explainer is aimed at beginners — by the "
        "end you'll have a working demo."
    )
    label, confidence = classify_youtube_format(transcript)
    assert label == "explainer"
    assert confidence > 0.0


def test_classify_youtube_format_empty_returns_default_with_zero_confidence():
    label, confidence = classify_youtube_format("")
    assert label == "commentary"
    assert confidence == 0.0


def test_classify_youtube_format_none_returns_default_with_zero_confidence():
    label, confidence = classify_youtube_format(None)
    assert label == "commentary"
    assert confidence == 0.0


def test_classify_youtube_format_whitespace_only_treated_as_empty():
    label, confidence = classify_youtube_format("   \n\t  ")
    assert label == "commentary"
    assert confidence == 0.0


# ---------------------------------------------------------------------------
# GitHub archetype classifier wrapper
# ---------------------------------------------------------------------------


def test_classify_github_archetype_cli_tool_signal():
    metadata = {
        "raw_text": (
            "# coolcli\n\n"
            "A command-line tool built with click.\n\n"
            "## Install\n\n"
            "    pip install coolcli\n\n"
            "## Usage\n\n"
            "    $ coolcli --help\n"
            "    $ coolcli run --verbose\n"
        ),
        "topics": ["cli", "command-line-tool"],
        "language": "python",
    }
    archetype = classify_github_archetype(metadata)
    assert archetype == "cli_tool"


def test_classify_github_archetype_framework_signal():
    metadata = {
        "raw_text": (
            "# webly\n\n"
            "An ASGI web framework with middleware, routes, and openapi "
            "support. Inspired by starlette and uvicorn.\n\n"
            "    @app.get('/items')\n"
            "    def list_items(): ...\n\n"
            "    @app.post('/items')\n"
            "    def create_item(): ...\n"
        ),
        "topics": ["web-framework", "asgi"],
        "language": "python",
    }
    archetype = classify_github_archetype(metadata)
    assert archetype == "framework_api"


def test_classify_github_archetype_empty_dict_returns_library_default():
    assert classify_github_archetype({}) == "library_thin"


def test_classify_github_archetype_none_returns_library_default():
    assert classify_github_archetype(None) == "library_thin"


def test_classify_github_archetype_non_dict_returns_library_default():
    # Pydantic models / lists / strings are common accidental call shapes.
    assert classify_github_archetype("github.com/foo/bar") == "library_thin"  # type: ignore[arg-type]
    assert classify_github_archetype(["raw_text", "..."]) == "library_thin"  # type: ignore[arg-type]


def test_classify_github_archetype_empty_raw_text_returns_default():
    metadata = {"raw_text": "   ", "topics": [], "language": ""}
    assert classify_github_archetype(metadata) == "library_thin"


def test_classify_github_archetype_uses_readme_or_description_fallback():
    # When raw_text is absent, the wrapper should fall back to readme/description.
    md_readme = {"readme": "A command-line tool. $ mytool --flag value\n[project.scripts]"}
    assert classify_github_archetype(md_readme) == "cli_tool"

    md_description = {
        "description": "An ASGI web framework with middleware and routes and openapi.",
        "topics": ["web-framework"],
    }
    assert classify_github_archetype(md_description) == "framework_api"
