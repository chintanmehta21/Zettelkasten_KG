"""Test 09_run_registry.py: SQLite registry init + ingest-iter."""
from __future__ import annotations

import csv
import sqlite3
import subprocess
import sys
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "docs" / "zettel_eval_v1" / "scripts" / "09_run_registry.py"
RUNS = REPO_ROOT / "docs" / "zettel_eval_v1" / "runs"
DATA = REPO_ROOT / "docs" / "zettel_eval_v1" / "_data"
DB = DATA / "eval_history.sqlite"


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )


def test_init_creates_tables():
    if DB.exists():
        DB.unlink()
    res = _run("init")
    assert res.returncode == 0, f"init failed: {res.stderr}"
    assert DB.exists()
    con = sqlite3.connect(DB)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    expected = {"runs", "llm_calls", "zettel_results", "canary_hashes", "annotations"}
    missing = expected - tables
    assert not missing, f"missing tables: {missing}"


def test_ingest_iter_inserts_zettel_results():
    # Seed a synthetic manifest_results.csv under runs/iter-registry-test/
    src_dir = RUNS / "iter-registry-test" / "_overall"
    src_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {"wz_uuid": "rz1", "source_type": "web", "composite": 80.0,
         "rubric_total": 70.0, "rubric_max_points": 100,
         "finesure_faithfulness": 0.95, "finesure_completeness": 0.85,
         "finesure_conciseness": 0.7, "g_eval_coherence": 3,
         "g_eval_fluency": 2, "composite_uncapped": 82.0,
         "hallucination_cap_hit": 0, "judge_kind": "primary",
         "judge_model_used": "gemini-2.5-flash"},
    ]
    csv_path = src_dir / "manifest_results.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows: w.writerow(r)

    res = _run("ingest-iter", "iter-registry-test")
    assert res.returncode == 0, f"ingest-iter failed: {res.stderr}"

    con = sqlite3.connect(DB)
    rows_db = list(con.execute(
        "SELECT run_id, workspace_zettel_id, composite, source_type FROM zettel_results WHERE run_id=?",
        ("iter-registry-test",)
    ))
    con.close()
    assert len(rows_db) == 1
    assert rows_db[0][1] == "rz1"
    assert float(rows_db[0][2]) == 80.0
    assert rows_db[0][3] == "web"


def test_query_returns_rows():
    res = _run("query", "SELECT COUNT(*) FROM zettel_results")
    assert res.returncode == 0
    assert "1" in res.stdout  # at least 1 row from prior test


if __name__ == "__main__":
    test_init_creates_tables()
    print("PASS test_init_creates_tables")
    test_ingest_iter_inserts_zettel_results()
    print("PASS test_ingest_iter_inserts_zettel_results")
    test_query_returns_rows()
    print("PASS test_query_returns_rows")
    print("ALL 3 TESTS PASS")
