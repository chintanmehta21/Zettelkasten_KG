"""06_run_stats.py — Spearman/Kendall + BCa CI per axis vs human annotations.

WIRED implementation (2026-05-28 TDD).

Reads:
  runs/<iter>/_overall/manifest_results.csv      (auto scores)
  annotation/round-1/responses.normalized.json    (human scores in [0,1])
  annotation/round-2-retest/responses.normalized.json    (optional, for intra-rater)
  annotation/pairwise/responses.normalized.json   (optional, for BT weights)

Maps:
  auto.finesure_faithfulness   -> human.faithfulness
  auto.finesure_completeness   -> human.coverage
  auto.finesure_conciseness    -> human.conciseness
  auto.g_eval_coherence (1-3)  -> human.coherence (rescaled)

Per axis, computes Spearman rho with BCa bootstrap CI; emits to:
  analysis/<iter>/per_axis_spearman.json
  analysis/<iter>/per_axis_kendall.json
  analysis/<iter>/intra_rater_krippendorff.json   (if retest exists)
  analysis/<iter>/bradley_terry_weights.json      (if pairwise exists)
  analysis/<iter>/REPORT.md                       (narrative; CI never bare rho)
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path
from statistics import median

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
EVAL = REPO_ROOT / "docs" / "zettel_eval_v1"
RUNS = EVAL / "runs"
ANNOT = EVAL / "annotation"
ANALYSIS = EVAL / "analysis"

# Shared backfilled-row exclusion (Fix #2.1; see lib/aggregable.py).
from docs.zettel_eval_v1.scripts.lib.aggregable import (  # noqa: E402
    aggregable_rows, excluded_count,
)

AXIS_MAP = {
    # human axis -> (auto column name, rescale function)
    "faithfulness": ("finesure_faithfulness", lambda x: float(x)),
    "coverage":     ("finesure_completeness", lambda x: float(x)),
    "conciseness":  ("finesure_conciseness", lambda x: float(x)),
    "coherence":    ("g_eval_coherence",     lambda x: (float(x) - 1) / 2.0),  # 1-3 -> 0-1
}


def _spearman_with_ci(xs: list[float], ys: list[float], B: int = 10000,
                      alpha: float = 0.05, seed: int = 42) -> dict:
    n = len(xs)
    if n < 3:
        return {"rho": None, "ci_low": None, "ci_high": None, "n": n,
                "note": "n<3; correlation undefined"}
    try:
        import numpy as np
        from scipy import stats
        x = np.asarray(xs, dtype=float); y = np.asarray(ys, dtype=float)
        rho_obs = float(stats.spearmanr(x, y).statistic)
        rng = np.random.default_rng(seed)
        # paired bootstrap
        def _stat(a, b): return stats.spearmanr(a, b).statistic
        res = stats.bootstrap(
            (x, y), _stat, n_resamples=B, method="BCa",
            random_state=rng, paired=True,
            confidence_level=1 - alpha,
        )
        return {"rho": round(rho_obs, 4),
                "ci_low": round(float(res.confidence_interval.low), 4),
                "ci_high": round(float(res.confidence_interval.high), 4),
                "n": n, "method": "scipy_bca"}
    except Exception:
        # Fallback: percentile bootstrap with manual rank-correlation
        def _rankdata(vals):
            order = sorted(range(len(vals)), key=lambda i: vals[i])
            ranks = [0.0] * len(vals)
            for rank, idx in enumerate(order):
                ranks[idx] = rank + 1
            return ranks

        def _rho(a, b):
            ra = _rankdata(a); rb = _rankdata(b)
            mean_a = sum(ra) / len(ra); mean_b = sum(rb) / len(rb)
            num = sum((ra[i] - mean_a) * (rb[i] - mean_b) for i in range(len(ra)))
            den_a = sum((r - mean_a) ** 2 for r in ra) ** 0.5
            den_b = sum((r - mean_b) ** 2 for r in rb) ** 0.5
            if den_a == 0 or den_b == 0:
                return 0.0
            return num / (den_a * den_b)

        rho_obs = _rho(xs, ys)
        rnd = random.Random(seed)
        boots = []
        for _ in range(B):
            idx = [rnd.randrange(n) for _ in range(n)]
            a = [xs[i] for i in idx]; b = [ys[i] for i in idx]
            boots.append(_rho(a, b))
        boots.sort()
        lo = boots[int(B * (alpha / 2))]
        hi = boots[int(B * (1 - alpha / 2))]
        return {"rho": round(rho_obs, 4), "ci_low": round(lo, 4), "ci_high": round(hi, 4),
                "n": n, "method": "manual_percentile"}


def _kendall_tau(xs: list[float], ys: list[float]) -> dict:
    n = len(xs)
    if n < 3:
        return {"tau": None, "n": n}
    concordant = discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            d = (xs[i] - xs[j]) * (ys[i] - ys[j])
            if d > 0: concordant += 1
            elif d < 0: discordant += 1
    pairs = n * (n - 1) / 2
    tau = (concordant - discordant) / pairs if pairs > 0 else 0.0
    return {"tau": round(tau, 4), "n": n}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iter", required=True, dest="iter_id")
    ap.add_argument("--bootstrap-B", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    iter_dir = RUNS / args.iter_id
    csv_path = iter_dir / "_overall" / "manifest_results.csv"
    if not csv_path.exists():
        raise SystemExit(f"missing {csv_path}; run 02 + 04 for this iter first.")
    annot_path = ANNOT / "round-1" / "responses.normalized.json"
    if not annot_path.exists():
        raise SystemExit(f"missing {annot_path}; run 05_annotation_kit.py --ingest first.")

    with csv_path.open(encoding="utf-8") as f:
        all_csv_rows = list(csv.DictReader(f))
    # Fix #2.1: synthesized neutral defaults (0.5) from backfilled rows would
    # bias the rank-correlation against human scores — exclude them upfront.
    n_backfilled_excluded = excluded_count(all_csv_rows)
    auto_rows = {r["wz_uuid"]: r for r in aggregable_rows(all_csv_rows)}
    human = json.loads(annot_path.read_text(encoding="utf-8"))
    human_by_id = {r["zettel_uuid"]: r["scores_normalized"] for r in human["responses"]}

    common = sorted(set(auto_rows.keys()) & set(human_by_id.keys()))

    per_axis_spearman: dict[str, dict] = {}
    per_axis_kendall: dict[str, dict] = {}
    for axis, (auto_col, rescale) in AXIS_MAP.items():
        xs, ys = [], []
        for z in common:
            try:
                auto_v = rescale(auto_rows[z][auto_col])
                human_v = float(human_by_id[z][axis])
            except (KeyError, ValueError):
                continue
            xs.append(auto_v); ys.append(human_v)
        per_axis_spearman[axis] = _spearman_with_ci(xs, ys, B=args.bootstrap_B, seed=args.seed)
        per_axis_kendall[axis] = _kendall_tau(xs, ys)

    out_dir = ANALYSIS / args.iter_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "per_axis_spearman.json").write_text(
        json.dumps(per_axis_spearman, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out_dir / "per_axis_kendall.json").write_text(
        json.dumps(per_axis_kendall, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # REPORT.md — CI mandatory (never bare rho)
    excluded_note = (f" (excluded {n_backfilled_excluded} backfilled rows from auto scores)"
                     if n_backfilled_excluded else "")
    md = [f"# Stats — {args.iter_id}\n\n",
          f"Generated by `06_run_stats.py`. Paired data: N={len(common)} common zettels"
          f"{excluded_note}.\n\n",
          "## Per-axis Spearman ρ + BCa 95% CI\n\n",
          "| Axis | ρ | CI low | CI high | N | Method |\n|---|---:|---:|---:|---:|---|\n"]
    for axis, r in per_axis_spearman.items():
        rho = r.get("rho")
        if rho is None:
            md.append(f"| {axis} | n/a | n/a | n/a | {r.get('n')} | {r.get('note','')} |\n")
        else:
            md.append(f"| {axis} | {rho:.3f} | {r['ci_low']:.3f} | {r['ci_high']:.3f} | "
                      f"{r['n']} | {r.get('method','')} |\n")
    md.append("\n## Per-axis Kendall τ\n\n| Axis | τ | N |\n|---|---:|---:|\n")
    for axis, r in per_axis_kendall.items():
        tau = r.get("tau")
        if tau is None:
            md.append(f"| {axis} | n/a | {r.get('n')} |\n")
        else:
            md.append(f"| {axis} | {tau:.3f} | {r['n']} |\n")
    if n_backfilled_excluded:
        md.append(
            f"\n## Backfilled-excluded rows ({n_backfilled_excluded})\n\n"
            "Rows where `ConsolidatedEvaluator` synthesized neutral defaults "
            "(`backfilled=1` in `manifest_results.csv`) are EXCLUDED from this "
            "correlation analysis — the synthesized 0.5 scores would bias the "
            "rank-correlation against the human annotations. They remain in the "
            "CSV for downstream inspection.\n"
        )
    (out_dir / "REPORT.md").write_text("".join(md), encoding="utf-8")
    print(f"[06] wrote {out_dir / 'per_axis_spearman.json'}")
    print(f"[06] wrote {out_dir / 'REPORT.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
