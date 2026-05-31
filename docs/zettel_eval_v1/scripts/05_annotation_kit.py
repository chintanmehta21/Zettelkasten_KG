"""05_annotation_kit.py — generate annotation CSVs + ingest filled responses.

WIRED implementation (2026-05-28 TDD). Two phases:

  --emit:
    1. Read manifest.json -> list of (wz_uuid, normalized_url, title) tuples.
    2. Random-shuffle with a content-hash-seeded RNG for reproducibility.
    3. Write annotation/round-1/shuffled_assignments.csv from
       _config/annotation_template.csv header.
    4. round=retest: random sample of 10 zettels from round-1's set.
    5. round=pairwise: 30 random pairs from manifest.

  --ingest:
    1. Read annotation/round-<N>/responses.csv (operator-filled).
    2. Validate all axis scores in [1, 5].
    3. Normalise each axis to [0, 1] via (score-1)/4.
    4. Write annotation/round-<N>/responses.normalized.json.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
EVAL = REPO_ROOT / "docs" / "zettel_eval_v1"
ANNOT = EVAL / "annotation"
MANIFEST = EVAL / "_config" / "manifest.json"
TEMPLATE = EVAL / "_config" / "annotation_template.csv"


def _seed_from_manifest() -> int:
    return int.from_bytes(hashlib.sha1(MANIFEST.read_bytes()).digest()[:4], "big")


def _template_columns() -> list[str]:
    """Read the annotation template header."""
    with TEMPLATE.open(encoding="utf-8") as f:
        rdr = csv.reader(f)
        cols = next(rdr)
    return cols


def cmd_emit(round_name: str) -> int:
    rdir = ANNOT / f"round-{round_name}"
    rdir.mkdir(parents=True, exist_ok=True)
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    zettels = m["zettels"]
    if not zettels:
        raise SystemExit("manifest is empty; run 01_freeze_manifest.py first.")

    rng = random.Random(_seed_from_manifest())

    if round_name == "1":
        ordered = zettels[:]
        rng.shuffle(ordered)
        out = rdir / "shuffled_assignments.csv"
        cols = _template_columns()
        with out.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
            for i, z in enumerate(ordered):
                w.writerow({
                    "zettel_uuid": z["workspace_zettel_id"],
                    "shown_order": i + 1,
                    "faithfulness_1_to_5": "",
                    "coverage_1_to_5": "",
                    "conciseness_1_to_5": "",
                    "coherence_1_to_5": "",
                    "comment": "",
                    "annotation_started_at_iso": "",
                    "annotation_finished_at_iso": "",
                })
        # also emit source_links.md
        (rdir / "source_links.md").write_text(
            "# Round 1 — source links\n\n" +
            "\n".join(f"{i+1}. [{z.get('title','(no title)')[:60]}]({z['normalized_url']}) `wz={z['workspace_zettel_id']}`"
                      for i, z in enumerate(ordered)),
            encoding="utf-8",
        )
        print(f"[05] emit round-1: {len(ordered)} zettels -> {out}")
    elif round_name == "retest":
        # random 10 from round-1
        rng2 = random.Random(_seed_from_manifest() ^ 0x12345678)
        sample = rng2.sample(zettels, min(10, len(zettels)))
        cols = _template_columns()
        out = rdir / "shuffled_assignments.csv"
        with out.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
            for i, z in enumerate(sample):
                w.writerow({"zettel_uuid": z["workspace_zettel_id"], "shown_order": i + 1,
                            **{k: "" for k in cols if k not in {"zettel_uuid","shown_order"}}})
        print(f"[05] emit round-retest: {len(sample)} zettels -> {out}")
    elif round_name == "pairwise":
        # 30 random pairs
        rng3 = random.Random(_seed_from_manifest() ^ 0xABCDEF01)
        all_pairs = list(itertools.combinations(zettels, 2))
        n_pairs = min(30, len(all_pairs))
        chosen = rng3.sample(all_pairs, n_pairs)
        out = rdir / "responses.csv"
        with out.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["pair_index", "left_wz_uuid", "right_wz_uuid",
                        "left_title", "right_title", "preference",  # left|right|tie
                        "comment", "annotation_started_at_iso", "annotation_finished_at_iso"])
            for i, (a, b) in enumerate(chosen):
                w.writerow([i + 1, a["workspace_zettel_id"], b["workspace_zettel_id"],
                            a.get("title","")[:60], b.get("title","")[:60], "", "", "", ""])
        print(f"[05] emit round-pairwise: {n_pairs} pairs -> {out}")
    else:
        raise SystemExit(f"unknown round {round_name!r}")
    return 0


def cmd_ingest(round_name: str) -> int:
    rdir = ANNOT / f"round-{round_name}"
    resp = rdir / "responses.csv"
    if not resp.exists():
        raise SystemExit(f"{resp} not found; annotator hasn't filled it yet.")

    out = {"round": round_name, "responses": []}
    with resp.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if round_name == "pairwise":
        out["preferences"] = []
        for r in rows:
            pref = (r.get("preference") or "").strip().lower()
            if pref not in {"left", "right", "tie"}:
                # skip un-annotated
                continue
            out["preferences"].append({
                "pair_index": int(r["pair_index"]),
                "left_wz": r["left_wz_uuid"],
                "right_wz": r["right_wz_uuid"],
                "preference": pref,
            })
        print(f"[05] ingested {len(out['preferences'])} pairwise preferences")
    else:
        for r in rows:
            try:
                f_, c_, n_, h_ = [int(r[f"{ax}_1_to_5"]) for ax in
                                  ("faithfulness", "coverage", "conciseness", "coherence")]
            except (KeyError, ValueError, TypeError):
                continue
            for v in (f_, c_, n_, h_):
                if not (1 <= v <= 5):
                    raise SystemExit(f"score out of [1,5] for {r.get('zettel_uuid')}: {v}")
            norm = {"faithfulness": (f_ - 1) / 4, "coverage": (c_ - 1) / 4,
                    "conciseness": (n_ - 1) / 4, "coherence": (h_ - 1) / 4}
            out["responses"].append({
                "zettel_uuid": r["zettel_uuid"],
                "shown_order": int(r.get("shown_order") or 0),
                "scores_raw": {"faithfulness": f_, "coverage": c_, "conciseness": n_, "coherence": h_},
                "scores_normalized": norm,
                "comment": r.get("comment", ""),
                "annotation_started_at_iso": r.get("annotation_started_at_iso", ""),
                "annotation_finished_at_iso": r.get("annotation_finished_at_iso", ""),
            })
        print(f"[05] ingested {len(out['responses'])} responses")

    out_path = rdir / "responses.normalized.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[05] wrote {out_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--emit", action="store_true")
    ap.add_argument("--ingest", action="store_true")
    ap.add_argument("--round", choices=["1", "retest", "pairwise"], default="1")
    ap.add_argument("--annotation-root", type=Path, default=None,
                    help="override the annotation output dir (default: "
                         "docs/zettel_eval_v1/annotation). Tests point this at a "
                         "temp dir so they never clobber real human annotations.")
    args = ap.parse_args()
    if args.annotation_root is not None:
        global ANNOT
        ANNOT = args.annotation_root
    if args.emit == args.ingest:
        ap.error("specify exactly one of --emit / --ingest")
    if args.emit:
        return cmd_emit(args.round)
    return cmd_ingest(args.round)


if __name__ == "__main__":
    raise SystemExit(main())
