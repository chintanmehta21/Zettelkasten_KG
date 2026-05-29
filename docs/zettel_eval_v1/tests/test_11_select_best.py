"""Test 11_select_best.py: across multiple iter manifest CSVs, picks the best iter per axis per source."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "docs" / "zettel_eval_v1" / "scripts" / "11_select_best.py"
RUNS = REPO_ROOT / "docs" / "zettel_eval_v1" / "runs"
ANALYSIS = REPO_ROOT / "docs" / "zettel_eval_v1" / "analysis"


def _seed_iter_csv(iter_id: str, src: str, rows: list[dict]) -> None:
    """Write a synthetic manifest_results.csv with controlled composite values."""
    d = RUNS / iter_id / src
    d.mkdir(parents=True, exist_ok=True)
    cols = list(rows[0].keys())
    with (d / "manifest_results.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_picks_winning_iter_per_axis():
    """Iter B has higher composite than iter A on the same zettels -> B wins."""
    rows_a = [
        {"wz_uuid": "z1", "source_type": "web", "composite": 70.0, "finesure_faithfulness": 0.9},
        {"wz_uuid": "z2", "source_type": "web", "composite": 75.0, "finesure_faithfulness": 0.95},
    ]
    rows_b = [
        {"wz_uuid": "z1", "source_type": "web", "composite": 80.0, "finesure_faithfulness": 0.95},
        {"wz_uuid": "z2", "source_type": "web", "composite": 85.0, "finesure_faithfulness": 0.97},
    ]
    _seed_iter_csv("iter-test-A", "web", rows_a)
    _seed_iter_csv("iter-test-B", "web", rows_b)

    res = subprocess.run(
        [sys.executable, str(SCRIPT), "--iters", "iter-test-A,iter-test-B",
         "--axes", "composite,finesure_faithfulness"],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )
    assert res.returncode == 0, f"11 failed: {res.stderr}"

    report = ANALYSIS / "best_per_axis_per_source.json"
    assert report.exists(), "best_per_axis_per_source.json not emitted"
    r = json.loads(report.read_text(encoding="utf-8"))

    # composite axis × web source should pick iter-test-B
    assert r["composite"]["web"]["winner"] == "iter-test-B"
    # The median delta should be POSITIVE (B - A > 0)
    assert r["composite"]["web"]["median_delta"] > 0


def test_emits_markdown_report():
    md = ANALYSIS / "best_per_axis_per_source.md"
    assert md.exists()
    txt = md.read_text(encoding="utf-8")
    assert "iter-test-B" in txt
    assert "composite" in txt.lower()


def test_select_excludes_backfilled_pairs():
    """Fix #2.1: pairs where EITHER iter's row is `backfilled=1` are dropped
    from the BCa CI + sign-flip p-value computation. result JSON exposes
    n_backfilled_excluded so downstream consumers can audit."""
    rows_a = [
        {"wz_uuid": "z1", "source_type": "web", "composite": 70.0,
         "finesure_faithfulness": 0.9, "backfilled": 0, "backfilled_fields": ""},
        # backfilled on the BASE side
        {"wz_uuid": "z2", "source_type": "web", "composite": 75.0,
         "finesure_faithfulness": 0.5, "backfilled": 1, "backfilled_fields": "finesure"},
    ]
    rows_b = [
        {"wz_uuid": "z1", "source_type": "web", "composite": 80.0,
         "finesure_faithfulness": 0.95, "backfilled": 0, "backfilled_fields": ""},
        {"wz_uuid": "z2", "source_type": "web", "composite": 85.0,
         "finesure_faithfulness": 0.97, "backfilled": 0, "backfilled_fields": ""},
    ]
    _seed_iter_csv("iter-test-bf-A", "web", rows_a)
    _seed_iter_csv("iter-test-bf-B", "web", rows_b)

    res = subprocess.run(
        [sys.executable, str(SCRIPT), "--iters", "iter-test-bf-A,iter-test-bf-B",
         "--axes", "composite,finesure_faithfulness"],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )
    assert res.returncode == 0, f"11 failed: {res.stderr}"
    report = json.loads((ANALYSIS / "best_per_axis_per_source.json").read_text(encoding="utf-8"))
    # Only the z1 pair is aggregable
    assert report["composite"]["web"]["n_paired"] == 1, (
        f"expected n_paired=1 post-backfill-drop; got {report['composite']['web']['n_paired']}"
    )
    assert report["composite"]["web"]["n_backfilled_excluded"] == 1, (
        f"expected n_backfilled_excluded=1; got {report['composite']['web']['n_backfilled_excluded']}"
    )
    md = (ANALYSIS / "best_per_axis_per_source.md").read_text(encoding="utf-8")
    # Per-row column AND tail section both present
    assert "Backfilled-excluded" in md, "markdown missing backfilled-excluded column header"
    assert "Backfilled-excluded pairs (" in md, "markdown missing tail section"


if __name__ == "__main__":
    test_picks_winning_iter_per_axis()
    print("PASS test_picks_winning_iter_per_axis")
    test_emits_markdown_report()
    print("PASS test_emits_markdown_report")
    test_select_excludes_backfilled_pairs()
    print("PASS test_select_excludes_backfilled_pairs")
    print("ALL 3 TESTS PASS")
