from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EVAL_LOOP = REPO_ROOT / "ops" / "scripts" / "eval_loop.py"

_CAL_ENV = {
    "CAL_LECTURE_URL":   "https://x/l",
    "CAL_INTERVIEW_URL": "https://x/i",
    "CAL_TUTORIAL_URL":  "https://x/t",
    "CAL_REVIEW_URL":    "https://x/r",
    "CAL_SHORT_URL":     "https://x/s",
}

_PASSING_SCORES = {
    "https://x/l": 90.0,
    "https://x/i": 91.0,
    "https://x/t": 89.0,
    "https://x/r": 90.0,
    "https://x/s": 88.0,
}


def _run(args: list[str], env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    import os
    env = os.environ.copy()
    # Clear any pre-set CAL_*_URLs from the outer shell so tests are deterministic.
    for k in list(env):
        if k.startswith("CAL_") and k.endswith("_URL"):
            del env[k]
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(EVAL_LOOP), *args],
        capture_output=True, text=True, env=env, cwd=str(REPO_ROOT),
    )


def test_calibrate_skips_when_env_vars_missing():
    proc = _run(["--calibrate", "--baseline", "90", "--calibration-scores", "/nope"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "skipped"


def test_calibrate_passes_on_healthy_scores(tmp_path: Path):
    scores_file = tmp_path / "scores.json"
    scores_file.write_text(json.dumps(_PASSING_SCORES), encoding="utf-8")
    proc = _run(
        ["--calibrate", "--baseline", "90", "--calibration-scores", str(scores_file)],
        env_extra=_CAL_ENV,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "pass"


def test_calibrate_blocks_on_shape_below_floor(tmp_path: Path):
    scores_file = tmp_path / "scores.json"
    bad = dict(_PASSING_SCORES)
    bad["https://x/i"] = 70.0
    scores_file.write_text(json.dumps(bad), encoding="utf-8")
    proc = _run(
        ["--calibrate", "--baseline", "90", "--calibration-scores", str(scores_file)],
        env_extra=_CAL_ENV,
    )
    assert proc.returncode == 2, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "block"
    assert "interview" in payload["reason"]


def test_calibrate_blocks_on_mean_regression(tmp_path: Path):
    scores_file = tmp_path / "scores.json"
    # All at 85 (above floor 80), baseline 90 → regression 5 > tolerance 3.
    regressed = {url: 85.0 for url in _PASSING_SCORES}
    scores_file.write_text(json.dumps(regressed), encoding="utf-8")
    proc = _run(
        ["--calibrate", "--baseline", "90",
         "--calibration-scores", str(scores_file),
         "--floor", "80"],
        env_extra=_CAL_ENV,
    )
    assert proc.returncode == 2, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "block"
    assert "regression" in payload["reason"].lower()


def test_calibrate_errors_when_scores_file_missing(tmp_path: Path):
    proc = _run(
        ["--calibrate", "--baseline", "90",
         "--calibration-scores", str(tmp_path / "nonexistent.json")],
        env_extra=_CAL_ENV,
    )
    assert proc.returncode == 2
    payload = json.loads(proc.stdout)
    assert payload["status"] == "error"
