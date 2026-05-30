"""03c_rescore_nli_v2.py — replay iter-003-nli hard-fails with the fixed pipeline.

ZERO API spend by design:
- Claims re-derived from atomic_facts cache (already on disk, populated during
  iter-001/002 judging — no Gemini call).
- LLM judge contradicted-sentence count read from the existing per_zettel JSON
  (no judge rerun).
- Only MiniCheck-DeBERTa NLI inference runs (local CPU).

Reads:
  runs/<iter>/_overall/per_zettel/<wz>.json  — existing v1 NLI + judge fields
  _data/<wz>/source_text.md                  — same source MiniCheck saw in v1
  _data/<wz>/meta.json                       — normalized_url + source_type
  _cache/atomic_facts/<sha>.json             — cached atomic facts (key derived
                                               from meta_json + PROMPT_VERSION)

Writes:
  runs/<iter>/_overall/per_zettel/<wz>.json   — ADDS `nli_v2` (v1 untouched)
  runs/<iter>/<source>/per_zettel/<wz>.json   — mirrored
  analysis/<iter>/RESCORE_V2.md               — residual hard-fail report

Methodology (v2 vs v1):
  v1 (broken):
    - claim source: regex sentence-split on detailed_summary
    - hard_fail = (max_con >= 0.7)  [standalone NLI, violates yaml spec]
  v2 (fixed):
    - claim source: atomic_facts cache (FActScore/RAGAS/FineSurE standard)
    - hard_fail = (max_con >= 0.7) AND (judge.summac_lite.contradicted_sentences != [])
      per nli_config.yaml:34-36 — preserves real grounding-gap signal while
      suppressing context-stripped-bullet false positives (Agent A/E findings
      2026-05-30).
"""
from __future__ import annotations

import argparse
import importlib.util as _ils
import json
import sys
from pathlib import Path
from statistics import mean

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

# Reuse predictor + (FIXED) claim extractor + AND-gate logic from 03_run_nli.
# The script's filename starts with a digit so we can't ``import`` it cleanly;
# load via spec instead. This is deliberate — keeping the v2 logic
# single-sourced in 03_run_nli ensures the rescore can never drift from
# the canonical pipeline (and from a future full rerun).
_spec = _ils.spec_from_file_location(
    "_run_nli_mod",
    REPO_ROOT / "docs" / "zettel_eval_v1" / "scripts" / "03_run_nli.py",
)
_run_nli = _ils.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_run_nli)

MiniCheckPredictor = _run_nli.MiniCheckPredictor
FakeMiniCheck = _run_nli.FakeMiniCheck
_extract_claims = _run_nli._extract_claims
route_verdict = _run_nli.route_verdict
HARD_FAIL_CONTRADICT_THRESHOLD = _run_nli.HARD_FAIL_CONTRADICT_THRESHOLD

EVAL = REPO_ROOT / "docs" / "zettel_eval_v1"
RUNS = EVAL / "runs"
DATA = EVAL / "_data"
ANALYSIS = EVAL / "analysis"


