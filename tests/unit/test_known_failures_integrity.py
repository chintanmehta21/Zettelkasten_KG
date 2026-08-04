"""Guard: every tests/known_failures.txt entry must point at a real test.

The ratchet applies ``xfail`` by exact node id. A node id that no longer
resolves — because the test was renamed, moved, or deleted — is silently
ignored: no error, no warning, the line just stops doing anything. The file
then looks like it is holding a line it is not, which is precisely the
"cannot run != passed" failure mode the ratchet exists to prevent.

Full verification means collecting the referenced files, which takes ~70s and
needs live-test imports — too slow for the mocked gate. This is the cheap
static equivalent: confirm the file exists and still defines a function of that
name. It catches renames and deletions, which is the realistic rot.

Verified by collection on 2026-08-04: all 19 entries resolved, 0 unresolved.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "tests"))

from conftest import _load_known_failures  # noqa: E402


def _entries() -> list[str]:
    return sorted(_load_known_failures())


def _function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


@pytest.mark.parametrize("node_id", _entries())
def test_known_failure_entry_resolves(node_id: str):
    file_part, _, test_part = node_id.partition("::")
    target = _REPO_ROOT / file_part
    assert target.is_file(), (
        f"known_failures.txt references a file that does not exist: {file_part}. "
        f"Delete the line, or fix the path."
    )
    # Strip parametrisation (``test_x[chromium]``) and any class prefix.
    func_name = test_part.split("[")[0].split("::")[-1]
    assert func_name in _function_names(target), (
        f"known_failures.txt lists {node_id}, but {file_part} no longer defines "
        f"{func_name!r} — the entry is inert and the ratchet is not actually "
        f"holding that line. Delete it or update the name."
    )


def test_known_failures_file_is_not_growing_silently():
    """A tripwire, not a hard cap.

    The file's own rules say it may shrink freely but must only grow by
    deliberate decision. This asserts the count against a recorded baseline so
    an unexplained addition shows up in review rather than sliding in.
    Update BASELINE in the same commit that adds an entry, and say why in the PR.
    """
    BASELINE = 19  # 2026-08-04, PR #168 (down from 34)
    actual = len(_entries())
    assert actual <= BASELINE, (
        f"known_failures.txt grew to {actual} entries (baseline {BASELINE}). "
        f"Growing the quarantine list needs a deliberate decision — justify it "
        f"in the PR description and bump BASELINE in the same commit."
    )
