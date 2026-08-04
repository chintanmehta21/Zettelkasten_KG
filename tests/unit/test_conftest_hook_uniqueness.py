"""Guard: tests/conftest.py must define each pytest hook exactly once.

2026-08-04 regression. The known-failure ratchet was added as a SECOND
``pytest_collection_modifyitems`` in tests/conftest.py, with a docstring
asserting that "pytest calls EVERY conftest hook of the same name, so this
coexists with the --e2e deselection hook above". That is false. pytest collects
one hook implementation per *plugin module*, and Python had already rebound the
name to the later def — so the earlier ``--e2e`` deselection hook simply stopped
existing.

Consequence: Playwright tests were no longer deselected, ran on a runner with no
browsers installed, and master's ``pytest (mocked)`` gate went red — which also
blocks deploys, since deploy-droplet.yml gates on that job.

The failure mode is silent: no import error, no warning, just one hook quietly
gone. This test makes it loud. Extend ``_HOOKS`` when new hooks are added.
"""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

_CONFTEST = Path(__file__).resolve().parents[1] / "conftest.py"

# Hooks that have bitten us or are load-bearing. Not exhaustive by design:
# any pytest_* def in the module is checked below.
_HOOKS = ("pytest_collection_modifyitems", "pytest_addoption")


def _top_level_function_names() -> Counter:
    tree = ast.parse(_CONFTEST.read_text(encoding="utf-8"))
    return Counter(
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


@pytest.mark.parametrize("hook", _HOOKS)
def test_named_hook_defined_at_most_once(hook: str):
    count = _top_level_function_names()[hook]
    assert count <= 1, (
        f"tests/conftest.py defines {hook}() {count} times. The later def "
        f"rebinds the name and the earlier one is silently dropped — merge the "
        f"bodies into a single hook and factor the parts into plain helpers."
    )


def test_no_pytest_hook_is_defined_twice():
    """Catch the same mistake for hooks not yet listed in _HOOKS."""
    dupes = {
        name: n
        for name, n in _top_level_function_names().items()
        if name.startswith("pytest_") and n > 1
    }
    assert not dupes, f"duplicate pytest hook definitions in tests/conftest.py: {dupes}"


def test_e2e_deselection_and_ratchet_share_the_single_hook():
    """Both behaviours must be reachable from the one surviving hook.

    Asserts wiring, not text: the ratchet helper has to actually be CALLED from
    pytest_collection_modifyitems, otherwise the hook is present but inert.
    """
    tree = ast.parse(_CONFTEST.read_text(encoding="utf-8"))
    hook = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "pytest_collection_modifyitems"
    )
    called = {
        n.func.id for n in ast.walk(hook)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "_apply_known_failures" in called, (
        "the known-failure ratchet is no longer invoked from "
        "pytest_collection_modifyitems — known_failures.txt would be ignored"
    )
    src = ast.get_source_segment(_CONFTEST.read_text(encoding="utf-8"), hook) or ""
    assert "--e2e" in src, (
        "the --e2e deselection is no longer in pytest_collection_modifyitems — "
        "Playwright tests would run without browsers installed"
    )
