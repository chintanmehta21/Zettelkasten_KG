"""04_compute_composite.py — assemble composite + per-source aggregates.

WIRED implementation (2026-05-28 TDD).

Inputs:
  runs/<iter>/_overall/per_zettel/<wz_uuid>.json   (and dual-linked <source>/per_zettel/*)

Per-source outputs (one per source folder present):
  runs/<iter>/<source>/manifest_results.csv
  runs/<iter>/<source>/error_class_histogram.json
  runs/<iter>/<source>/source_summary.md
  runs/<iter>/<source>/top_failures.md

Overall outputs:
  runs/<iter>/_overall/manifest_results.csv
  runs/<iter>/_overall/error_class_histogram.json
  runs/<iter>/_overall/top_failures.md
  runs/<iter>/REPORT.md

Composite formula: parity with website/features/summarization_engine/evaluator/models.py::composite_score
  composite = 0.60 * rubric_total + 0.20 * faithfulness*100 + 0.10 * completeness*100 + 0.10 * g_eval_avg
  Then apply rubric caps_applied.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from statistics import mean

# Shared aggregate-exclusion helper (Fix #2.1, 2026-05-30) — single point of
# truth for "should this row count in corpus-mean aggregates?". Importing via
# absolute path so the script works whether invoked as a script or imported
# as a module by the test suite.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from docs.zettel_eval_v1.scripts.lib.aggregable import (  # noqa: E402
    aggregable_rows,
    excluded_count,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNS = REPO_ROOT / "docs" / "zettel_eval_v1" / "runs"
MANIFEST = REPO_ROOT / "docs" / "zettel_eval_v1" / "_config" / "manifest.json"

FRANK_CLASSES = ["EntE", "PredE", "CircE", "CorefE", "LinkE", "GramE", "OutE"]
CSV_COLS = [
    "wz_uuid", "normalized_url", "title", "source_type",
    "rubric_total", "rubric_max_points",
    "finesure_faithfulness", "finesure_completeness", "finesure_conciseness",
    "g_eval_coherence", "g_eval_fluency",
    "composite", "composite_uncapped", "hallucination_cap_hit",
    "judge_kind", "judge_model_used",
    "top_error_class_1", "top_error_class_2", "top_error_class_3",
    # Lane 2 (2026-05-30 Fix #2) — when the judge omitted required EvalResult
    # fields AND the single validation-retry reprompt also failed, the row was
    # synthesized with neutral defaults. ``backfilled=1`` rows MUST be excluded
    # from corpus-mean aggregates; ``backfilled_fields`` names which fields
    # were synthesized so analysts can decide whether to use the row for
    # partial signals (e.g. NLI is still valid even if g_eval was synthesized).
    "backfilled", "backfilled_fields",
]


def _manifest_index() -> dict[str, dict]:
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {z["workspace_zettel_id"]: z for z in m["zettels"]}


def _g_eval_avg(eval_json: dict) -> float:
    g = eval_json.get("g_eval") or {}
    coh = (g.get("coherence") or {}).get("score") or 0
    flu = (g.get("fluency") or {}).get("score") or 0
    # Ordinal 1-3, average and scale to 0..100 via (avg-1)/(3-1) * 100
    avg = (float(coh) + float(flu)) / 2.0
    return max(0.0, min(100.0, (avg - 1) / 2.0 * 100.0))


def _composite(eval_json: dict) -> tuple[float, float, bool]:
    rubric = eval_json.get("rubric") or {}
    components = rubric.get("components") or []
    rubric_total = sum(float(c.get("score", 0)) for c in components)
    rubric_max = sum(float(c.get("max_points", 0)) for c in components)
    rubric_pct = (rubric_total / rubric_max * 100.0) if rubric_max > 0 else 0.0

    fin = eval_json.get("finesure") or {}
    faith = float((fin.get("faithfulness") or {}).get("score") or 0)
    compl = float((fin.get("completeness") or {}).get("score") or 0)
    geval = _g_eval_avg(eval_json)

    base = 0.60 * rubric_pct + 0.20 * faith * 100 + 0.10 * compl * 100 + 0.10 * geval
    caps = rubric.get("caps_applied") or {}
    cap_values = [v for v in caps.values() if isinstance(v, (int, float))]
    capped = min([base] + cap_values) if cap_values else base
    hallucination_hit = bool(caps.get("hallucination_cap"))
    return round(capped, 2), round(base, 2), hallucination_hit


def _top_error_classes(eval_json: dict, k: int = 3) -> list[str]:
    rubric = eval_json.get("rubric") or {}
    aps = rubric.get("anti_patterns_triggered") or []
    seen = []
    for ap in aps:
        if isinstance(ap, dict):
            cls = ap.get("class") or ap.get("id")
            if cls and cls not in seen:
                seen.append(cls)
                if len(seen) == k:
                    break
    return seen + [""] * (k - len(seen))


def _class_counts(eval_json: dict) -> Counter:
    """Per-FRANK-class hit count for this zettel (multi-class possible)."""
    c = Counter()
    rubric = eval_json.get("rubric") or {}
    for ap in rubric.get("anti_patterns_triggered") or []:
        if isinstance(ap, dict):
            cls = (ap.get("class") or ap.get("id") or "").upper()
            # Map common labels to FRANK classes (best-effort, lowercase tolerant)
            if cls.startswith("ENTE") or "ENTITY" in cls or "INVENTED" in cls:
                c["EntE"] += 1
            elif cls.startswith("PREDE") or "PREDICATE" in cls or "STANCE" in cls:
                c["PredE"] += 1
            elif cls.startswith("CIRCE") or "CIRCUMSTANCE" in cls or "MODAL" in cls:
                c["CircE"] += 1
            elif cls.startswith("COREFE") or "COREF" in cls or "ATTRIBUTION" in cls:
                c["CorefE"] += 1
            elif cls.startswith("LINKE") or "LINK" in cls or "DISCOURSE" in cls:
                c["LinkE"] += 1
            elif cls.startswith("GRAME") or "GRAMMAR" in cls:
                c["GramE"] += 1
            elif cls.startswith("OUTE") or "OUT" in cls or "HALLUC" in cls or "FABRIC" in cls:
                c["OutE"] += 1
    return c


def _row_for_zettel(payload: dict, manifest_entry: dict | None) -> dict:
    composite, uncapped, hcap = _composite(payload)
    fin = payload.get("finesure") or {}
    g = payload.get("g_eval") or {}
    meta = payload.get("_meta") or {}
    rubric = payload.get("rubric") or {}
    components = rubric.get("components") or []
    rubric_total = sum(float(c.get("score", 0)) for c in components)
    rubric_max = sum(float(c.get("max_points", 0)) for c in components)
    top = _top_error_classes(payload)
    # Lane 2 backfill capture: surface synthesized-field provenance up to the
    # row level so per-source / per-iter aggregates can EXCLUDE these rows.
    ev_meta = payload.get("evaluator_metadata") or {}
    backfilled_fields = ev_meta.get("backfilled_fields") or []
    return {
        "wz_uuid": meta.get("wz_zettel_id", ""),
        "normalized_url": (manifest_entry or {}).get("normalized_url", ""),
        "title": (manifest_entry or {}).get("title", ""),
        "source_type": meta.get("source_type", ""),
        "rubric_total": round(rubric_total, 2),
        "rubric_max_points": int(rubric_max),
        "finesure_faithfulness": round(float((fin.get("faithfulness") or {}).get("score") or 0), 3),
        "finesure_completeness": round(float((fin.get("completeness") or {}).get("score") or 0), 3),
        "finesure_conciseness": round(float((fin.get("conciseness") or {}).get("score") or 0), 3),
        "g_eval_coherence": int((g.get("coherence") or {}).get("score") or 0),
        "g_eval_fluency": int((g.get("fluency") or {}).get("score") or 0),
        "composite": composite,
        "composite_uncapped": uncapped,
        "hallucination_cap_hit": int(hcap),
        "judge_kind": meta.get("judge_kind", ""),
        "judge_model_used": meta.get("judge_model_used", ""),
        "top_error_class_1": top[0],
        "top_error_class_2": top[1],
        "top_error_class_3": top[2],
        "backfilled": 1 if backfilled_fields else 0,
        "backfilled_fields": ";".join(backfilled_fields) if backfilled_fields else "",
    }


_JURY_NUMERIC_COLS = [
    "rubric_total", "rubric_max_points", "finesure_faithfulness",
    "finesure_completeness", "finesure_conciseness", "g_eval_coherence",
    "g_eval_fluency", "composite", "composite_uncapped",
]
_TRUEY = {"1", "true", "True"}


def _collapse_jury(rows: list[dict]) -> tuple[list[dict], bool]:
    """Collapse per-judge rows into ONE jury_mean row per wz_uuid — PoLL
    mean-of-judges (Verga 2024; operator decision 2026-05-31). Numeric metrics
    are averaged across judges; hallucination_cap_hit / backfilled are OR'd
    (a zettel a jury collapses is flagged if EITHER judge flagged it);
    backfilled_fields are unioned; judge_kind becomes 'jury_mean'.

    Single-judge iters (001/002/003/005) have exactly one row per wz_uuid →
    returns (rows, False) UNCHANGED (byte-identical, no downstream impact).
    Only multi-judge iters (iter-004) collapse; returns (collapsed, True)."""
    by_wz: dict[str, list[dict]] = {}
    order: list[str] = []
    for r in rows:
        wz = r["wz_uuid"]
        if wz not in by_wz:
            by_wz[wz] = []
            order.append(wz)
        by_wz[wz].append(r)
    if not any(len(g) > 1 for g in by_wz.values()):
        return rows, False
    out: list[dict] = []
    for wz in order:
        group = by_wz[wz]
        base = dict(group[0])
        for col in _JURY_NUMERIC_COLS:
            vals = []
            for g in group:
                try:
                    vals.append(float(g.get(col, "")))
                except (TypeError, ValueError):
                    pass
            base[col] = round(sum(vals) / len(vals), 4) if vals else ""
        base["hallucination_cap_hit"] = "1" if any(
            str(g.get("hallucination_cap_hit")) in _TRUEY for g in group) else "0"
        base["backfilled"] = "1" if any(
            str(g.get("backfilled")) in _TRUEY for g in group) else "0"
        bf: set[str] = set()
        for g in group:
            if g.get("backfilled_fields"):
                bf.update(x for x in str(g["backfilled_fields"]).split(";") if x)
        base["backfilled_fields"] = ";".join(sorted(bf))
        base["judge_kind"] = "jury_mean"
        base["judge_model_used"] = "+".join(sorted(
            {str(g.get("judge_model_used", "")) for g in group if g.get("judge_model_used")}))
        out.append(base)
    return out, True


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CSV_COLS})


def _write_histogram(path: Path, payloads: list[dict]) -> None:
    counts = Counter({k: 0 for k in FRANK_CLASSES})
    for p in payloads:
        counts.update(_class_counts(p))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({k: int(counts.get(k, 0)) for k in FRANK_CLASSES},
                   indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _top_failures_md(rows: list[dict], top_n: int = 5) -> str:
    if not rows:
        return "No failures to report (no rows).\n"
    rows_sorted = sorted(rows, key=lambda r: r["composite"])
    out = [f"# Top {min(top_n, len(rows_sorted))} failures by composite\n"]
    for r in rows_sorted[:top_n]:
        out.append(
            f"- **{r['composite']:.1f}/100** — `{r['source_type']}` "
            f"[{r['title'][:60]}]({r['normalized_url']}) "
            f"`wz={r['wz_uuid'][:8]}` "
            f"top_errors={r['top_error_class_1'] or '(none)'}\n"
        )
    return "".join(out)


def _source_summary_md(src: str, rows: list[dict], hist: dict[str, int]) -> str:
    if not rows:
        return f"# {src}\n\nNo zettels in this source folder.\n"
    # Lane 2 Fix #2 + #2.1: EXCLUDE backfilled rows from corpus-mean stats
    # so synthesized defaults don't bias the means toward 0.5 / level-1.
    # Rows remain in the CSV (with backfilled=1) so analysts can still
    # inspect them. Histogram + FRANK classes include all rows since those
    # signals may still be partially valid (e.g. NLI runs locally on real
    # text). Uses the shared ``aggregable_rows`` helper to keep the
    # exclusion logic in one place across 04 / 06 / 07 / 11.
    aggregable = aggregable_rows(rows)
    excluded = excluded_count(rows)
    if not aggregable:
        return (
            f"# Source: {src}\n\n"
            f"- N zettels: {len(rows)} (ALL backfilled — no aggregable rows)\n"
            f"- See manifest_results.csv for the synthesized-field provenance.\n"
        )
    mean_composite = mean(r["composite"] for r in aggregable)
    mean_faith = mean(r["finesure_faithfulness"] for r in aggregable)
    mean_compl = mean(r["finesure_completeness"] for r in aggregable)
    mean_conc = mean(r["finesure_conciseness"] for r in aggregable)
    top_class = max(hist.items(), key=lambda kv: kv[1])
    out = [
        f"# Source: {src}\n\n",
        f"- N zettels: {len(rows)}"
        + (f" ({excluded} backfilled-excluded; N={len(aggregable)} aggregated)"
           if excluded else "")
        + "\n",
        f"- Composite mean: {mean_composite:.2f} / 100\n",
        f"- Faithfulness mean: {mean_faith:.3f}\n",
        f"- Completeness mean: {mean_compl:.3f}\n",
        f"- Conciseness mean: {mean_conc:.3f}\n",
        f"- Most-fired FRANK class: {top_class[0]} ({top_class[1]} hits)\n",
        f"- Per-class histogram: `{hist}`\n",
    ]
    return "".join(out)


def _iter_report_md(iter_id: str, per_source: dict[str, list[dict]],
                    overall_hist: dict[str, int]) -> str:
    all_rows = [r for rs in per_source.values() for r in rs]
    if not all_rows:
        return f"# {iter_id}\n\nNo rows.\n"
    # Lane 2 Fix #2 + #2.1: shared helper for exclusion across all aggregators.
    aggregable = aggregable_rows(all_rows)
    excluded = excluded_count(all_rows)
    if not aggregable:
        return (
            f"# REPORT — {iter_id}\n\n"
            f"All {len(all_rows)} rows were backfilled — no aggregable means.\n"
            f"See manifest_results.csv for synthesized-field provenance.\n"
        )
    out = [
        f"# REPORT — {iter_id}\n\n",
        "Generated by `04_compute_composite.py`.\n\n",
        f"## Aggregate (N={len(aggregable)} zettels"
        + (f"; {excluded} backfilled-excluded" if excluded else "")
        + ")\n",
        f"- Composite mean: {mean(r['composite'] for r in aggregable):.2f} / 100\n",
        f"- Faithfulness mean: {mean(r['finesure_faithfulness'] for r in aggregable):.3f}\n",
        f"- Completeness mean: {mean(r['finesure_completeness'] for r in aggregable):.3f}\n",
        f"- Conciseness mean: {mean(r['finesure_conciseness'] for r in aggregable):.3f}\n\n",
        "## Per-source composite means\n\n| Source | N (aggregated) | Composite mean | Top FRANK |\n|---|---:|---:|---|\n",
    ]
    for src, rows in sorted(per_source.items()):
        src_aggregable = aggregable_rows(rows)
        if not src_aggregable:
            out.append(f"| {src} | 0 | n/a | (all backfilled) |\n")
            continue
        m_comp = mean(r["composite"] for r in src_aggregable)
        out.append(f"| {src} | {len(src_aggregable)} | {m_comp:.2f} | (see histogram) |\n")
    out.append("\n## FRANK-7 aggregate histogram\n\n")
    for k in FRANK_CLASSES:
        out.append(f"- {k}: {overall_hist.get(k, 0)}\n")
    if excluded:
        out.append(
            f"\n## Backfilled-excluded rows ({excluded})\n\n"
            f"Rows where the judge omitted required fields AND the validation-"
            f"retry reprompt also failed. Synthesized with neutral defaults to "
            f"keep the pipeline alive; EXCLUDED from corpus-mean stats above to "
            f"avoid biasing the judge mean. See manifest_results.csv "
            f"`backfilled_fields` column for per-row provenance.\n"
        )
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iter", required=True, dest="iter_id")
    args = ap.parse_args()

    iter_dir = RUNS / args.iter_id
    if not iter_dir.exists():
        raise SystemExit(f"iter dir not found: {iter_dir}")

    overall_pz = iter_dir / "_overall" / "per_zettel"
    if not overall_pz.exists():
        raise SystemExit(f"_overall/per_zettel not found: {overall_pz}")

    manifest = _manifest_index()

    # Load all per-zettel payloads via _overall (single source of truth)
    all_payloads: list[dict] = []
    for f in sorted(overall_pz.glob("*.json")):
        all_payloads.append(json.loads(f.read_text(encoding="utf-8")))

    if not all_payloads:
        print(f"[04] No per_zettel JSON in {overall_pz}; nothing to aggregate.")
        return 0

    # Build per-(zettel, judge) rows, then collapse multi-judge (jury) iters to
    # one jury_mean row per zettel so downstream (06/07/11, which join by
    # wz_uuid) see a single composite. Single-judge iters pass through unchanged.
    per_judge_rows = [_row_for_zettel(p, manifest.get(p.get("_meta", {}).get("wz_zettel_id"))) for p in all_payloads]
    rows, is_jury = _collapse_jury(per_judge_rows)

    # Group the COLLAPSED rows by source_type (1 row/zettel even for juries).
    per_source_rows: dict[str, list[dict]] = {}
    for r in rows:
        per_source_rows.setdefault(r["source_type"] or "unknown", []).append(r)
    # Histograms aggregate the raw per-judge payloads (error-class counts —
    # per-judge granularity is fine and more informative there).
    per_source_payloads: dict[str, list[dict]] = {}
    for p in all_payloads:
        src = (p.get("_meta") or {}).get("source_type") or "unknown"
        per_source_payloads.setdefault(src, []).append(p)

    # _overall
    _write_csv(iter_dir / "_overall" / "manifest_results.csv", rows)
    if is_jury:
        # Audit sidecar: the un-collapsed per-judge rows (jury provenance).
        _write_csv(iter_dir / "_overall" / "manifest_results_per_judge.csv", per_judge_rows)
    _write_histogram(iter_dir / "_overall" / "error_class_histogram.json", all_payloads)
    (iter_dir / "_overall" / "top_failures.md").write_text(
        _top_failures_md(rows, top_n=10), encoding="utf-8"
    )

    # Per-source
    overall_hist = json.loads((iter_dir / "_overall" / "error_class_histogram.json").read_text(encoding="utf-8"))
    for src, src_rows in per_source_rows.items():
        src_dir = iter_dir / src
        _write_csv(src_dir / "manifest_results.csv", src_rows)
        _write_histogram(src_dir / "error_class_histogram.json", per_source_payloads[src])
        hist = json.loads((src_dir / "error_class_histogram.json").read_text(encoding="utf-8"))
        (src_dir / "source_summary.md").write_text(
            _source_summary_md(src, src_rows, hist), encoding="utf-8"
        )
        (src_dir / "top_failures.md").write_text(
            _top_failures_md(src_rows, top_n=5), encoding="utf-8"
        )

    # iter-level REPORT.md
    (iter_dir / "REPORT.md").write_text(
        _iter_report_md(args.iter_id, per_source_rows, overall_hist), encoding="utf-8"
    )

    n_sources = len(per_source_rows)
    print(f"[04] iter={args.iter_id} | N={len(rows)} zettels | sources={n_sources} | wrote per-source CSV + histograms + REPORT.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
