"""07_diff_runs.py — paired BCa diff between two iters with per-source breakdown.

WIRED implementation (2026-05-28 TDD).

Reads:
  runs/<base>/<source>/manifest_results.csv
  runs/<candidate>/<source>/manifest_results.csv

For each axis x source, computes paired delta (candidate - base) on the SAME
zettels (joined by wz_uuid), with paired BCa bootstrap CI + sign-flip
permutation test per "When +1% Is Not Enough" (arxiv 2511.19794).

Writes:
  analysis/diff-<base>-vs-<candidate>/OVERALL.md
  analysis/diff-<base>-vs-<candidate>/per_source/<source>.md
  analysis/diff-<base>-vs-<candidate>/per_axis.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
RUNS = REPO_ROOT / "docs" / "zettel_eval_v1" / "runs"
ANALYSIS = REPO_ROOT / "docs" / "zettel_eval_v1" / "analysis"

# Shared backfilled-row exclusion (Fix #2.1; see lib/aggregable.py).
from docs.zettel_eval_v1.scripts.lib.aggregable import (  # noqa: E402
    is_aggregable_row,
)

# Reuse the bootstrap from 11
sys.path.insert(0, str((REPO_ROOT / "docs" / "zettel_eval_v1" / "scripts").resolve()))
import importlib.util as _ils
_spec = _ils.spec_from_file_location(
    "_select_best", REPO_ROOT / "docs" / "zettel_eval_v1" / "scripts" / "11_select_best.py"
)
_select_best = _ils.module_from_spec(_spec)
_spec.loader.exec_module(_select_best)
_bca_ci_paired = _select_best._bca_ci_paired
_sign_flip_pvalue = _select_best._sign_flip_pvalue
_load_iter_csv = _select_best._load_iter_csv
_paired_join = _select_best._paired_join

DEFAULT_AXES = ("composite", "finesure_faithfulness", "finesure_completeness",
                "finesure_conciseness")


def _discover_sources(base: str, candidate: str) -> list[str]:
    sources = set()
    for it in (base, candidate):
        for p in (RUNS / it).iterdir() if (RUNS / it).exists() else []:
            if p.is_dir() and p.name not in {"_overall"} and (p / "manifest_results.csv").exists():
                sources.add(p.name)
    return sorted(sources)


def _diff_per_source(base: str, candidate: str, source: str, axes: list[str]) -> dict:
    rows_a = _load_iter_csv(base, source)
    rows_b = _load_iter_csv(candidate, source)
    paired_all = _paired_join(rows_a, rows_b)
    # Fix #2.1: drop pairs where EITHER side is backfilled — synthesized
    # neutral 0.5 scores would distort the paired delta.
    paired = [(a, b) for a, b in paired_all
              if is_aggregable_row(a) and is_aggregable_row(b)]
    n_backfilled_excluded = len(paired_all) - len(paired)
    out: dict[str, dict] = {}
    for axis in axes:
        try:
            deltas = [float(b[axis]) - float(a[axis]) for a, b in paired]
        except (KeyError, ValueError):
            deltas = []
        med, lo, hi = _bca_ci_paired(deltas)
        p = _sign_flip_pvalue(deltas)
        sig = (lo > 0) or (hi < 0)
        out[axis] = {
            "median_delta": round(med, 3),
            "ci_low": round(lo, 3),
            "ci_high": round(hi, 3),
            "sign_flip_p": round(p, 4),
            "is_significant": bool(sig),
            "n_paired": len(deltas),
            "n_improvements": sum(1 for d in deltas if d > 0),
            "n_regressions": sum(1 for d in deltas if d < 0),
            "n_backfilled_excluded": n_backfilled_excluded,
        }
    return out


def _wins_losses_per_zettel(base: str, candidate: str, source: str) -> dict:
    """Surface the top 3 wins (candidate >> base) and top 3 regressions per source."""
    rows_a = _load_iter_csv(base, source)
    rows_b = _load_iter_csv(candidate, source)
    paired_all = _paired_join(rows_a, rows_b)
    # Fix #2.1: drop pairs where EITHER side is backfilled — a fake delta from
    # a synthesized 0.5 score would otherwise appear in the top-3 highlight list.
    paired = [(a, b) for a, b in paired_all
              if is_aggregable_row(a) and is_aggregable_row(b)]
    with_delta = []
    for a, b in paired:
        try:
            d = float(b["composite"]) - float(a["composite"])
        except (KeyError, ValueError):
            continue
        with_delta.append({
            "wz_uuid": a["wz_uuid"],
            "title": a.get("title", "")[:60],
            "url": a.get("normalized_url", ""),
            "base_composite": float(a["composite"]),
            "candidate_composite": float(b["composite"]),
            "delta": round(d, 2),
        })
    wins = sorted(with_delta, key=lambda r: -r["delta"])[:3]
    losses = sorted(with_delta, key=lambda r: r["delta"])[:3]
    return {"wins": wins, "regressions": losses}


def _per_source_md(source: str, axis_stats: dict, wl: dict, base: str, candidate: str) -> str:
    # n_backfilled_excluded is the same across axes within a source (it's a
    # property of the underlying paired set, not of the axis).
    first_axis = next(iter(axis_stats.values()), {})
    n_excluded = int(first_axis.get("n_backfilled_excluded", 0))
    excluded_note = f" (excluded {n_excluded} backfilled-pair(s))" if n_excluded else ""
    out = [f"# Diff: `{base}` -> `{candidate}` — source: `{source}`{excluded_note}\n\n",
           "## Per-axis paired delta (candidate - base)\n\n",
           "| Axis | median Δ | CI low | CI high | sign-flip p | Significant? | N | Improved | Regressed |\n",
           "|---|---:|---:|---:|---:|---|---:|---:|---:|\n"]
    for axis, r in axis_stats.items():
        sig = "**YES**" if r["is_significant"] else "no"
        out.append(f"| {axis} | {r['median_delta']:.3f} | {r['ci_low']:.3f} | {r['ci_high']:.3f} | "
                   f"{r['sign_flip_p']:.4f} | {sig} | {r['n_paired']} | "
                   f"{r['n_improvements']} | {r['n_regressions']} |\n")
    out.append("\n## Top-3 candidate wins (largest composite improvement)\n\n")
    for w in wl["wins"]:
        out.append(f"- **+{w['delta']:.2f}** — {w['title']} ({w['url']}) `wz={w['wz_uuid'][:8]}` "
                   f"({w['base_composite']:.1f} → {w['candidate_composite']:.1f})\n")
    out.append("\n## Top-3 candidate regressions (largest composite drop)\n\n")
    for w in wl["regressions"]:
        if w["delta"] >= 0: continue
        out.append(f"- **{w['delta']:.2f}** — {w['title']} ({w['url']}) `wz={w['wz_uuid'][:8]}` "
                   f"({w['base_composite']:.1f} → {w['candidate_composite']:.1f})\n")
    return "".join(out)


def _overall_md(base: str, candidate: str, per_axis: dict, sources: list[str]) -> str:
    # Aggregate backfilled-excluded count across sources via the first axis
    # (same value per axis within a source).
    first_axis_map = next(iter(per_axis.values()), {})
    total_excluded = sum(
        int(r.get("n_backfilled_excluded", 0)) for r in first_axis_map.values()
    )
    excluded_note = (f" (excluded {total_excluded} backfilled-pair(s) across sources)"
                     if total_excluded else "")
    out = [f"# Diff: `{base}` -> `{candidate}` — overall{excluded_note}\n\n",
           "Generated by `07_diff_runs.py`. Paired BCa bootstrap (B=10k) + sign-flip "
           "permutation per *When +1% Is Not Enough* (arXiv 2511.19794).\n\n",
           "## Per-axis aggregate (across all sources)\n\n",
           "| Axis | median Δ | CI low | CI high | sign-flip p | Significant? | N paired |\n",
           "|---|---:|---:|---:|---:|---|---:|\n"]
    for axis, src_map in per_axis.items():
        # Aggregate across sources
        all_n = sum(r["n_paired"] for r in src_map.values())
        # For aggregate, take a weighted-by-N average of medians (rough; full pooled bootstrap would be ideal)
        if all_n == 0:
            out.append(f"| {axis} | n/a | n/a | n/a | n/a | n/a | 0 |\n"); continue
        med_w = sum(r["median_delta"] * r["n_paired"] for r in src_map.values()) / all_n
        lo_w = sum(r["ci_low"] * r["n_paired"] for r in src_map.values()) / all_n
        hi_w = sum(r["ci_high"] * r["n_paired"] for r in src_map.values()) / all_n
        sig = "**YES**" if (lo_w > 0 or hi_w < 0) else "no"
        out.append(f"| {axis} | {med_w:.3f} | {lo_w:.3f} | {hi_w:.3f} | n/a | {sig} | {all_n} |\n")
    out.append(f"\n## Sources analysed\n\n- " + "\n- ".join(sources) + "\n")
    if total_excluded:
        out.append(
            f"\n## Backfilled-excluded pairs ({total_excluded})\n\n"
            "Pairs where EITHER iter's row was tagged `backfilled=1` are EXCLUDED "
            "from the aggregate above and from the per-source wins/losses. "
            "Synthesized 0.5 scores would otherwise distort the paired delta and "
            "surface as fake top-3 wins/regressions.\n"
        )
    out.append(f"\nSee `per_source/<src>.md` for per-source detail.\n")
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--axes", type=str, default=",".join(DEFAULT_AXES))
    args = ap.parse_args()

    axes = [s.strip() for s in args.axes.split(",") if s.strip()]
    sources = _discover_sources(args.base, args.candidate)
    if not sources:
        raise SystemExit("No common sources with manifest_results.csv between base and candidate")

    per_axis: dict[str, dict[str, dict]] = {a: {} for a in axes}
    per_source_payloads: dict[str, tuple[dict, dict]] = {}
    for src in sources:
        stats = _diff_per_source(args.base, args.candidate, src, axes)
        wl = _wins_losses_per_zettel(args.base, args.candidate, src)
        per_source_payloads[src] = (stats, wl)
        for axis, r in stats.items():
            per_axis[axis][src] = r

    diff_dir = ANALYSIS / f"diff-{args.base}-vs-{args.candidate}"
    (diff_dir / "per_source").mkdir(parents=True, exist_ok=True)
    (diff_dir / "OVERALL.md").write_text(_overall_md(args.base, args.candidate, per_axis, sources),
                                          encoding="utf-8")
    for src, (stats, wl) in per_source_payloads.items():
        (diff_dir / "per_source" / f"{src}.md").write_text(
            _per_source_md(src, stats, wl, args.base, args.candidate), encoding="utf-8"
        )
    (diff_dir / "per_axis.json").write_text(
        json.dumps(per_axis, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"[07] wrote {diff_dir / 'OVERALL.md'}")
    print(f"[07] wrote {diff_dir / 'per_axis.json'}")
    print(f"[07] wrote {len(per_source_payloads)} per-source markdowns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
