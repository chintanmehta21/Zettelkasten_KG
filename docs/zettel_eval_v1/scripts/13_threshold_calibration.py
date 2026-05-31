"""13_threshold_calibration.py — NLI contradict-threshold calibration kit.

⚠️ DO NOT USE FOR A REAL THRESHOLD AT SMALL n. Three-agent research
(docs/claude_audits/nli_threshold_calibration_verdict_2026-05-31.md) established
that data-driven calibration is INVALID at our current label scale, for three
independent reasons:
  1. n~25-50 OVERFITS — operating-point CIs are wide at n<=100 and the cut can't be
     cross-validated (sklearn). Defer until labels reach the HUNDREDS.
  2. A score-stratified sample of our well-grounded corpus is ~ALL "supported"
     (degenerate single-class sweep; recall undefined) — exactly what the 2026-05-31
     probe produced (25 supported / 0 contradicted).
  3. Enriching positives via the LLM JUDGE introduces verification/workup bias
     (judge & NLI are correlated detectors), only partially correctable via IPW.
  And F-beta is prevalence-DEPENDENT, so a cut chosen on an enriched (positive-heavy)
  set over-fires in production unless prevalence-corrected (King-Zeng / IPW).

CURRENT DECISION (2026-05-31): the threshold stays a FIXED 0.70 (see
03_run_nli.py). Under OR-with-review it only sizes the low-priority nli_only review
queue — correctness is owned by the judge_only route — so a fixed default is safe.

WHEN you DO calibrate (labels in the hundreds), the methodologically clean recipe is:
  - enrich rare positives by NLI's OWN near-boundary uncertainty + a random/stratified
    base layer (NOT judge flags);
  - label truthfully against source;
  - select the F-beta(beta>1) cut with examples reweighted to NATURAL prevalence (IPW),
    or recompute F-beta at true prevalence on a representative held-out slice.
This script's --calibrate implements the F-beta sweep but NOT the prevalence
correction — add IPW before trusting its output at scale.

ZERO API: claims + NLI contradict scores are read straight from the per_zettel JSONs.

Two modes:

  --emit       Sample N (claim, source-chunk, nli_contradict_prob) rows, STRATIFIED
               across the contradict_prob range so the decision boundary is well
               covered, into a CSV with an empty `label` column for the operator.

  --calibrate  Read the operator-labeled CSV (label ∈ {supported, contradicted})
               and sweep the threshold; report precision / recall / F-beta /
               Youden's J per threshold and the F-beta-optimal operating point.

Usage:
  # 1. emit the labeling sheet
  python docs/zettel_eval_v1/scripts/13_threshold_calibration.py --emit \
      --iter iter-003-nli --n 25 \
      --out docs/zettel_eval_v1/annotation/threshold_calibration/labels.csv

  # 2. operator opens labels.csv, fills the `label` column (supported|contradicted)

  # 3. calibrate
  python docs/zettel_eval_v1/scripts/13_threshold_calibration.py --calibrate \
      --labeled docs/zettel_eval_v1/annotation/threshold_calibration/labels.csv \
      --beta 2.0
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EVAL = REPO_ROOT / "docs" / "zettel_eval_v1"
RUNS = EVAL / "runs"
ANALYSIS = EVAL / "analysis"

CSV_COLS = ["wz", "claim", "best_chunk_text", "nli_contradict_prob", "label"]
VALID_LABELS = {"supported", "contradicted"}

# Below this labeled-set size a data-driven threshold overfits to label noise
# (operating-point CIs are wide at n<=100; sklearn can't CV the cut). Research
# 2026-05-31 → defer formal calibration until labels reach the hundreds.
MIN_CALIBRATION_N = 200

# Spreadsheets (Excel / Sheets) interpret a cell beginning with any of these as
# a FORMULA, rendering grounded text as `#NAME?` (and a CSV-injection vector).
# Prefix such cells with a leading apostrophe — Excel hides it and shows the
# value as text. Harmless to --calibrate, which never reads the claim text.
_FORMULA_LEAD = ("=", "+", "-", "@")


def _excel_safe(s: str) -> str:
    return "'" + s if s[:1] in _FORMULA_LEAD else s


def _collect_claims(iter_id: str) -> list[dict]:
    """Gather (wz, claim, best_chunk_text, contradict_prob) from per_claim
    entries — STRICTLY from ``nli_v2`` (atomic_facts claim source).

    We deliberately do NOT fall back to v1 ``nli``: the v1 per_claim list is the
    regex sentence-split (markdown bullets / headers / fragments) the v2 pipeline
    replaced. Calibrating the v2 threshold on v1 regex claims would tune against
    the wrong distribution (and reintroduces the `-`/`#`-prefixed noise that
    triggers Excel's `#NAME?`). Only zettels rescored via 03c (route+atomic_facts)
    contribute. Run 03c on more zettels first to widen the calibration pool."""
    p_dir = RUNS / iter_id / "_overall" / "per_zettel"
    if not p_dir.exists():
        raise SystemExit(f"missing {p_dir}; run 03/03c for this iter first.")
    rows: list[dict] = []
    for f in sorted(p_dir.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        nli = d.get("nli_v2")
        if not isinstance(nli, dict) or "error" in nli:
            continue  # atomic_facts (nli_v2) only — no v1 regex fallback
        for c in nli.get("per_claim", []) or []:
            claim = (c.get("claim") or "").strip()
            if not claim:
                continue
            rows.append({
                "wz": f.stem[:8],
                "claim": claim,
                "best_chunk_text": (c.get("best_chunk_text") or "").strip(),
                "nli_contradict_prob": float(c.get("contradict_prob", 0.0)),
            })
    return rows


def _stratified_sample(rows: list[dict], n: int) -> list[dict]:
    """Deterministic stratified sample across the contradict_prob range so the
    labeled set spans the decision boundary rather than clustering at the
    extremes. Bins [0,1] into n slots, takes the median-prob row per non-empty
    bin, then tops up from the densest bins if short. No RNG → reproducible."""
    if len(rows) <= n:
        return sorted(rows, key=lambda r: r["nli_contradict_prob"])
    by_prob = sorted(rows, key=lambda r: r["nli_contradict_prob"])
    picked, used = [], set()
    for i in range(n):
        lo = i / n
        hi = (i + 1) / n
        bin_rows = [r for r in by_prob
                    if lo <= r["nli_contradict_prob"] < hi and id(r) not in used]
        if i == n - 1:  # last bin is closed on the right so 1.0 lands somewhere
            bin_rows = [r for r in by_prob
                        if lo <= r["nli_contradict_prob"] <= hi and id(r) not in used]
        if bin_rows:
            mid = bin_rows[len(bin_rows) // 2]
            picked.append(mid)
            used.add(id(mid))
    # Top up if some bins were empty: pull the still-unused rows nearest the
    # gaps (just take evenly-spaced remaining rows).
    if len(picked) < n:
        remaining = [r for r in by_prob if id(r) not in used]
        step = max(1, len(remaining) // (n - len(picked)))
        picked.extend(remaining[::step][: n - len(picked)])
    return sorted(picked, key=lambda r: r["nli_contradict_prob"])


def _emit(iter_id: str, n: int, out_path: Path) -> int:
    rows = _collect_claims(iter_id)
    if not rows:
        raise SystemExit(f"no claims found in {iter_id}; nothing to label.")
    sample = _stratified_sample(rows, n)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-SIG (BOM) so Excel on Windows detects UTF-8 and renders accented
    # characters (ñ, é, …) instead of mojibake. csv.DictReader on --calibrate
    # transparently strips the BOM.
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLS)
        w.writeheader()
        for r in sample:
            w.writerow({
                "wz": r["wz"],
                "claim": _excel_safe(r["claim"][:300]),
                "best_chunk_text": _excel_safe(r["best_chunk_text"][:300]),
                "nli_contradict_prob": f"{r['nli_contradict_prob']:.4f}",
                "label": "",  # operator fills: supported | contradicted
            })
    print(f"[13] wrote {len(sample)} rows to {out_path}")
    print("[13] open it and fill the `label` column with supported|contradicted, then --calibrate.")
    return 0


def _prf(labeled: list[tuple[float, bool]], t: float, beta: float) -> dict:
    """precision/recall/F-beta + TPR/FPR at threshold t. Positive = contradicted."""
    tp = sum(1 for prob, pos in labeled if prob >= t and pos)
    fp = sum(1 for prob, pos in labeled if prob >= t and not pos)
    fn = sum(1 for prob, pos in labeled if prob < t and pos)
    tn = sum(1 for prob, pos in labeled if prob < t and not pos)
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    b2 = beta * beta
    fbeta = ((1 + b2) * prec * rec / (b2 * prec + rec)) if (b2 * prec + rec) else 0.0
    tpr = rec
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    return {"t": t, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": prec, "recall": rec, "fbeta": fbeta,
            "youden_j": tpr - fpr}


def _calibrate(labeled_path: Path, beta: float) -> int:
    if not labeled_path.exists():
        raise SystemExit(f"missing {labeled_path}; run --emit first and label it.")
    labeled: list[tuple[float, bool]] = []
    skipped = 0
    # utf-8-sig transparently strips the BOM the emit writes (and tolerates a
    # plain utf-8 file the operator may have re-saved).
    with labeled_path.open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            lbl = (row.get("label") or "").strip().lower()
            if lbl not in VALID_LABELS:
                skipped += 1
                continue
            try:
                prob = float(row["nli_contradict_prob"])
            except (KeyError, ValueError):
                skipped += 1
                continue
            labeled.append((prob, lbl == "contradicted"))
    n_pos = sum(1 for _, pos in labeled if pos)
    n_neg = len(labeled) - n_pos
    if not labeled:
        raise SystemExit("no valid labeled rows (label must be supported|contradicted).")
    if n_pos == 0 or n_neg == 0:
        print(f"[13] WARNING: only one class present (pos={n_pos}, neg={n_neg}); "
              "threshold sweep is degenerate. Label a more balanced sample.")
    if len(labeled) < MIN_CALIBRATION_N:
        print(f"[13] WARNING: n={len(labeled)} < {MIN_CALIBRATION_N}. A threshold "
              "fit at this size OVERFITS to label noise (wide operating-point CI, "
              "cannot cross-validate). Per the 2026-05-31 research verdict, treat the "
              "output as EXPLORATORY only — do NOT wire it as the production threshold. "
              "Keep the fixed 0.70 default until labels reach the hundreds (enriched by "
              "NLI's own uncertainty + random-stratified, with IPW prevalence correction).")

    grid = [round(0.05 * i, 2) for i in range(1, 20)]  # 0.05 .. 0.95
    sweep = [_prf(labeled, t, beta) for t in grid]
    best_fbeta = max(sweep, key=lambda r: (r["fbeta"], r["recall"]))
    best_youden = max(sweep, key=lambda r: r["youden_j"])

    out_dir = ANALYSIS / "threshold_calibration"
    out_dir.mkdir(parents=True, exist_ok=True)
    md = [f"# NLI threshold calibration (β={beta})\n\n",
          f"Labeled rows: **{len(labeled)}** ({n_pos} contradicted / {n_neg} supported), "
          f"{skipped} unlabeled/invalid skipped.\n\n",
          "Current inherited threshold: **0.70**. MiniCheck paper default: **0.50**.\n\n",
          f"**F-β-optimal (β={beta}, recall-favoring): t = {best_fbeta['t']}** "
          f"(P={best_fbeta['precision']:.2f} R={best_fbeta['recall']:.2f} "
          f"Fβ={best_fbeta['fbeta']:.3f})  \n",
          f"**Youden's J optimal: t = {best_youden['t']}** (J={best_youden['youden_j']:.3f})\n\n",
          "| t | TP | FP | FN | TN | precision | recall | Fβ | Youden J |\n",
          "|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n"]
    for r in sweep:
        md.append(f"| {r['t']:.2f} | {r['tp']} | {r['fp']} | {r['fn']} | {r['tn']} | "
                  f"{r['precision']:.2f} | {r['recall']:.2f} | {r['fbeta']:.3f} | "
                  f"{r['youden_j']:.3f} |\n")
    (out_dir / "REPORT.md").write_text("".join(md), encoding="utf-8")

    print(f"[13] labeled={len(labeled)} (pos={n_pos} neg={n_neg}) skipped={skipped}")
    print(f"[13] F-beta(β={beta})-optimal threshold = {best_fbeta['t']}  "
          f"(P={best_fbeta['precision']:.2f} R={best_fbeta['recall']:.2f})")
    print(f"[13] Youden's J optimal threshold      = {best_youden['t']}")
    print(f"[13] report -> {out_dir / 'REPORT.md'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--emit", action="store_true", help="Sample N rows for labeling.")
    mode.add_argument("--calibrate", action="store_true", help="Calibrate from labeled CSV.")
    ap.add_argument("--iter", dest="iter_id", default="iter-003-nli")
    ap.add_argument("--n", type=int, default=25, help="Sample size for --emit.")
    ap.add_argument("--out", type=Path,
                    default=EVAL / "annotation" / "threshold_calibration" / "labels.csv")
    ap.add_argument("--labeled", type=Path,
                    default=EVAL / "annotation" / "threshold_calibration" / "labels.csv")
    ap.add_argument("--beta", type=float, default=2.0,
                    help="F-beta beta; >1 favors recall (missed hallucination is worse).")
    args = ap.parse_args()
    if args.emit:
        return _emit(args.iter_id, args.n, args.out)
    return _calibrate(args.labeled, args.beta)


if __name__ == "__main__":
    raise SystemExit(main())
