"""11_select_best.py — pick best iter per axis per source via paired BCa bootstrap.

WIRED implementation (2026-05-28 TDD).

Reads:
  runs/<iter>/<source>/manifest_results.csv  for each iter, each source

Per axis x source, computes paired delta (iter_X - iter_BASE) on the SAME zettels
(joined by wz_uuid). Uses scipy.stats.bootstrap with method='BCa' (B=10k) for the
median-delta 95% CI when scipy is available; falls back to manual paired bootstrap
when not.

Writes:
  analysis/best_per_axis_per_source.json   (machine-readable)
  analysis/best_per_axis_per_source.md     (operator narrative)

Per METHODOLOGY §19.4 + Sub-3 sweep: "When +1% Is Not Enough" (arxiv 2511.19794)
mandates paired BCa + sign-flip permutation for cross-iter comparisons.
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
RUNS = REPO_ROOT / "docs" / "zettel_eval_v1" / "runs"
ANALYSIS = REPO_ROOT / "docs" / "zettel_eval_v1" / "analysis"

# Shared backfilled-row exclusion (Fix #2.1; see lib/aggregable.py).
from docs.zettel_eval_v1.scripts.lib.aggregable import (  # noqa: E402
    is_aggregable_row,
)

DEFAULT_AXES = ("composite", "finesure_faithfulness", "finesure_completeness", "finesure_conciseness")


def _load_iter_csv(iter_id: str, source: str) -> list[dict]:
    p = RUNS / iter_id / source / "manifest_results.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _paired_join(rows_a: list[dict], rows_b: list[dict]) -> list[tuple[dict, dict]]:
    by_id_a = {r["wz_uuid"]: r for r in rows_a}
    by_id_b = {r["wz_uuid"]: r for r in rows_b}
    common = set(by_id_a.keys()) & set(by_id_b.keys())
    return [(by_id_a[k], by_id_b[k]) for k in sorted(common)]


def _bca_ci_paired(deltas: list[float], B: int = 10000, alpha: float = 0.05,
                   seed: int = 42) -> tuple[float, float, float]:
    """Return (median_delta, low_ci, high_ci) via BCa bootstrap when scipy is
    available; fall back to a percentile bootstrap otherwise."""
    if not deltas:
        return 0.0, 0.0, 0.0
    try:
        import numpy as np
        from scipy import stats
        arr = np.array(deltas, dtype=float)
        rng = np.random.default_rng(seed)
        res = stats.bootstrap(
            (arr,), np.median, n_resamples=B, method="BCa", random_state=rng,
            confidence_level=1 - alpha,
        )
        return float(np.median(arr)), float(res.confidence_interval.low), float(res.confidence_interval.high)
    except Exception:
        # Manual percentile fallback
        rnd = random.Random(seed)
        meds = []
        for _ in range(B):
            sample = [rnd.choice(deltas) for _ in deltas]
            meds.append(median(sample))
        meds.sort()
        lo = meds[int(B * (alpha / 2))]
        hi = meds[int(B * (1 - alpha / 2))]
        return median(deltas), lo, hi


def _sign_flip_pvalue(deltas: list[float], B: int = 2000, seed: int = 42) -> float:
    """Two-sided sign-flip permutation test on median(deltas) vs 0."""
    if not deltas:
        return 1.0
    obs = median(deltas)
    if obs == 0:
        return 1.0
    rnd = random.Random(seed)
    count = 0
    for _ in range(B):
        flipped = [d if rnd.random() < 0.5 else -d for d in deltas]
        if abs(median(flipped)) >= abs(obs):
            count += 1
    return count / B


def _select(iters: list[str], axes: list[str]) -> dict:
    """For each (axis, source), determine which iter beats the others by median paired delta."""
    if len(iters) < 2:
        raise SystemExit("Need at least 2 iters to compare; got: " + str(iters))
    base = iters[0]
    result: dict[str, dict[str, dict]] = {a: {} for a in axes}

    # Discover all sources present
    sources: set[str] = set()
    for it in iters:
        for src_dir in (RUNS / it).iterdir() if (RUNS / it).exists() else []:
            if src_dir.is_dir() and src_dir.name not in {"_overall"} and \
               (src_dir / "manifest_results.csv").exists():
                sources.add(src_dir.name)

    for src in sorted(sources):
        rows_base = _load_iter_csv(base, src)
        if not rows_base:
            continue
        # Tuple shape: (median_delta, ci_low, ci_high, sign_flip_p, n_paired, n_backfilled_excluded)
        per_iter_stats = {base: {a: (0.0, 0.0, 0.0, 1.0, 0, 0) for a in axes}}
        for cand in iters[1:]:
            rows_cand = _load_iter_csv(cand, src)
            if not rows_cand:
                continue
            paired_all = _paired_join(rows_base, rows_cand)
            # Fix #2.1: drop pairs where EITHER side is backfilled — synthesized
            # neutral 0.5 scores would distort the BCa CI and sign-flip p-value.
            paired = [(a, b) for a, b in paired_all
                      if is_aggregable_row(a) and is_aggregable_row(b)]
            n_backfilled_excluded = len(paired_all) - len(paired)
            for axis in axes:
                try:
                    deltas = [float(b[axis]) - float(a[axis]) for a, b in paired]
                except (KeyError, ValueError):
                    deltas = []
                med, lo, hi = _bca_ci_paired(deltas)
                p = _sign_flip_pvalue(deltas)
                per_iter_stats.setdefault(cand, {})[axis] = (
                    med, lo, hi, p, len(deltas), n_backfilled_excluded,
                )

        for axis in axes:
            # Pick the iter with highest median (positive against base = improvement)
            cand_stats = {it: per_iter_stats[it][axis] for it in iters if it in per_iter_stats and axis in per_iter_stats[it]}
            if not cand_stats:
                continue
            winner = max(cand_stats.keys(), key=lambda it: cand_stats[it][0])
            med, lo, hi, p, n, n_excluded = cand_stats[winner]
            sig = (lo > 0) or (hi < 0)  # CI does not cross zero
            result[axis][src] = {
                "winner": winner,
                "median_delta": round(med, 3),
                "ci_low": round(lo, 3),
                "ci_high": round(hi, 3),
                "sign_flip_p": round(p, 4),
                "is_significant": bool(sig),
                "n_paired": n,
                "n_backfilled_excluded": n_excluded,
                "compared_iters": iters,
            }
    return result


def _emit_markdown(result: dict, out_path: Path) -> None:
    out = ["# Best iter per axis per source\n\n",
           "Generated by `11_select_best.py`. Verdicts marked **significant** when paired BCa CI excludes 0.\n\n"]
    total_excluded = 0
    for axis, by_src in result.items():
        out.append(f"## Axis: `{axis}`\n\n")
        if not by_src:
            out.append("_no eligible sources_\n\n"); continue
        out.append("| Source | Winner | median Δ | CI low | CI high | sign-flip p | Significant? | N paired | Backfilled-excluded |\n")
        out.append("|---|---|---:|---:|---:|---:|---|---:|---:|\n")
        for src, r in sorted(by_src.items()):
            sig = "**YES**" if r["is_significant"] else "no"
            n_excl = int(r.get("n_backfilled_excluded", 0))
            total_excluded += n_excl
            out.append(f"| {src} | {r['winner']} | {r['median_delta']:.3f} | {r['ci_low']:.3f} | "
                       f"{r['ci_high']:.3f} | {r['sign_flip_p']:.4f} | {sig} | {r['n_paired']} | "
                       f"{n_excl} |\n")
        out.append("\n")
    if total_excluded:
        out.append(
            f"## Backfilled-excluded pairs ({total_excluded} total across axes×sources)\n\n"
            "Pairs where EITHER iter's row was tagged `backfilled=1` are EXCLUDED "
            "from the BCa CI + sign-flip computation above. Synthesized 0.5 scores "
            "would otherwise distort the per-source winner selection.\n"
        )
    out_path.write_text("".join(out), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iters", type=str, default=None,
                    help="comma-separated list, e.g. iter-001-baseline,iter-002-claude")
    ap.add_argument("--axes", type=str, default=",".join(DEFAULT_AXES))
    ap.add_argument("--bootstrap-B", type=int, default=10000)
    ap.add_argument("--permutation-B", type=int, default=2000)
    ap.add_argument("--significance-median-delta-pct", type=float, default=5.0)
    ap.add_argument("--emit-json", type=str, default=None)
    args = ap.parse_args()

    if args.iters:
        iters = [s.strip() for s in args.iters.split(",") if s.strip()]
    else:
        # Auto-discover any iter dir with at least one manifest_results.csv
        iters = sorted(
            p.name for p in RUNS.iterdir()
            if p.is_dir() and any(p.glob("*/manifest_results.csv"))
        )
    if len(iters) < 2:
        raise SystemExit(f"Need ≥2 iters with manifest_results.csv; found: {iters}")

    axes = [s.strip() for s in args.axes.split(",") if s.strip()]
    result = _select(iters, axes)

    ANALYSIS.mkdir(parents=True, exist_ok=True)
    json_path = Path(args.emit_json) if args.emit_json else ANALYSIS / "best_per_axis_per_source.json"
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _emit_markdown(result, ANALYSIS / "best_per_axis_per_source.md")
    print(f"[11] iters={iters} axes={axes}")
    print(f"[11] wrote {json_path}")
    print(f"[11] wrote {ANALYSIS / 'best_per_axis_per_source.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