def _rescore_one(payload: dict, predictor, batch_size: int = 8) -> dict:
    """Compute the v2 `nli` dict for a single per_zettel payload. Pure function
    — does NOT mutate ``payload``; caller composes the merge."""
    wz_id = (payload.get("_meta") or {}).get("wz_zettel_id", "?")
    data_dir = DATA / wz_id
    source_path = data_dir / "source_text.md"
    if not source_path.exists():
        return {"error": f"source_text.md missing for {wz_id}"}
    source_text = source_path.read_text(encoding="utf-8", errors="replace")

    summary_json = None
    summary_path = data_dir / "summary.json"
    if summary_path.exists():
        try:
            summary_json = json.loads(summary_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass

    meta_json = None
    meta_path = data_dir / "meta.json"
    if meta_path.exists():
        try:
            meta_json = json.loads(meta_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass

    claims, claim_source = _extract_claims(payload, summary_json, meta_json)
    per_claim = predictor.predict_batch(claims, source_text, batch_size=batch_size)

    judge_contras = (payload.get("summac_lite") or {}).get("contradicted_sentences") or []
    judge_contras_n = len(judge_contras)

    if not per_claim:
        route, review_reason = route_verdict(False, judge_contras_n)
        return {
            "n_claims": 0, "mean_entailment": 1.0, "max_contradict": 0.0,
            "nli_threshold_flag": False,
            "judge_contradicted_count": judge_contras_n,
            "route": route, "review_reason": review_reason,
            "hard_fail_flagged": route == "hard_fail", "per_claim": [],
            "nli_model": predictor.model_name,
            "claim_source": claim_source,
            "_methodology": "v2_or_with_review_atomic_facts",
        }

    mean_ent = mean(p["entail_prob"] for p in per_claim)
    max_con = max(p["contradict_prob"] for p in per_claim)
    nli_flag = max_con >= HARD_FAIL_CONTRADICT_THRESHOLD
    route, review_reason = route_verdict(nli_flag, judge_contras_n)
    return {
        "n_claims": len(per_claim),
        "mean_entailment": round(mean_ent, 4),
        "max_contradict": round(max_con, 4),
        "nli_threshold_flag": nli_flag,
        "judge_contradicted_count": judge_contras_n,
        "route": route,
        "review_reason": review_reason,
        "hard_fail_flagged": route == "hard_fail",
        "per_claim": per_claim,
        "nli_model": predictor.model_name,
        "claim_source": claim_source,
        "_methodology": "v2_or_with_review_atomic_facts",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iter", default="iter-003-nli", dest="iter_id")
    ap.add_argument("--fake-nli", action="store_true",
                    help="Use FakeMiniCheck stub (smoke test only — no real scoring).")
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--all", action="store_true",
                    help="Rescore ALL zettels (default: only v1 hard-fails).")
    ap.add_argument("--resume", action="store_true",
                    help="Skip zettels that already have an nli_v2 block (safe to "
                         "re-run after an interruption; only the unscored remainder runs).")
    ap.add_argument("--sample-clean", type=int, default=0, metavar="N",
                    help="ALSO rescore N v1-CLEAN zettels (sanity batch). Verifies the "
                         "atomic_facts switch doesn't surface NEW hard-fails the noisy "
                         "v1 gate masked. Deterministic even-spaced selection by wz_uuid.")
    args = ap.parse_args()

    iter_dir = RUNS / args.iter_id
    overall_dir = iter_dir / "_overall" / "per_zettel"
    if not overall_dir.exists():
        raise SystemExit(f"Missing {overall_dir}; expected populated iter dir.")

    predictor = FakeMiniCheck() if args.fake_nli else MiniCheckPredictor(device="cpu")

    files = sorted(overall_dir.glob("*.json"))
    print(f"[03c] iter={args.iter_id} total_zettels_in_iter={len(files)}", flush=True)

    def _already_scored(payload: dict) -> bool:
        v2 = payload.get("nli_v2")
        return isinstance(v2, dict) and "error" not in v2

    target = []
    clean_pool = []  # v1-clean candidates for the sanity sample
    skipped_resume = 0
    for f in files:
        payload = json.loads(f.read_text(encoding="utf-8"))
        v1_hf = (payload.get("nli") or {}).get("hard_fail_flagged", False)
        if args.resume and _already_scored(payload):
            skipped_resume += 1
            continue
        if args.all or v1_hf:
            target.append((f, payload))
        elif args.sample_clean:
            clean_pool.append((f, payload))

    # Deterministic even-spaced sample from the v1-clean pool (no RNG → fully
    # reproducible). Sorted by wz_uuid then strided so the sample spans the
    # corpus rather than clustering at the alphabetical head.
    n_sampled = 0
    if args.sample_clean and clean_pool and not args.all:
        clean_pool.sort(key=lambda t: t[0].stem)
        n = min(args.sample_clean, len(clean_pool))
        step = max(1, len(clean_pool) // n)
        sampled = clean_pool[::step][:n]
        target.extend(sampled)
        n_sampled = len(sampled)

    cohort = "all" if args.all else "v1 hard-fails"
    if n_sampled:
        cohort += f" + {n_sampled} clean-sanity"
    resume_note = f" (resume: skipped {skipped_resume} already-scored)" if skipped_resume else ""
    print(f"[03c] rescoring {len(target)} zettel(s) ({cohort}){resume_note}", flush=True)

    for i, (f, payload) in enumerate(target, start=1):
        wz8 = f.stem[:8]
        nli_v2 = _rescore_one(payload, predictor, batch_size=args.batch_size)
        payload["nli_v2"] = nli_v2

        src_type = (payload.get("_meta") or {}).get("source_type", "")
        mirror = iter_dir / src_type / "per_zettel" / f.name if src_type else None
        f.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if mirror is not None and mirror.exists():
            mirror.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        hf2 = nli_v2.get("hard_fail_flagged")
        max_con2 = nli_v2.get("max_contradict", 0.0)
        cs = nli_v2.get("claim_source", "?")
        v1_max = (payload.get("nli") or {}).get("max_contradict", 0.0)
        print(f"  [{i}/{len(target)}] {wz8}  v1.max_con={v1_max:.3f} v2.max_con={max_con2:.3f}  "
              f"hard_fail_v2={hf2}  src={cs}", flush=True)

    # Build the report from ALL nli_v2 blocks on disk (not just this run's
    # target) so a resumed/partial run still emits a complete picture.
    # OR-with-review routing (route field): hard_fail / review(judge_only|nli_only) / clean.
    # Cross-tabbed with the v1 hard_fail flag so the sanity cohort surfaces
    # "newly_surfaced" = a v1-clean zettel that now routes to hard_fail/review.
    buckets = {"hard_fail": [], "review_judge": [], "review_nli": [], "clean": []}
    newly_surfaced = []  # v1-clean but v2 route in {hard_fail, review}
    for f in files:
        payload = json.loads(f.read_text(encoding="utf-8"))
        nli_v2 = payload.get("nli_v2")
        if not isinstance(nli_v2, dict) or "error" in nli_v2:
            continue
        route = nli_v2.get("route") or ("hard_fail" if nli_v2.get("hard_fail_flagged") else "clean")
        rr = nli_v2.get("review_reason", "")
        v1_hf = bool((payload.get("nli") or {}).get("hard_fail_flagged", False))
        rec = {
            "wz": f.stem[:8],
            "max_con": nli_v2.get("max_contradict", 0.0),
            "v1_max_con": (payload.get("nli") or {}).get("max_contradict", 0.0),
            "n_claims": nli_v2.get("n_claims"),
            "judge_n": nli_v2.get("judge_contradicted_count"),
            "claim_source": nli_v2.get("claim_source", "?"),
            "route": route, "review_reason": rr,
        }
        if route == "hard_fail":
            buckets["hard_fail"].append(rec)
        elif route == "review" and rr == "judge_only":
            buckets["review_judge"].append(rec)
        elif route == "review":
            buckets["review_nli"].append(rec)
        else:
            buckets["clean"].append(rec)
        if (not v1_hf) and route in ("hard_fail", "review"):
            newly_surfaced.append(rec)

    def _tbl(rows, sort_key):
        out = ["| wz | route | v2.max_con | v1.max_con | n_claims | judge_n | claim_source |\n",
               "|---|---|---:|---:|---:|---:|---|\n"]
        for r in sorted(rows, key=sort_key):
            rt = r["route"] + (f"/{r['review_reason']}" if r["review_reason"] else "")
            out.append(f"| {r['wz']} | {rt} | {r['max_con']:.4f} | {r['v1_max_con']:.4f} | "
                       f"{r['n_claims']} | {r['judge_n']} | {r['claim_source']} |\n")
        return "".join(out)

    out_dir = ANALYSIS / args.iter_id
    out_dir.mkdir(parents=True, exist_ok=True)
    total_scored = sum(len(v) for v in buckets.values())
    md = []
    md.append(f"# RESCORE v2 — {args.iter_id}\n\n")
    md.append("Re-scored NLI on iter-003-nli using the FIXED pipeline + OR-with-review routing.\n\n")
    md.append("**Pipeline changes:**\n\n")
    md.append("| Stage | v1 (broken) | v2 (fixed) |\n|---|---|---|\n")
    md.append("| Claim source | regex sentence-split on `detailed_summary` | "
              "**atomic_facts cache** (FActScore/RAGAS/FineSurE) |\n")
    md.append(f"| Combination | `max_con >= {HARD_FAIL_CONTRADICT_THRESHOLD}` (standalone NLI) | "
              "**OR-with-review** — both fire → hard_fail; one fires → review; neither → clean "
              "(deep-research verdict 2026-05-30, drops strict-AND's judge-false-negative veto) |\n\n")
    md.append(f"**Total v2 blocks on disk:** {total_scored}  \n")
    md.append(f"**This run rescored:** {len(target)} ({cohort})  \n\n")
    md.append("## Routing breakdown\n\n")
    md.append("| Route | Count | Meaning |\n|---|---:|---|\n")
    md.append(f"| **hard_fail** (NLI≥{HARD_FAIL_CONTRADICT_THRESHOLD} ∧ judge>0) | "
              f"{len(buckets['hard_fail'])} | auto-fail, high confidence |\n")
    md.append(f"| **review / judge_only** (judge>0, NLI<{HARD_FAIL_CONTRADICT_THRESHOLD}) | "
              f"{len(buckets['review_judge'])} | judge caught, NLI under threshold — human queue |\n")
    md.append(f"| **review / nli_only** (NLI≥{HARD_FAIL_CONTRADICT_THRESHOLD}, judge=0) | "
              f"{len(buckets['review_nli'])} | NLI caught, judge lenient — human queue |\n")
    md.append(f"| **clean** (neither) | {len(buckets['clean'])} | dropped |\n\n")
    if newly_surfaced:
        md.append(f"**Sanity note:** {len(newly_surfaced)} v1-CLEAN zettel(s) now route to "
                  "hard_fail/review under atomic_facts — review whether the v1 gate masked a real gap.\n\n")

    md.append("## hard_fail (auto-fail — both signals agree)\n\n")
    md.append("_None._\n\n" if not buckets["hard_fail"]
              else _tbl(buckets["hard_fail"], lambda x: -x["max_con"]) + "\n")
    md.append("## review / judge_only (judge caught, NLI missed — incl. the AND-gate's prior false-negatives)\n\n")
    md.append("_None._\n\n" if not buckets["review_judge"]
              else _tbl(buckets["review_judge"], lambda x: -x["judge_n"]) + "\n")
    md.append("## review / nli_only (NLI caught, judge lenient — many are NLI false-positives, triage)\n\n")
    md.append("_None._\n\n" if not buckets["review_nli"]
              else _tbl(buckets["review_nli"], lambda x: -x["max_con"]) + "\n")

    (out_dir / "RESCORE_V2.md").write_text("".join(md), encoding="utf-8")
    print(f"[03c] DONE.  hard_fail={len(buckets['hard_fail'])}  "
          f"review_judge={len(buckets['review_judge'])}  review_nli={len(buckets['review_nli'])}  "
          f"clean={len(buckets['clean'])}", flush=True)
    print(f"[03c] report -> {out_dir / 'RESCORE_V2.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
