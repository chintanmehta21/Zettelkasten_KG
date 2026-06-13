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


from website.features.summarization_engine.summarization.github.archetype import (
    RepoArchetype,
)
from website.features.summarization_engine.summarization.github.prompts import (
    _signals_slot,
    source_context_for,
)
from website.features.summarization_engine.summarization.github.readme_signals import (
    ReadmeSignals,
)


def _bogus_signals() -> ReadmeSignals:
    # The verified fabrication tokens, exactly as the README regex emits them.
    return ReadmeSignals(
        install_cmds=("pip install requests",),
        endpoints=("/sub", "/center"),
        cli_flags=("--Please",),
        decorators=(),
        inline_code=(),
        first_code_block="",
        stack=("Python",),
        purpose_sentence="",
    )


def test_signals_slot_demotes_surface_to_corroboration():
    """M2: README-regex surfaces must NOT be framed as 'must be preserved
    verbatim'. They become corroboration-only."""
    out = _signals_slot(_bogus_signals(), verified_interface=None)
    lowered = out.lower()
    # The must-preserve framing is gone for surfaces.
    assert "must be preserved verbatim" not in lowered
    # Corroboration framing is present (the regex output is now optional/checked).
    assert "corrobor" in lowered or "only if" in lowered or "verify against" in lowered


def test_signals_slot_refusal_first_when_no_verified_interface():
    """M1: with no verified artifact, the slot states the refusal-first label."""
    out = _signals_slot(_bogus_signals(), verified_interface=None)
    assert "no verified interface artifact" in out.lower()


def test_signals_slot_uses_verified_label_on_artifact_hit():
    """M1: a HIGH-rung manifest hit flips to the verified-surface label and
    names the real command(s)."""
    vi = {
        "verified": True,
        "commands": ["eslint"],
        "kind": "cli",
        "label": "verified CLI interface — command(s): eslint",
        "source_files": ["package.json"],
    }
    out = _signals_slot(_bogus_signals(), verified_interface=vi)
    assert "verified cli interface" in out.lower()
    assert "eslint" in out
    # Even when verified, the bogus regex tokens are never elevated to verbatim.
    assert "must be preserved verbatim" not in out.lower()


def test_source_context_threads_verified_interface():
    vi = {"verified": True, "commands": ["rg"], "kind": "cli",
          "label": "verified CLI interface — command(s): rg", "source_files": ["cargo.toml"]}
    ctx = source_context_for(RepoArchetype.CLI_TOOL, _bogus_signals(), verified_interface=vi)
    assert "rg" in ctx
    assert "verified cli interface" in ctx.lower()


def test_source_context_refusal_first_default():
    ctx = source_context_for(RepoArchetype.LIBRARY_THIN, _bogus_signals(), verified_interface=None)
    assert "no verified interface artifact" in ctx.lower()
