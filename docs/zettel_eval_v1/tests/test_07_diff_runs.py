"""Test 07_diff_runs.py: paired diff between two iters with per-source breakdown."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "docs" / "zettel_eval_v1" / "scripts" / "07_diff_runs.py"
RUNS = REPO_ROOT / "docs" / "zettel_eval_v1" / "runs"
ANALYSIS = REPO_ROOT / "docs" / "zettel_eval_v1" / "analysis"


def _seed_csv(iter_id: str, src: str, rows: list[dict]) -> None:
    d = RUNS / iter_id / src
    d.mkdir(parents=True, exist_ok=True)
    cols = list(rows[0].keys())
    with (d / "manifest_results.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow(r)


def test_emits_per_source_diff_markdown():
    rows_a = [{"wz_uuid": "z1", "source_type": "web", "composite": 70.0,
               "finesure_faithfulness": 0.9, "finesure_completeness": 0.8,
               "finesure_conciseness": 0.5, "title": "T1", "normalized_url": "https://x"}]
    rows_b = [{"wz_uuid": "z1", "source_type": "web", "composite": 85.0,
               "finesure_faithfulness": 0.95, "finesure_completeness": 0.85,
               "finesure_conciseness": 0.6, "title": "T1", "normalized_url": "https://x"}]
    _seed_csv("iter-diff-base", "web", rows_a)
    _seed_csv("iter-diff-cand", "web", rows_b)

    res = subprocess.run(
        [sys.executable, str(SCRIPT), "--base", "iter-diff-base", "--candidate", "iter-diff-cand"],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )
    assert res.returncode == 0, f"07 failed: {res.stderr}"

    diff_dir = ANALYSIS / "diff-iter-diff-base-vs-iter-diff-cand"
    md = diff_dir / "OVERALL.md"
    assert md.exists(), f"OVERALL.md missing under {diff_dir}"
    txt = md.read_text(encoding="utf-8")
    assert "composite" in txt.lower()
    assert "iter-diff-cand" in txt

    per_source_md = diff_dir / "per_source" / "web.md"
    assert per_source_md.exists(), "per_source/web.md missing"


def test_machine_readable_payload_has_axis_deltas():
    diff_dir = ANALYSIS / "diff-iter-diff-base-vs-iter-diff-cand"
    j = json.loads((diff_dir / "per_axis.json").read_text(encoding="utf-8"))
    assert "composite" in j
    assert "web" in j["composite"]
    assert j["composite"]["web"]["median_delta"] > 0   # candidate beat base


def test_diff_excludes_backfilled_pairs():
    """Fix #2.1: a pair where EITHER iter's row is `backfilled=1` must be
    dropped from the paired delta. Otherwise the synthesized 0.5 score
    creates a fake delta in either direction and corrupts the median."""
    rows_a = [
        {"wz_uuid": "z1", "source_type": "web", "composite": 70.0,
         "finesure_faithfulness": 0.9, "finesure_completeness": 0.8,
         "finesure_conciseness": 0.5, "title": "T1", "normalized_url": "https://x",
         "backfilled": 0, "backfilled_fields": ""},
        # backfilled on the BASE side — pair (z2_base, z2_cand) must drop
        {"wz_uuid": "z2", "source_type": "web", "composite": 60.0,
         "finesure_faithfulness": 0.5, "finesure_completeness": 0.5,
         "finesure_conciseness": 0.5, "title": "T2", "normalized_url": "https://y",
         "backfilled": 1, "backfilled_fields": "finesure"},
    ]
    rows_b = [
        {"wz_uuid": "z1", "source_type": "web", "composite": 85.0,
         "finesure_faithfulness": 0.95, "finesure_completeness": 0.85,
         "finesure_conciseness": 0.6, "title": "T1", "normalized_url": "https://x",
         "backfilled": 0, "backfilled_fields": ""},
        {"wz_uuid": "z2", "source_type": "web", "composite": 90.0,
         "finesure_faithfulness": 0.97, "finesure_completeness": 0.87,
         "finesure_conciseness": 0.62, "title": "T2", "normalized_url": "https://y",
         "backfilled": 0, "backfilled_fields": ""},
    ]
    _seed_csv("iter-diff-base-bf", "web", rows_a)
    _seed_csv("iter-diff-cand-bf", "web", rows_b)

    res = subprocess.run(
        [sys.executable, str(SCRIPT), "--base", "iter-diff-base-bf",
         "--candidate", "iter-diff-cand-bf"],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )
    assert res.returncode == 0, f"07 failed: {res.stderr}"
    diff_dir = ANALYSIS / "diff-iter-diff-base-bf-vs-iter-diff-cand-bf"
    j = json.loads((diff_dir / "per_axis.json").read_text(encoding="utf-8"))
    # only z1 survives → n_paired must be 1; n_backfilled_excluded must be 1
    for axis in ("composite", "finesure_faithfulness", "finesure_completeness",
                 "finesure_conciseness"):
        assert j[axis]["web"]["n_paired"] == 1, (
            f"axis {axis}: expected 1 pair post-backfill-drop; got {j[axis]['web']['n_paired']}"
        )
        assert j[axis]["web"]["n_backfilled_excluded"] == 1, (
            f"axis {axis}: expected n_backfilled_excluded=1; got {j[axis]['web']['n_backfilled_excluded']}"
        )
    per_source_md = (diff_dir / "per_source" / "web.md").read_text(encoding="utf-8")
    assert "excluded 1 backfilled-pair(s)" in per_source_md, (
        f"per_source/web.md missing excluded-pair note. text={per_source_md!r}"
    )
    overall_md = (diff_dir / "OVERALL.md").read_text(encoding="utf-8")
    assert "Backfilled-excluded pairs (1)" in overall_md, "OVERALL.md missing tail section"


if __name__ == "__main__":
    test_emits_per_source_diff_markdown()
    print("PASS test_emits_per_source_diff_markdown")
    test_machine_readable_payload_has_axis_deltas()
    print("PASS test_machine_readable_payload_has_axis_deltas")
    test_diff_excludes_backfilled_pairs()
    print("PASS test_diff_excludes_backfilled_pairs")
    print("ALL 3 TESTS PASS")
