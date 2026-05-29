"""10_judge_calibration.py — measure judge competence against the smoke bank.

WIRED implementation (2026-05-28 TDD).

Reads:
  _config/judge_calibration_set.json       (18 items, judge-visible)
  _oracle/judge_calibration_oracle.json    (18 answers, judge-HIDDEN)
                                            <- never included in judge prompt;
                                            joined by id at scoring time only

Writes:
  analysis/calibration/<judge>.json        (per-class detection rate + overall_pass)
  analysis/calibration/<judge>.md          (human-readable narrative)

The pre-flight gate (METHODOLOGY §18.7) requires `overall_pass: true` per judge
in the iter's run_matrix row before 02_run_judge.py is permitted to run.

Detection rule: for each calibration item, send (summary_text, source_text) to
the judge with the same evaluator.v7 prompt 02_run_judge.py uses. Parse the
judge's per-class anti_patterns_triggered. Detection counts if the judge
flagged a class within ±1 alias of the seeded ground-truth FRANK class
(e.g. "INVENTED_FACT" -> OutE, "ENTITY_ERROR" -> EntE) — the same
class-aliasing 04_compute_composite.py uses.

Fake-judge mode (for tests + dry-runs):
  --fake-judge                 use the FakeJudge instead of a real LLM
  --fake-mode {correct,wrong}  determines what the fake returns
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

EVAL = REPO_ROOT / "docs" / "zettel_eval_v1"
SET_PATH = EVAL / "_config" / "judge_calibration_set.json"
ORACLE_PATH = EVAL / "_oracle" / "judge_calibration_oracle.json"
ANALYSIS = EVAL / "analysis" / "calibration"
RUBRIC_PATH = REPO_ROOT / "docs" / "summary_eval" / "_config" / "rubric_universal.yaml"

# Mapping from judge-flagged class strings to FRANK-7 canonical labels.
# Mirrors 04_compute_composite.py's _class_counts.
def _canonicalise(cls: str) -> str:
    c = (cls or "").upper()
    if c.startswith("ENTE") or "ENTITY" in c or "INVENTED" in c:
        return "EntE"
    if c.startswith("PREDE") or "PREDICATE" in c or "STANCE" in c:
        return "PredE"
    if c.startswith("CIRCE") or "CIRCUMSTANCE" in c or "MODAL" in c:
        return "CircE"
    if c.startswith("COREFE") or "COREF" in c or "ATTRIBUTION" in c:
        return "CorefE"
    if c.startswith("LINKE") or "LINK" in c or "DISCOURSE" in c:
        return "LinkE"
    if c.startswith("GRAME") or "GRAMMAR" in c:
        return "GramE"
    if c.startswith("OUTE") or "OUT" in c or "HALLUC" in c or "FABRIC" in c:
        return "OutE"
    if "COMPLETE" in c:
        return "completeness"
    if "CONCISE" in c or "REDUND" in c:
        return "conciseness"
    return cls  # unmapped


class FakeJudge:
    """Deterministic stub-judge for tests. NEVER hits an LLM API."""
    def __init__(self, mode: str = "correct", oracle: dict | None = None):
        self.mode = mode
        self.oracle = oracle or {}

    async def evaluate(self, *, item_id: str, **_kwargs):
        """Return a fake EvalResult dict given the calibration item id.
        - mode=correct: return the ground truth from oracle
        - mode=wrong:   return nothing/empty (judge missed the error)
        """
        ans = self.oracle.get(item_id, {})
        if self.mode == "wrong":
            return {"rubric": {"anti_patterns_triggered": []}}
        cls = ans.get("frank_class", "")
        return {"rubric": {"anti_patterns_triggered": [{"class": cls}]}}


async def _evaluate_with_real_judge(judge_kind: str, item: dict, rubric_yaml: dict) -> dict:
    """Use the real judge (Gemini primary or Claude secondary) — same path as 02_run_judge.py."""
    from website.features.summarization_engine.evaluator.consolidated import ConsolidatedEvaluator
    from website.features.summarization_engine.evaluator.atomic_facts import extract_atomic_facts
    if judge_kind == "primary":
        from ops.scripts.lib.gemini_factory import make_client as make_judge
    else:
        from docs.zettel_eval_v1.scripts.lib.anthropic_factory import make_client as make_judge
    from ops.scripts.lib.gemini_factory import make_client as make_gemini_extractor

    extractor = make_gemini_extractor()
    cache_root = EVAL / "_cache"
    atomic = await extract_atomic_facts(
        client=extractor,
        source_text=item["source_text"],
        cache_root=cache_root,
        url=f"calibration://{item['id']}",
        ingestor_version="calib",
    )
    evaluator = ConsolidatedEvaluator(make_judge())
    # The judge expects summary_json as a dict; calibration items have summary_text str.
    # Wrap as {"detailed_summary": ..., "_shape": "general"} so the existing prompt works.
    summary_json = {
        "brief_summary": "",
        "detailed_summary": item["summary_text"],
        "_shape": "general",
    }
    result = await evaluator.evaluate(
        rubric_yaml=rubric_yaml,
        atomic_facts=atomic,
        source_text=item["source_text"],
        summary_json=summary_json,
    )
    return result.model_dump(mode="json")


def _flagged_classes(eval_payload: dict) -> list[str]:
    rubric = eval_payload.get("rubric") or {}
    aps = rubric.get("anti_patterns_triggered") or []
    out = []
    for ap in aps:
        if isinstance(ap, dict):
            cls = ap.get("class") or ap.get("id") or ""
            if cls:
                out.append(_canonicalise(cls))
    return out


async def main_async(args) -> int:
    s = json.loads(SET_PATH.read_text(encoding="utf-8"))
    o = json.loads(ORACLE_PATH.read_text(encoding="utf-8"))
    items = s["items"]
    answers = o["answers"]

    if sum((s.get("items_pending") or {}).values()) > 0 and not args.override_pending:
        raise SystemExit("calibration set has pending items; finish curation or --override-pending.")

    if args.judge == "both":
        judges = ["primary", "secondary"]
    else:
        judges = [args.judge]

    # FAIL CONDITION (overall): any judge whose any-class detection rate < target_rate
    overall_failure_flag = False

    for jk in judges:
        per_item_records = []
        for item in items:
            gt_class = answers.get(item["id"], {}).get("frank_class", "")
            try:
                if args.fake_judge:
                    fj = FakeJudge(mode=args.fake_mode, oracle=answers)
                    payload = await fj.evaluate(item_id=item["id"])
                else:
                    import yaml
                    rubric_yaml = yaml.safe_load(RUBRIC_PATH.read_text(encoding="utf-8"))
                    payload = await _evaluate_with_real_judge(jk, item, rubric_yaml)
            except Exception as exc:
                per_item_records.append({
                    "id": item["id"], "ground_truth": gt_class, "detected_classes": [],
                    "detected": False, "error": f"{type(exc).__name__}: {exc}",
                })
                continue
            flagged = _flagged_classes(payload)
            detected = gt_class in flagged
            per_item_records.append({
                "id": item["id"], "ground_truth": gt_class,
                "detected_classes": flagged, "detected": detected,
            })

        # Per-class detection rate
        by_class_total = Counter()
        by_class_hit = Counter()
        for rec in per_item_records:
            gt = rec["ground_truth"]
            by_class_total[gt] += 1
            if rec["detected"]:
                by_class_hit[gt] += 1

        per_class_rate = {}
        all_target_classes = {"EntE", "PredE", "CircE", "CorefE", "LinkE", "GramE", "OutE",
                              "completeness", "conciseness"}
        for cls in all_target_classes | set(by_class_total.keys()):
            n = by_class_total.get(cls, 0)
            per_class_rate[cls] = round(by_class_hit.get(cls, 0) / n, 3) if n > 0 else 0.0

        overall_pass = all(r >= args.target_rate for r in per_class_rate.values())
        if not overall_pass:
            overall_failure_flag = True

        # Emit reports
        ANALYSIS.mkdir(parents=True, exist_ok=True)
        report = {
            "judge_kind": jk,
            "target_detection_rate_per_class": args.target_rate,
            "per_class_detection_rate": per_class_rate,
            "overall_pass": overall_pass,
            "blocking_failures": [
                rec["id"] for rec in per_item_records
                if not rec["detected"] and not rec.get("error")
            ],
            "errored_items": [
                {"id": rec["id"], "error": rec.get("error")}
                for rec in per_item_records if rec.get("error")
            ],
            "per_item": per_item_records,
            "fake_judge": args.fake_judge,
            "fake_mode": args.fake_mode if args.fake_judge else None,
        }
        (ANALYSIS / f"{jk}.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        md = [f"# Calibration — {jk}\n\n",
              f"- overall_pass: **{overall_pass}**\n",
              f"- target_detection_rate_per_class: {args.target_rate}\n",
              f"- fake_judge: {args.fake_judge} (mode={args.fake_mode if args.fake_judge else 'n/a'})\n\n",
              f"## Per-class detection rate\n\n| Class | Rate |\n|---|---:|\n"]
        for cls in sorted(per_class_rate.keys()):
            md.append(f"| {cls} | {per_class_rate[cls]:.3f} |\n")
        if report["blocking_failures"]:
            md.append("\n## Blocking failures (judge missed these)\n\n")
            for fid in report["blocking_failures"]:
                md.append(f"- {fid}\n")
        (ANALYSIS / f"{jk}.md").write_text("".join(md), encoding="utf-8")

        print(f"[10] judge={jk} overall_pass={overall_pass} per_class={per_class_rate}")

    return 0 if not overall_failure_flag else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--judge", choices=["primary", "secondary", "both"], default="primary")
    ap.add_argument("--target-rate", type=float, default=0.7)
    ap.add_argument("--override-pending", action="store_true")
    ap.add_argument("--emit-detector-coverage", action="store_true",
                    help="(reserved for v2; not used in this script)")
    ap.add_argument("--force-refresh", action="store_true",
                    help="(reserved; calibration items themselves are fixed)")
    ap.add_argument("--fake-judge", action="store_true",
                    help="use FakeJudge instead of real LLM — for tests + dry-runs")
    ap.add_argument("--fake-mode", choices=["correct", "wrong"], default="correct",
                    help="FakeJudge return mode")
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
