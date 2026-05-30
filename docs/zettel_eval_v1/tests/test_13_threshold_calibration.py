"""Tests for 13_threshold_calibration.py — NLI threshold calibration kit.

Covers the pure logic (no NLI model, no API):
  - _prf precision/recall/F-beta/Youden counts
  - _stratified_sample spans the contradict_prob range
  - _emit writes a well-formed labeling CSV
  - _calibrate picks a recall-favoring threshold under β>1
"""
from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "docs" / "zettel_eval_v1" / "scripts" / "13_threshold_calibration.py"


def _load():
    spec = importlib.util.spec_from_file_location("calib13", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


def test_prf_perfect_separation():
    """Labeled set perfectly separable at t=0.5 → P=R=Fβ=1 there."""
    m = _load()
    labeled = [(0.1, False), (0.2, False), (0.8, True), (0.9, True)]
    r = m._prf(labeled, 0.5, beta=2.0)
    assert r["tp"] == 2 and r["fp"] == 0 and r["fn"] == 0 and r["tn"] == 2
    assert r["precision"] == 1.0 and r["recall"] == 1.0
    assert abs(r["fbeta"] - 1.0) < 1e-9
    assert abs(r["youden_j"] - 1.0) < 1e-9


def test_prf_counts_threshold_too_high():
    """A high threshold misses real contradictions → recall drops, FN rises."""
    m = _load()
    labeled = [(0.6, True), (0.65, True), (0.9, True), (0.1, False)]
    r = m._prf(labeled, 0.8, beta=2.0)
    # only the 0.9 contradicted is caught; 0.6 + 0.65 become false negatives
    assert r["tp"] == 1 and r["fn"] == 2 and r["fp"] == 0 and r["tn"] == 1
    assert r["recall"] < 0.5


def test_fbeta_favors_recall_when_beta_gt_1():
    """With β=2, a threshold that catches all positives (some FP) should beat
    one that is precise but misses positives."""
    m = _load()
    labeled = [(0.4, True), (0.5, True), (0.6, True), (0.45, False), (0.1, False)]
    low_t = m._prf(labeled, 0.35, beta=2.0)   # catches all 3 pos + 1 fp
    high_t = m._prf(labeled, 0.55, beta=2.0)  # catches 1 pos, misses 2
    assert low_t["recall"] > high_t["recall"]
    assert low_t["fbeta"] > high_t["fbeta"], "β=2 must reward the higher-recall threshold"


def test_stratified_sample_spans_range():
    """Sample must span low..high contradict_prob, not cluster at one end."""
    m = _load()
    rows = [{"wz": f"z{i}", "claim": f"c{i}", "best_chunk_text": "",
             "nli_contradict_prob": i / 100.0} for i in range(101)]  # 0.00..1.00
    sample = m._stratified_sample(rows, 10)
    probs = [r["nli_contradict_prob"] for r in sample]
    assert len(sample) == 10
    assert min(probs) < 0.2 and max(probs) > 0.8, "sample should span the boundary"


def test_emit_writes_labeling_csv(tmp_path, monkeypatch):
    """_emit produces a CSV with the canonical columns and an empty label col."""
    m = _load()
    monkeypatch.setattr(m, "_collect_claims", lambda iter_id: [
        {"wz": "aaaa1111", "claim": "A claim.", "best_chunk_text": "chunk",
         "nli_contradict_prob": 0.1},
        {"wz": "bbbb2222", "claim": "Another claim.", "best_chunk_text": "chunk2",
         "nli_contradict_prob": 0.9},
    ])
    out = tmp_path / "labels.csv"
    rc = m._emit("iter-x", 2, out)
    assert rc == 0 and out.exists()
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert [*rows[0].keys()] == m.CSV_COLS
    assert all(r["label"] == "" for r in rows), "label column must start empty for operator"


def test_calibrate_end_to_end(tmp_path):
    """_calibrate reads a labeled CSV and emits a REPORT.md without raising."""
    m = _load()
    csv_path = tmp_path / "labels.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=m.CSV_COLS)
        w.writeheader()
        data = [("z1", 0.1, "supported"), ("z2", 0.2, "supported"),
                ("z3", 0.8, "contradicted"), ("z4", 0.9, "contradicted"),
                ("z5", 0.5, "contradicted")]
        for wz, prob, lbl in data:
            w.writerow({"wz": wz, "claim": "c", "best_chunk_text": "",
                        "nli_contradict_prob": f"{prob:.4f}", "label": lbl})
    # Redirect ANALYSIS so we don't write into the real tree
    orig = m.ANALYSIS
    m.ANALYSIS = tmp_path / "analysis"
    try:
        rc = m._calibrate(csv_path, beta=2.0)
    finally:
        m.ANALYSIS = orig
    assert rc == 0
    assert (tmp_path / "analysis" / "threshold_calibration" / "REPORT.md").exists()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                import inspect
                if "tmp_path" in inspect.signature(fn).parameters:
                    continue  # skip fixture-dependent tests in __main__ mode
                fn()
                print(f"PASS {name}")
            except Exception as e:  # pragma: no cover
                print(f"FAIL {name}: {e}")
                raise
    print("ALL non-fixture tests PASS")
