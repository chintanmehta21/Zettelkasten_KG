"""2026-05-25 fix: the read_recent_logs workflow now converts the operator's
RFC3339 ``since`` input into journalctl's ``YYYY-MM-DD HH:MM:SS`` shape.

The earlier behavior passed ``2026-05-22T16:00:00Z`` straight to
``journalctl --since``, which rejects it with ``Failed to parse timestamp``
(observed during the Nimit forensic sweep). The fix is a tiny ``sed`` rewrite
inline in the SSH script; this test pins the rewrite tokens so a future
"clean up the sed call" refactor cannot silently revert the bug.
"""
from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[3]
    / ".github"
    / "workflows"
    / "read_recent_logs.yml"
)


def test_workflow_exists():
    assert WORKFLOW.exists()


def test_journalctl_branch_uses_translated_timestamp():
    """The journalctl branch must translate the input via sed before
    passing to ``--since``. We pin three things: the sed pipeline, the
    translated variable name, and the variable used by the journalctl call.
    """
    raw = WORKFLOW.read_text(encoding="utf-8")
    # sed must strip the T-separator and trailing Z that RFC3339 carries.
    assert "JCTL_SINCE_FMT=" in raw
    assert "sed -e 's/T/ /'" in raw
    assert "s/Z$//" in raw
    # journalctl must consume the translated variable, NOT the raw input.
    # The bug-state would be `journalctl --since "$JCTL_SINCE"`; the fixed
    # state is `journalctl --since "$JCTL_SINCE_FMT"`.
    assert 'journalctl --since "$JCTL_SINCE_FMT"' in raw
    assert 'journalctl --since "$JCTL_SINCE"' not in raw  # bug-state guard


def test_docker_compose_branch_unaffected():
    """Docker compose accepts both RFC3339 and the journalctl format, so it
    must keep using DOCKER_SINCE (the existing translation), NOT the new
    journalctl-specific JCTL_SINCE_FMT."""
    raw = WORKFLOW.read_text(encoding="utf-8")
    assert 'DOCKER_SINCE="$(echo "$JCTL_SINCE" | sed' in raw
    assert 'docker compose -f docker-compose.${COLOR}.yml logs --since "$DOCKER_SINCE"' in raw


def test_workflow_yaml_parses():
    """Sanity: the workflow file is still valid YAML after the edit."""
    yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
