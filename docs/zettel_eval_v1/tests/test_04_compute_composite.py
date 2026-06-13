"""Test 04_compute_composite.py: reads per_zettel JSONs, emits CSV + histograms + REPORT.md."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "docs" / "zettel_eval_v1" / "scripts" / "04_compute_composite.py"
RUNS = REPO_ROOT / "docs" / "zettel_eval_v1" / "runs"

# iter-001-baseline is a generated run tree (gitignored) — absent in CI and
# fresh clones. Tests that read its artifacts skip (not fail) when absent; they
# run for the operator who has completed a real eval run.
_ITER001_PER_ZETTEL = RUNS / "iter-001-baseline" / "_overall" / "per_zettel"
requires_iter001 = pytest.mark.skipif(
    not _ITER001_PER_ZETTEL.exists() or not any(_ITER001_PER_ZETTEL.glob("*.json")),
    reason="runs/iter-001-baseline artifacts absent (gitignored; produced by a real eval run)",
)


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )


@requires_iter001
def test_iter_001_baseline_emits_overall_manifest_results_csv():
    """After 04 runs, _overall/manifest_results.csv must exist with at least 1 row."""
    iter_dir = RUNS / "iter-001-baseline"
    assert (iter_dir / "_overall" / "per_zettel").exists(), \
        "iter-001 per_zettel from 02_run_judge.py smoke missing"

    res = _run("--iter", "iter-001-baseline")
    assert res.returncode == 0, f"04 failed: {res.stderr}"

    manifest_csv = iter_dir / "_overall" / "manifest_results.csv"
    assert manifest_csv.exists(), "_overall/manifest_results.csv not emitted"
    with manifest_csv.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 1, "manifest_results.csv has no rows"
    # Required columns
    required = {
        "wz_uuid", "normalized_url", "title", "source_type",
        "rubric_total", "finesure_faithfulness", "finesure_completeness",
        "finesure_conciseness", "g_eval_coherence", "g_eval_fluency",
        "composite", "composite_uncapped",
    }
    missing = required - set(rows[0].keys())
    assert not missing, f"missing CSV columns: {missing}"


@requires_iter001
def test_per_source_manifest_results_csv():
    """Each source_type folder must get its own manifest_results.csv filtered to those zettels."""
    iter_dir = RUNS / "iter-001-baseline"
    # Find which source folders have per_zettel data
    src_with_data = [
        p.parent.parent.name for p in iter_dir.glob("*/per_zettel/*.json")
        if p.parent.parent.name not in {"_overall"}
    ]
    assert len(set(src_with_data)) >= 1
    for src in set(src_with_data):
        csv_path = iter_dir / src / "manifest_results.csv"
        assert csv_path.exists(), f"{src}/manifest_results.csv missing"
        with csv_path.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        # Every row's source_type must equal the folder name
        for r in rows:
            assert r["source_type"] == src, \
                f"{src}/manifest_results.csv contains rows of other source_types"


@requires_iter001
def test_error_class_histogram_per_source():
    iter_dir = RUNS / "iter-001-baseline"
    overall_hist = iter_dir / "_overall" / "error_class_histogram.json"
    assert overall_hist.exists(), "_overall/error_class_histogram.json missing"
    d = json.loads(overall_hist.read_text(encoding="utf-8"))
    # Must be a dict; keys are FRANK classes; values are ints
    expected_classes = {"EntE", "PredE", "CircE", "CorefE", "LinkE", "GramE", "OutE"}
    assert expected_classes.issubset(set(d.keys())), \
        f"histogram missing FRANK classes: {expected_classes - set(d.keys())}"
    for k, v in d.items():
        assert isinstance(v, int), f"histogram value for {k} is not int"


@requires_iter001
def test_iter_level_report_md():
    iter_dir = RUNS / "iter-001-baseline"
    report = iter_dir / "REPORT.md"
    assert report.exists(), "iter-level REPORT.md missing"
    txt = report.read_text(encoding="utf-8")
    # Should mention iter id + N + at least one source type
    assert "iter-001-baseline" in txt
    assert "composite" in txt.lower()


def _load_04():
    import importlib.util
    spec = importlib.util.spec_from_file_location("zettel_eval_v1_04", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


def test_collapse_jury_averages_two_judges():
    """Multi-judge → one jury_mean row/zettel; numerics averaged, cap/backfilled OR'd."""
    m = _load_04()
    rows = [
        {"wz_uuid": "z1", "source_type": "web", "composite": "80",
         "composite_uncapped": "80", "finesure_faithfulness": "0.9",
         "g_eval_coherence": "3", "hallucination_cap_hit": "0",
         "backfilled": "0", "backfilled_fields": "", "judge_kind": "primary",
         "judge_model_used": "gemini-2.5-flash"},
        {"wz_uuid": "z1", "source_type": "web", "composite": "90",
         "composite_uncapped": "90", "finesure_faithfulness": "0.7",
         "g_eval_coherence": "2", "hallucination_cap_hit": "1",
         "backfilled": "0", "backfilled_fields": "", "judge_kind": "secondary",
         "judge_model_used": "claude-haiku-4-5"},
    ]
    out, is_jury = m._collapse_jury(rows)
    assert is_jury is True and len(out) == 1
    r = out[0]
    assert r["judge_kind"] == "jury_mean"
    assert float(r["composite"]) == 85.0
    assert abs(float(r["finesure_faithfulness"]) - 0.8) < 1e-9
    assert r["hallucination_cap_hit"] == "1"  # OR across judges
    assert "claude-haiku-4-5" in r["judge_model_used"] and "gemini-2.5-flash" in r["judge_model_used"]


def test_collapse_jury_single_judge_passthrough():
    """Single judge per zettel → returned UNCHANGED (is_jury False)."""
    m = _load_04()
    rows = [{"wz_uuid": "z1", "composite": "80", "judge_kind": "primary"},
            {"wz_uuid": "z2", "composite": "70", "judge_kind": "primary"}]
    out, is_jury = m._collapse_jury(rows)
    assert is_jury is False
    assert out == rows


if __name__ == "__main__":
    test_iter_001_baseline_emits_overall_manifest_results_csv()
    test_per_source_manifest_results_csv()
    test_error_class_histogram_per_source()
    test_iter_level_report_md()
    test_collapse_jury_averages_two_judges()
    test_collapse_jury_single_judge_passthrough()
    print("PASS all 6 tests")
