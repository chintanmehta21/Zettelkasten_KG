"""Test 08_canary_drift.py: save baseline, re-run, ensure no drift; tweak fake response, ensure drift detected."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "docs" / "zettel_eval_v1" / "scripts" / "08_canary_drift.py"
CANARY = REPO_ROOT / "docs" / "zettel_eval_v1" / "_config" / "canary_set.json"


def _restore_canary_no_baselines():
    """Reset canary_set.json::baselines to empty so tests start clean."""
    doc = json.loads(CANARY.read_text(encoding="utf-8"))
    doc["baselines"] = {"primary_judge_gemini": {}, "secondary_judge_claude": {}}
    CANARY.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )


def test_save_baseline_then_recheck_zero_drift():
    """--save-baseline writes hashes; re-run with same fake responses -> 0 drift."""
    _restore_canary_no_baselines()

    # First run: save baseline with fake judge returning canned response 'BASE'
    res1 = _run("--judge", "primary", "--save-baseline", "--fake-judge", "--fake-response", "BASE")
    assert res1.returncode == 0, f"first save-baseline failed: {res1.stderr}"

    doc = json.loads(CANARY.read_text(encoding="utf-8"))
    baseline = doc["baselines"]["primary_judge_gemini"]
    assert len(baseline) == len(doc["items"]), \
        f"baseline should have one hash per canary item; got {len(baseline)} vs {len(doc['items'])}"

    # Re-run with same response -> zero drift
    res2 = _run("--judge", "primary", "--fake-judge", "--fake-response", "BASE")
    assert res2.returncode == 0, f"recheck should pass (zero drift); got: {res2.stderr}"


def test_drift_detected_when_response_changes():
    """Re-run after baseline with DIFFERENT fake response → script exits nonzero and reports drift."""
    _restore_canary_no_baselines()
    _ = _run("--judge", "primary", "--save-baseline", "--fake-judge", "--fake-response", "BASE")

    # Now change the fake response → should detect drift
    res = _run("--judge", "primary", "--fake-judge", "--fake-response", "DRIFTED")
    assert res.returncode != 0, "drift should produce nonzero exit code"
    assert "drift" in (res.stdout + res.stderr).lower(), "drift report should mention 'drift'"


if __name__ == "__main__":
    test_save_baseline_then_recheck_zero_drift()
    print("PASS test_save_baseline_then_recheck_zero_drift")
    test_drift_detected_when_response_changes()
    print("PASS test_drift_detected_when_response_changes")
    print("ALL 2 TESTS PASS")
