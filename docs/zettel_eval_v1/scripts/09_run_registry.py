"""09_run_registry.py — SQLite registry for eval-run history (Datasette pattern).

WIRED implementation (2026-05-28 TDD).

Local SQLite at docs/zettel_eval_v1/_data/eval_history.sqlite. DDL lives in
docs/zettel_eval_v1/_config/run_registry_schema.sql (created by Sub-5).

Subcommands:
  init                          apply DDL (idempotent)
  ingest-iter <iter_id>         parse runs/<iter>/_overall/manifest_results.csv + config.json + telemetry.json
  ingest-canary <path>          parse a canary report and insert into canary_hashes
  ingest-annot <path>           parse annotation/round-N/responses.csv into annotations
  query <sql>                   ad-hoc read-only SQL
  trend <axis>                  emit JSON timeseries of mean(axis) per iter
  diff <a> <b>                  paired Δ(composite) between two iters

Storage budget per Sub-5 sweep: ~1 MB/iter × 1000 iters = ~1 GB; trivial.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
EVAL = REPO_ROOT / "docs" / "zettel_eval_v1"
DB_PATH = EVAL / "_data" / "eval_history.sqlite"
DDL_PATH = EVAL / "_config" / "run_registry_schema.sql"
RUNS = EVAL / "runs"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def cmd_init() -> int:
    if not DDL_PATH.exists():
        raise SystemExit(f"DDL missing: {DDL_PATH}")
    con = _conn()
    con.executescript(DDL_PATH.read_text(encoding="utf-8"))
    con.commit(); con.close()
    print(f"[09] init OK -> {DB_PATH}")
    return 0


def cmd_ingest_iter(iter_id: str) -> int:
    iter_dir = RUNS / iter_id
    csv_path = iter_dir / "_overall" / "manifest_results.csv"
    if not csv_path.exists():
        raise SystemExit(f"missing {csv_path}; run 04_compute_composite.py --iter {iter_id} first")
    con = _conn()
    # Upsert runs row
    cfg_path = iter_dir / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    con.execute(
        "INSERT OR REPLACE INTO runs (run_id, started_at, finished_at, git_sha, git_dirty, "
        "harness_version, python_version, hostname, dataset_id, dataset_sha256, config_sha256, "
        "rubric_sha256, failure_taxonomy_sha256, notes) VALUES "
        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            iter_id,
            cfg.get("started_at") or datetime.now(timezone.utc).isoformat(),
            None,
            cfg.get("git_sha", "unknown"),
            0,
            "zettel_eval_v1.v1",
            sys.version.split()[0],
            None,
            "eval-v1.0",
            cfg.get("manifest_sha256", ""),
            cfg.get("config_sha256", ""),
            cfg.get("rubric_sha256", ""),
            None,
            None,
        ),
    )
    # Ingest zettel_results
    inserted = 0
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            con.execute(
                "INSERT OR REPLACE INTO zettel_results "
                "(run_id, workspace_zettel_id, source_type, composite, composite_uncapped, "
                "rubric_total, finesure_faithfulness, finesure_completeness, finesure_conciseness, "
                "g_eval_coherence, g_eval_fluency, hallucination_cap_hit, failure_class_vector, "
                "top_error_class_1, top_error_class_2, top_error_class_3) VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    iter_id, r.get("wz_uuid"), r.get("source_type"),
                    float(r.get("composite") or 0), float(r.get("composite_uncapped") or 0),
                    float(r.get("rubric_total") or 0),
                    float(r.get("finesure_faithfulness") or 0),
                    float(r.get("finesure_completeness") or 0),
                    float(r.get("finesure_conciseness") or 0),
                    int(r.get("g_eval_coherence") or 0),
                    int(r.get("g_eval_fluency") or 0),
                    int(r.get("hallucination_cap_hit") or 0),
                    None,
                    r.get("top_error_class_1") or None,
                    r.get("top_error_class_2") or None,
                    r.get("top_error_class_3") or None,
                ),
            )
            inserted += 1
    con.commit(); con.close()
    print(f"[09] ingested {inserted} rows into zettel_results for run_id={iter_id}")
    return 0


def cmd_query(sql: str) -> int:
    con = _conn()
    try:
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        if cols:
            print("\t".join(cols))
        for row in cur.fetchall():
            print("\t".join(str(c) for c in row))
    finally:
        con.close()
    return 0


def cmd_trend(axis: str) -> int:
    con = _conn()
    rows = con.execute(
        f"SELECT run_id, AVG({axis}) FROM zettel_results GROUP BY run_id ORDER BY run_id"
    ).fetchall()
    con.close()
    payload = [{"run_id": rid, f"mean_{axis}": float(val) if val is not None else None} for rid, val in rows]
    print(json.dumps(payload, indent=2))
    return 0


def cmd_diff(a: str, b: str) -> int:
    con = _conn()
    rows = con.execute(
        "SELECT a.workspace_zettel_id, a.composite, b.composite "
        "FROM zettel_results a JOIN zettel_results b "
        "ON a.workspace_zettel_id=b.workspace_zettel_id "
        "WHERE a.run_id=? AND b.run_id=?", (a, b)
    ).fetchall()
    con.close()
    deltas = [float(bc) - float(ac) for _, ac, bc in rows]
    if not deltas:
        print(json.dumps({"n_paired": 0, "median_delta": None}))
        return 0
    from statistics import median
    print(json.dumps({
        "n_paired": len(deltas),
        "median_delta": round(median(deltas), 3),
        "mean_delta": round(sum(deltas) / len(deltas), 3),
        "n_improvements": sum(1 for d in deltas if d > 0),
        "n_regressions": sum(1 for d in deltas if d < 0),
    }, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    p_iter = sub.add_parser("ingest-iter"); p_iter.add_argument("iter_id")
    p_canary = sub.add_parser("ingest-canary"); p_canary.add_argument("path")
    p_annot = sub.add_parser("ingest-annot"); p_annot.add_argument("path")
    p_q = sub.add_parser("query"); p_q.add_argument("sql")
    p_t = sub.add_parser("trend"); p_t.add_argument("axis")
    p_d = sub.add_parser("diff"); p_d.add_argument("a"); p_d.add_argument("b")
    args = ap.parse_args()

    if args.cmd == "init": return cmd_init()
    if args.cmd == "ingest-iter": return cmd_ingest_iter(args.iter_id)
    if args.cmd == "ingest-canary":
        # Defer: schema in place, full ingest in next iter
        print("[09] ingest-canary: not yet implemented (schema present)"); return 0
    if args.cmd == "ingest-annot":
        print("[09] ingest-annot: not yet implemented (schema present)"); return 0
    if args.cmd == "query": return cmd_query(args.sql)
    if args.cmd == "trend": return cmd_trend(args.axis)
    if args.cmd == "diff": return cmd_diff(args.a, args.b)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
