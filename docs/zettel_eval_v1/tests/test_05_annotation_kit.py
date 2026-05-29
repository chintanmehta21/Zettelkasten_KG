"""Test 05_annotation_kit.py: emit shuffled CSV from manifest; ingest filled CSV into normalized JSON."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "docs" / "zettel_eval_v1" / "scripts" / "05_annotation_kit.py"
ANNOT = REPO_ROOT / "docs" / "zettel_eval_v1" / "annotation"


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )


def test_emit_round1_csv_from_manifest():
    res = _run("--emit", "--round", "1")
    assert res.returncode == 0, f"emit failed: {res.stderr}"
    csv_path = ANNOT / "round-1" / "shuffled_assignments.csv"
    assert csv_path.exists(), f"missing {csv_path}"
    with csv_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 1
    expected_cols = {"zettel_uuid", "shown_order", "faithfulness_1_to_5",
                     "coverage_1_to_5", "conciseness_1_to_5", "coherence_1_to_5"}
    missing = expected_cols - set(rows[0].keys())
    assert not missing, f"CSV missing cols: {missing}"


def test_ingest_round1_responses():
    """Fill a synthetic responses.csv, ingest it, assert normalized JSON shape."""
    # Read the emitted shuffled CSV and fill in dummy scores
    src_csv = ANNOT / "round-1" / "shuffled_assignments.csv"
    with src_csv.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["faithfulness_1_to_5"] = "4"
        r["coverage_1_to_5"] = "4"
        r["conciseness_1_to_5"] = "3"
        r["coherence_1_to_5"] = "5"
        r["comment"] = ""
        r["annotation_started_at_iso"] = "2026-05-28T12:00:00Z"
        r["annotation_finished_at_iso"] = "2026-05-28T12:05:00Z"
    resp_csv = ANNOT / "round-1" / "responses.csv"
    with resp_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows: w.writerow(r)

    res = _run("--ingest", "--round", "1")
    assert res.returncode == 0, f"ingest failed: {res.stderr}"
    out_json = ANNOT / "round-1" / "responses.normalized.json"
    assert out_json.exists(), "responses.normalized.json missing"
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert "responses" in payload
    for r in payload["responses"]:
        for axis in ("faithfulness", "coverage", "conciseness", "coherence"):
            v = r["scores_normalized"][axis]
            assert 0.0 <= v <= 1.0, f"normalized score out of [0,1]: {axis}={v}"


if __name__ == "__main__":
    test_emit_round1_csv_from_manifest()
    print("PASS test_emit_round1_csv_from_manifest")
    test_ingest_round1_responses()
    print("PASS test_ingest_round1_responses")
    print("ALL 2 TESTS PASS")
