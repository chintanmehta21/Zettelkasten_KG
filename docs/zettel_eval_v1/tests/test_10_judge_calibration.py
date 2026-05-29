"""Test 10_judge_calibration.py: runs judge on 18 calibration items, joins with oracle, computes detection rate.

Uses a FAKE judge to avoid real LLM cost. The fake returns predetermined
EvalResult JSON for each calibration item — we control its responses so we
can assert detection rates exactly.
"""
from __future__ import annotations

import json
import subprocess
import sys
import importlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "docs" / "zettel_eval_v1" / "scripts" / "10_judge_calibration.py"
ANALYSIS = REPO_ROOT / "docs" / "zettel_eval_v1" / "analysis" / "calibration"


def test_emits_per_judge_report_json():
    """Running with --fake-judge writes analysis/calibration/<judge>.json with per-class detection rate."""
    if ANALYSIS.exists():
        for f in ANALYSIS.glob("*.json"):
            f.unlink()
    res = subprocess.run(
        [sys.executable, str(SCRIPT), "--judge", "primary", "--fake-judge"],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )
    assert res.returncode == 0, f"10 failed: {res.stderr}"

    report = ANALYSIS / "primary.json"
    assert report.exists(), "analysis/calibration/primary.json missing"
    r = json.loads(report.read_text(encoding="utf-8"))
    assert "per_class_detection_rate" in r
    assert "overall_pass" in r
    assert isinstance(r["overall_pass"], bool)

    # Detection rates must be in [0, 1]
    for k, v in r["per_class_detection_rate"].items():
        assert 0.0 <= float(v) <= 1.0, f"detection rate for {k} = {v} out of [0,1]"


def test_per_class_keys_match_taxonomy():
    """Every FRANK-7 class + completeness + conciseness must appear in the report."""
    report = json.loads((ANALYSIS / "primary.json").read_text(encoding="utf-8"))
    expected = {"EntE", "PredE", "CircE", "CorefE", "LinkE", "GramE", "OutE",
                "completeness", "conciseness"}
    actual = set(report["per_class_detection_rate"].keys())
    assert expected.issubset(actual), f"missing classes: {expected - actual}"


def test_overall_pass_threshold_enforced():
    """A fake judge that detects 0% should fail; >=70% should pass."""
    # The default --fake-judge mode returns the correct class for each item -> 100% detection -> pass.
    report = json.loads((ANALYSIS / "primary.json").read_text(encoding="utf-8"))
    # All-correct fake should pass
    assert report["overall_pass"] is True

    # Now run with --fake-judge --fake-mode wrong → all wrong → should fail
    res = subprocess.run(
        [sys.executable, str(SCRIPT), "--judge", "primary", "--fake-judge", "--fake-mode", "wrong"],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )
    assert res.returncode != 0, "calibration should EXIT NONZERO when judge fails the gate"

    report2 = json.loads((ANALYSIS / "primary.json").read_text(encoding="utf-8"))
    assert report2["overall_pass"] is False


if __name__ == "__main__":
    test_emits_per_judge_report_json()
    print("PASS test_emits_per_judge_report_json")
    test_per_class_keys_match_taxonomy()
    print("PASS test_per_class_keys_match_taxonomy")
    test_overall_pass_threshold_enforced()
    print("PASS test_overall_pass_threshold_enforced")
    print("ALL 3 TESTS PASS")
