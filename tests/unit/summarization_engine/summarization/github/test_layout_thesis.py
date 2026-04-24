"""Tests for the GitHub Thesis cornerstone injection (P6).

Locks the contract that ``compose_github_detailed`` always returns an
Overview section whose ``sub_sections`` contains a non-empty single-sentence
``Thesis`` entry, deterministically derived from the validated payload —
no LLM calls, no hallucinated facts.
"""
from __future__ import annotations

from website.features.summarization_engine.summarization.github.layout import (
    _extract_thesis_from_detailed,
    compose_github_detailed,
)
from website.features.summarization_engine.summarization.github.schema import (
    GitHubDetailedSection,
    GitHubStructuredPayload,
)


_TERMINAL_PUNCT = (".", "!", "?")


def _assert_thesis_shape(thesis: str) -> None:
    assert isinstance(thesis, str)
    assert thesis, "Thesis must be a non-empty string"
    assert thesis.endswith(_TERMINAL_PUNCT), f"Thesis must end with terminal punct: {thesis!r}"
    # Single sentence: no internal sentence boundaries beyond the terminal one.
    interior = thesis.rstrip(".!?")
    for terminator in (". ", "! ", "? "):
        assert terminator not in interior, f"Thesis must be a single sentence: {thesis!r}"


def _assert_overview_has_thesis(sections, *, expected_first_key: str = "Thesis") -> str:
    overview = next(s for s in sections if s.heading == "Overview")
    assert "Thesis" in overview.sub_sections, "Overview.sub_sections must contain 'Thesis'"
    thesis_bullets = overview.sub_sections["Thesis"]
    assert len(thesis_bullets) == 1
    # Confirm Thesis is the first sub-section (Python 3.7+ dicts are ordered).
    first_key = next(iter(overview.sub_sections.keys()))
    assert first_key == expected_first_key, (
        f"Thesis must be the first sub-section, got: {first_key!r}"
    )
    _assert_thesis_shape(thesis_bullets[0])
    return thesis_bullets[0]


def test_thesis_happy_path_uses_architecture_overview_first_sentence():
    """When architecture_overview is present, thesis = its first sentence."""
    payload = GitHubStructuredPayload(
        mini_title="fastapi/fastapi",
        architecture_overview=(
            "FastAPI is an ASGI framework using pydantic for validation. "
            "It layers on top of Starlette for the request pipeline."
        ),
        brief_summary="High-performance Python API framework with type-safe routes.",
        tags=["fastapi", "python", "asgi", "starlette", "pydantic", "openapi", "webdev"],
        detailed_summary=[
            {
                "heading": "Routing",
                "bullets": ["APIRouter groups endpoints"],
                "module_or_feature": "routing",
                "main_stack": ["Starlette"],
                "public_interfaces": ["APIRouter"],
                "usability_signals": ["Type hints drive validation"],
            }
        ],
    )
    sections = compose_github_detailed(payload)
    thesis = _assert_overview_has_thesis(sections)
    assert thesis.startswith("FastAPI is an ASGI framework")


def test_thesis_fallback_uses_first_bullet_when_arch_overview_missing():
    """No architecture_overview → thesis falls back to first detailed bullet."""
    payload = GitHubStructuredPayload(
        mini_title="acme/widget",
        architecture_overview=(
            "Widget powers small embedded UIs with a documented public API surface."
        ),
        brief_summary="Embedded widget toolkit.",
        tags=["widget", "embedded", "ui", "toolkit", "library", "open-source", "documented"],
        detailed_summary=[
            GitHubDetailedSection(
                heading="Renderer",
                bullets=["The renderer paints to a 1-bit framebuffer at 60 fps."],
                module_or_feature="renderer",
                main_stack=["c"],
                public_interfaces=["Widget_Render"],
                usability_signals=["Single header include"],
            )
        ],
    )
    # Bypass validation to clear architecture_overview so branch 1 fails.
    cleared = payload.model_copy(update={"architecture_overview": ""})
    # model_copy still enforces field constraints on assignment? Pydantic v2
    # model_copy does NOT re-validate by default.
    thesis = _extract_thesis_from_detailed(cleared)
    _assert_thesis_shape(thesis)
    assert "renderer" in thesis.lower() or "framebuffer" in thesis.lower()


def test_thesis_skeleton_fallback_when_arch_and_bullets_empty():
    """Both architecture_overview and bullets empty → archetype skeleton."""
    payload = GitHubStructuredPayload(
        mini_title="acme/widget",
        architecture_overview=(
            "Widget powers small embedded UIs with a documented public API surface."
        ),
        brief_summary="Embedded widget toolkit and library for tiny screens.",
        tags=["widget", "embedded", "library", "toolkit", "open-source", "documented", "ui"],
        detailed_summary=[
            GitHubDetailedSection(
                heading="Overview",
                bullets=[],
                module_or_feature="overview",
                main_stack=[],
                public_interfaces=[],
                usability_signals=[],
            )
        ],
    )
    cleared = payload.model_copy(update={"architecture_overview": ""})
    thesis = _extract_thesis_from_detailed(cleared)
    _assert_thesis_shape(thesis)
    # Skeleton must reference the repo name; it never invents unrelated facts.
    assert "widget" in thesis.lower()


def test_thesis_final_skeleton_when_all_payload_signals_empty():
    """No mini_title repo half, no arch, no bullets → deterministic constant."""
    payload = GitHubStructuredPayload(
        mini_title="acme/widget",
        architecture_overview=(
            "Widget powers small embedded UIs with a documented public API surface."
        ),
        brief_summary="",
        tags=["widget", "embedded", "library", "toolkit", "open-source", "documented", "ui"],
        detailed_summary=[
            GitHubDetailedSection(
                heading="Overview",
                bullets=[],
                module_or_feature="overview",
                main_stack=[],
                public_interfaces=[],
                usability_signals=[],
            )
        ],
    )
    # Wipe both architecture_overview AND mini_title's repo half to force the
    # final skeleton branch.
    cleared = payload.model_copy(update={"architecture_overview": "", "mini_title": "x/"})
    thesis = _extract_thesis_from_detailed(cleared)
    _assert_thesis_shape(thesis)
