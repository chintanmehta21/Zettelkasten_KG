"""Tests for archetype-tuned GitHub prompt variants.

Locks the contract that ``select_github_prompt`` returns archetype-specific
focus prefixes prepended to ``STRUCTURED_EXTRACT_INSTRUCTION`` for each known
archetype, while ``"unknown"`` and bogus labels fall through to the unmodified
base instruction.
"""
from __future__ import annotations

import pytest

from website.features.summarization_engine.summarization.github.prompts import (
    STRUCTURED_EXTRACT_INSTRUCTION,
    _ARCHETYPE_FOCUS,
    select_github_prompt,
)


# (archetype, keyword that MUST appear case-insensitively in the focus block)
_ARCHETYPE_KEYWORDS = [
    ("library_thin", "API"),
    ("framework_api", "middleware"),
    ("cli_tool", "subcommands"),
    ("docs_heavy", "docs/"),
    ("app_example", "deployable"),
]


@pytest.mark.parametrize("archetype,keyword", _ARCHETYPE_KEYWORDS)
def test_known_archetype_returns_longer_prompt_with_keyword(
    archetype: str, keyword: str
) -> None:
    """Each known archetype yields a prompt longer than the base, containing
    its archetype-specific keyword."""
    out = select_github_prompt(archetype)
    assert len(out) > len(STRUCTURED_EXTRACT_INSTRUCTION), (
        f"Archetype {archetype!r} did not extend the base instruction"
    )
    assert keyword.lower() in out.lower(), (
        f"Archetype {archetype!r} prompt missing required keyword {keyword!r}"
    )
    # Library_thin specifically must mention API or interface (per spec).
    if archetype == "library_thin":
        lowered = out.lower()
        assert "api" in lowered or "interface" in lowered


def test_library_thin_mentions_api_or_interface() -> None:
    """Spec requirement: library_thin focus block must reference API/interface."""
    out = select_github_prompt("library_thin")
    lowered = out.lower()
    assert "api" in lowered or "interface" in lowered


def test_unknown_archetype_returns_base_unchanged() -> None:
    """The literal string ``"unknown"`` falls through to the base instruction."""
    assert select_github_prompt("unknown") == STRUCTURED_EXTRACT_INSTRUCTION


def test_nonsense_archetype_falls_back_to_base() -> None:
    """Unknown labels (typos, junk) gracefully fall back to the base prompt."""
    assert select_github_prompt("nonsense_archetype") == STRUCTURED_EXTRACT_INSTRUCTION
    assert select_github_prompt("") == STRUCTURED_EXTRACT_INSTRUCTION
    assert select_github_prompt(None) == STRUCTURED_EXTRACT_INSTRUCTION


@pytest.mark.parametrize("archetype,_kw", _ARCHETYPE_KEYWORDS)
def test_focus_block_is_prepended_not_appended(archetype: str, _kw: str) -> None:
    """Round-trip: the focus block must START the returned prompt so it shapes
    how the model interprets the schema instructions that follow.

    We assert that (1) the focus block is the literal prefix, (2) the base
    instruction appears strictly after, and (3) the focus block does NOT
    appear after the base instruction.
    """
    focus = _ARCHETYPE_FOCUS[archetype]
    out = select_github_prompt(archetype)

    assert out.startswith(focus), (
        f"Focus block for {archetype!r} is not at the start of the prompt"
    )
    base_idx = out.find(STRUCTURED_EXTRACT_INSTRUCTION)
    focus_idx = out.find(focus)
    assert focus_idx == 0
    assert base_idx > focus_idx, (
        f"Base instruction should appear after focus block for {archetype!r}"
    )
    # Focus should not also be appended after the base.
    assert out.count(focus) == 1


def test_focus_blocks_under_word_budget() -> None:
    """Each focus block must stay under 80 words per spec."""
    for archetype, block in _ARCHETYPE_FOCUS.items():
        word_count = len(block.split())
        assert word_count < 80, (
            f"Archetype {archetype!r} focus block has {word_count} words "
            "(spec: under 80)"
        )


def test_all_known_archetypes_have_focus_blocks() -> None:
    """Every non-unknown RepoArchetype value must have a focus block."""
    from website.features.summarization_engine.summarization.github.archetype import (
        RepoArchetype,
    )

    for arch in RepoArchetype:
        if arch == RepoArchetype.UNKNOWN:
            continue
        assert arch.value in _ARCHETYPE_FOCUS, (
            f"Missing focus block for archetype {arch.value!r}"
        )
