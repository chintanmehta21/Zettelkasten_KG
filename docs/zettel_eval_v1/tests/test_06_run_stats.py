"""Test 06_run_stats.py: per-axis Spearman + BCa CI between auto scores and human annotations."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "docs" / "zettel_eval_v1" / "scripts" / "06_run_stats.py"
RUNS = REPO_ROOT / "docs" / "zettel_eval_v1" / "runs"
ANALYSIS = REPO_ROOT / "docs" / "zettel_eval_v1" / "analysis"
ANNOT = REPO_ROOT / "docs" / "zettel_eval_v1" / "annotation"


def _seed_iter(iter_id: str, rows: list[dict]) -> None:
    d = RUNS / iter_id / "_overall"; d.mkdir(parents=True, exist_ok=True)
    cols = list(rows[0].keys())
    with (d / "manifest_results.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow(r)
    # also per-source
    d2 = RUNS / iter_id / "web"; d2.mkdir(parents=True, exist_ok=True)
    with (d2 / "manifest_results.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow(r)


def _seed_annotations(annot_root: Path, zettel_uuids: list[str]) -> None:
    # Write into a SANDBOX annot_root (a tmp dir), NEVER the real annotation/
    # tree — test fixtures here previously clobbered the real
    # responses.normalized.json and silently broke 06 (N=0). 06 is pointed at
    # this sandbox via --annotation-root.
    rdir = annot_root / "round-1"; rdir.mkdir(parents=True, exist_ok=True)
    payload = {"round": "1", "responses": [
        {"zettel_uuid": z, "scores_normalized": {
            "faithfulness": 0.5 + i * 0.1,
            "coverage": 0.5 + i * 0.05,
            "conciseness": 0.7,
            "coherence": 0.8,
        }} for i, z in enumerate(zettel_uuids)
    ]}
    (rdir / "responses.normalized.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


def test_emits_per_axis_spearman_with_ci(tmp_path):
    rows = [{"wz_uuid": f"sz{i}", "source_type": "web",
             "composite": 50.0 + i * 10,
             "finesure_faithfulness": 0.5 + i * 0.1,
             "finesure_completeness": 0.5 + i * 0.08,
             "finesure_conciseness": 0.7,
             "g_eval_coherence": 3} for i in range(5)]
    _seed_iter("iter-stats-test", rows)
    _seed_annotations(tmp_path, [r["wz_uuid"] for r in rows])

    res = subprocess.run(
        [sys.executable, str(SCRIPT), "--iter", "iter-stats-test", "--bootstrap-B", "200",
         "--annotation-root", str(tmp_path)],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )
    assert res.returncode == 0, f"06 failed: {res.stderr}"

    spearman_path = ANALYSIS / "iter-stats-test" / "per_axis_spearman.json"
    assert spearman_path.exists()
    d = json.loads(spearman_path.read_text(encoding="utf-8"))
    for axis in ("faithfulness", "coverage", "conciseness", "coherence"):
        assert axis in d, f"missing axis {axis}"
        assert "rho" in d[axis]
        assert "ci_low" in d[axis]
        assert "ci_high" in d[axis]
        assert "n" in d[axis]


def test_excludes_backfilled_rows_from_correlation(tmp_path):
    """Fix #2.1: backfilled rows (synthesized 0.5 scores) must NOT enter the
    rank-correlation against human annotations. Without this, the synthesized
    'middle' scores artificially compress Spearman ρ toward 0."""
    # 3 aggregable rows with monotonic auto+human scores → strong positive rho
    rows = [{"wz_uuid": f"sz{i}", "source_type": "web",
             "composite": 50.0 + i * 10,
             "finesure_faithfulness": 0.5 + i * 0.1,
             "finesure_completeness": 0.5 + i * 0.08,
             "finesure_conciseness": 0.7,
             "g_eval_coherence": 3,
             "backfilled": 0, "backfilled_fields": ""} for i in range(3)]
    # 1 backfilled row with synthesized 0.5 — if NOT excluded, it would shift
    # the rho meaningfully because it has middling scores against a high-coherence human.
    rows.append({
        "wz_uuid": "sz_backfilled", "source_type": "web",
        "composite": 50.0, "finesure_faithfulness": 0.5,
        "finesure_completeness": 0.5, "finesure_conciseness": 0.5,
        "g_eval_coherence": 1,
        "backfilled": 1, "backfilled_fields": "finesure;rubric",
    })
    _seed_iter("iter-stats-backfilled-test", rows)
    _seed_annotations(tmp_path, [r["wz_uuid"] for r in rows])

    res = subprocess.run(
        [sys.executable, str(SCRIPT), "--iter", "iter-stats-backfilled-test",
         "--bootstrap-B", "200", "--annotation-root", str(tmp_path)],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )
    assert res.returncode == 0, f"06 failed: {res.stderr}"

    spearman = json.loads(
        (ANALYSIS / "iter-stats-backfilled-test" / "per_axis_spearman.json").read_text(encoding="utf-8")
    )
    # All axes computed on the 3 aggregable rows only — n must be 3, not 4
    for axis in ("faithfulness", "coverage", "conciseness", "coherence"):
        assert spearman[axis]["n"] == 3, (
            f"axis {axis}: expected n=3 (aggregable only); got {spearman[axis]['n']}"
        )
    # REPORT.md surfaces the excluded count in both header and tail section
    report = (ANALYSIS / "iter-stats-backfilled-test" / "REPORT.md").read_text(encoding="utf-8")
    assert "excluded 1 backfilled rows" in report, f"REPORT.md missing header note. text={report!r}"
    assert "Backfilled-excluded rows (1)" in report, "REPORT.md missing tail section"


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as _d:
        test_emits_per_axis_spearman_with_ci(Path(_d))
    print("PASS test_emits_per_axis_spearman_with_ci")
    with tempfile.TemporaryDirectory() as _d:
        test_excludes_backfilled_rows_from_correlation(Path(_d))
    print("PASS test_excludes_backfilled_rows_from_correlation")
    print("ALL 2 TESTS PASS")
