"""Ensure the committed structured-payload schema snapshots match the live
pydantic schemas. A drift here means either (a) a payload schema changed
without an intentional snapshot refresh, or (b) the snapshot file is missing.

Both conditions are production risks because downstream evaluators, prompt
templates, and JSON-mode guidance all key off the schema shape. The CI gate
runs the same ``check_schema_drift.py`` module so the test catches drift at the
same layer production does.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SCRIPT = _REPO_ROOT / "ops" / "scripts" / "check_schema_drift.py"


def test_script_file_exists():
    assert _SCRIPT.is_file(), f"missing drift-check script at {_SCRIPT}"


def test_no_schema_drift_vs_snapshots():
    """Runs the CI drift check as a subprocess and asserts exit-code 0.

    Runs the script in a fresh interpreter to avoid pydantic ``model_json_schema``
    caching side effects that could leak between tests, and to mirror exactly
    how the CI pipeline invokes it.
    """
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        pytest.fail(
            "Schema drift detected.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}\n"
            "Run `python ops/scripts/check_schema_drift.py --update` to refresh "
            "snapshots if the drift is intentional."
        )


def test_detect_drift_in_process():
    """Direct in-process call — catches import-time regressions the subprocess
    form would silently hide under sys.path shenanigans."""
    sys.path.insert(0, str(_REPO_ROOT / "ops" / "scripts"))
    try:
        import check_schema_drift  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)
    drifts = check_schema_drift.detect_drift()
    assert drifts == [], f"unexpected in-process drifts: {drifts}"
