"""Guard against silently-dead pytest hooks in conftest files.

2026-08-04: tests/conftest.py defined ``pytest_collection_modifyitems`` TWICE at
module level — line 77 (skip e2e tests without --e2e) and line 380 (known-failure
ratchet). pytest calls every conftest hook of the same name across DIFFERENT
conftest files, but two defs in the SAME module are ordinary Python shadowing:
the later def wins and the earlier is dead code.

The e2e skip therefore stopped running the moment the ratchet was added, which
is what broke the deploy gate — browser tests were selected in a job with no
Playwright browsers and ERRORed on BrowserType.launch. The `# noqa: F811` on the
second def suppressed the one lint rule that was reporting the problem.

This is a whole class of bug: any duplicated hook name in one conftest silently
loses behaviour, with no error and no test failure at the point of breakage.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

def _is_excluded(path: Path) -> bool:
    """Filter on the REPO-RELATIVE parts.

    Filtering absolute parts is wrong: a git worktree lives under
    ``.claude/worktrees/<name>/``, so every absolute path contains ``.claude``
    and the whole set gets excluded — silently turning this guard into a no-op.
    """
    rel_parts = path.relative_to(REPO_ROOT).parts
    return any(
        part in {".claude", ".claire", "node_modules", ".git", "site-packages"}
        for part in rel_parts
    )


# Every conftest in the repo — tests/ plus the co-located feature test trees.
CONFTESTS = sorted(p for p in REPO_ROOT.rglob("conftest.py") if not _is_excluded(p))


def _module_level_def_counts(path: Path) -> dict[str, int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    for node in tree.body:  # module level ONLY — nested defs don't shadow
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            counts[node.name] = counts.get(node.name, 0) + 1
    return counts


def test_conftests_exist():
    assert CONFTESTS, "no conftest.py files discovered — glob is wrong"


@pytest.mark.parametrize("path", CONFTESTS, ids=lambda p: str(p.name))
def test_no_duplicate_module_level_hook_defs(path: Path):
    """A pytest hook defined twice in one module loses the earlier definition."""
    dupes = {
        name: n
        for name, n in _module_level_def_counts(path).items()
        if n > 1 and name.startswith("pytest_")
    }
    rel = path.relative_to(REPO_ROOT)
    assert not dupes, (
        f"{rel} defines these pytest hooks more than once at module level: "
        f"{dupes}. The later def shadows the earlier one and its behaviour is "
        f"silently lost. Merge them into a single hook that calls helpers."
    )


def test_e2e_skip_helper_is_wired_into_the_hook():
    """The specific regression: the e2e skip must actually be reachable."""
    conftest = REPO_ROOT / "tests/conftest.py"
    tree = ast.parse(conftest.read_text(encoding="utf-8"))

    hooks = [
        n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "pytest_collection_modifyitems"
    ]
    assert len(hooks) == 1, "must be exactly one collection hook in this module"

    called = {
        n.func.id
        for n in ast.walk(hooks[0])
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "_skip_e2e_without_flag" in called, (
        "the e2e skip helper is no longer called from the collection hook — "
        "browser tests will be selected in jobs that have no Playwright browsers"
    )
    # The merge must not have dropped the other half. Before the fix these were
    # two separate defs and the ratchet was the one that survived; the failure
    # mode of a careless re-merge is losing it instead.
    assert "_load_known_failures" in called, (
        "the known-failure ratchet is no longer driven from the collection hook"
    )
