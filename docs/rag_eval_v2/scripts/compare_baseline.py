"""rag_eval_v2 — baseline vs current delta + cross-Kasten aggregate.

Offline, read-only. Compares each Kasten's iter-N eval.json against its
baseline_score.json (the iter-11 legacy composite reference) and reports:

  * composite + per-stage component delta
  * trust-first holistic delta (gold@1 / accuracy_user_visible / over/under-refusal)
  * a cross-Kasten aggregate so an improvement isn't overfit to one Kasten
  * actionable next-iter recommendations

Usage:
    python docs/rag_eval_v2/scripts/compare_baseline.py --iter 1
    python docs/rag_eval_v2/scripts/compare_baseline.py --iter 1 --kasten economics
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RAG_EVAL_V2 = ROOT / "docs" / "rag_eval_v2"
KASTENS = ("psychedelic-drugs", "economics")


def _load(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _delta(cur: float | None, base: float | None) -> float | None:
    if cur is None or base is None:
        return None
    return round(float(cur) - float(base), 4)


def compare_one(kasten: str, iter_n: int) -> dict:
    kdir = RAG_EVAL_V2 / kasten
    base = _load(kdir / "baseline_score.json") or {}
    cur = _load(kdir / f"iter-{iter_n}" / "eval.json")
    if cur is None:
        return {"kasten": kasten, "status": "no_eval", "iter": iter_n}

    cur_comp = cur.get("composite")
    base_comp = base.get("composite")
    cur_cs = (cur.get("component_scores") or {})
    base_cs = (base.get("components") or {})
    cur_h = cur.get("holistic") or {}
    base_h = base.get("holistic") or {}

    comp_delta = _delta(cur_comp, base_comp)
    stage_delta = {
        s: _delta(cur_cs.get(s), base_cs.get(s))
        for s in ("chunking", "retrieval", "reranking", "synthesis")
    }
    holistic_delta = {
        k: _delta(cur_h.get(k), base_h.get(k))
        for k in ("gold_at_1_unconditional", "gold_at_1_within_budget",
                  "gold_at_3", "gold_at_8")
    }

    recs: list[str] = []
    if comp_delta is not None and comp_delta < 0:
        worst = min(
            ((s, d) for s, d in stage_delta.items() if d is not None),
            key=lambda kv: kv[1], default=(None, None),
        )
        if worst[0]:
            recs.append(
                f"composite regressed {comp_delta:+.2f} vs legacy bar; "
                f"weakest stage '{worst[0]}' ({worst[1]:+.2f}) is the iter target"
            )
    g1 = cur_h.get("gold_at_1_unconditional")
    if isinstance(g1, (int, float)) and g1 < 0.6:
        recs.append(
            f"gold@1={g1:.3f} < 0.60 — inspect failure_analysis.md: "
            "retrieval-miss vs rerank-miss split drives the fix"
        )
    orr = cur_h.get("over_refusal_rate")
    if isinstance(orr, (int, float)) and orr > 0.15:
        recs.append(
            f"over_refusal_rate={orr:.3f} high — synth refused with gold "
            "retrieved; check coverage/floor gates"
        )
    if not recs:
        recs.append("no automatic regression flag for this Kasten")

    return {
        "kasten": kasten,
        "iter": iter_n,
        "status": "ok",
        "composite": {"baseline": base_comp, "current": cur_comp, "delta": comp_delta},
        "component_delta": stage_delta,
        "holistic": {
            "current": {k: cur_h.get(k) for k in
                        ("gold_at_1_unconditional", "accuracy_user_visible",
                         "over_refusal_rate", "under_refusal_rate")},
            "delta": holistic_delta,
        },
        "recommendations": recs,
    }


def cross_kasten_aggregate(per_kasten: list[dict]) -> dict:
    ok = [p for p in per_kasten if p.get("status") == "ok"]
    if not ok:
        return {"status": "no_data"}
    comps = [p["composite"]["current"] for p in ok if p["composite"]["current"] is not None]
    deltas = [p["composite"]["delta"] for p in ok if p["composite"]["delta"] is not None]
    g1s = [
        p["holistic"]["current"]["gold_at_1_unconditional"]
        for p in ok
        if isinstance(p["holistic"]["current"].get("gold_at_1_unconditional"), (int, float))
    ]
    note = (
        "An improvement that lands on only one Kasten is suspect — a true "
        "pipeline gain moves the mean composite AND does not regress either "
        "Kasten's gold@1. Use min(delta) as the overfit guardrail."
    )
    return {
        "status": "ok",
        "n_kastens": len(ok),
        "mean_composite": round(sum(comps) / len(comps), 2) if comps else None,
        "mean_composite_delta": round(sum(deltas) / len(deltas), 2) if deltas else None,
        "min_composite_delta": round(min(deltas), 2) if deltas else None,
        "mean_gold_at_1": round(sum(g1s) / len(g1s), 4) if g1s else None,
        "overfit_guardrail": note,
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="rag_eval_v2 baseline comparator")
    p.add_argument("--iter", type=int, required=True, dest="iter_n")
    p.add_argument("--kasten", choices=list(KASTENS), default=None)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    targets = [args.kasten] if args.kasten else list(KASTENS)
    per_kasten = [compare_one(k, args.iter_n) for k in targets]
    report = {
        "iter": args.iter_n,
        "per_kasten": per_kasten,
        "cross_kasten": cross_kasten_aggregate(per_kasten),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
