"""Iter-03 §9: corpus drift detector for the int8 BGE calibration set.

Reads the current corpus stats from Supabase, compares to
models/calibration_baseline.json, and reports YES + breached thresholds when
any of (chunk_count delta > 10%, source_type proportion delta > 5pp, embedding
centroid L2 > 0.05) are exceeded. The drift cron uses this to decide whether
to open an auto-refresh PR.

Returns exit 0 (no drift) / 1 (drift detected) / 2 (config / IO error) for
the workflow to branch on.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("check_corpus_drift")


def detect_drift(
    *,
    baseline_path: Path,
    current_stats: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Return (drifted, reasons). reasons is a list of human-readable breach descriptions."""
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    base_stats = baseline.get("corpus_stats", {})
    thresholds = baseline.get("drift_thresholds", {})
    reasons: list[str] = []

    base_count = max(int(base_stats.get("chunk_count", 0)), 1)
    cur_count = int(current_stats.get("chunk_count", 0))
    cc_delta = abs(cur_count - base_count) / base_count
    cc_max = float(thresholds.get("chunk_count_pct_delta_max", 0.10))
    if cc_delta > cc_max:
        reasons.append(
            f"chunk_count delta {cc_delta:.1%} > threshold {cc_max:.1%} "
            f"(baseline={base_count} current={cur_count})"
        )

    base_dist = base_stats.get("source_type_distribution", {}) or {}
    cur_dist = current_stats.get("source_type_distribution", {}) or {}
    st_max = float(thresholds.get("source_type_proportion_pp_max", 0.05))
    keys = set(base_dist) | set(cur_dist)
    for k in sorted(keys):
        delta = abs(float(base_dist.get(k, 0)) - float(cur_dist.get(k, 0)))
        if delta > st_max:
            reasons.append(
                f"source_type[{k}] delta {delta:.3f} > threshold {st_max:.3f} "
                f"(baseline={base_dist.get(k, 0)} current={cur_dist.get(k, 0)})"
            )

    base_cent = base_stats.get("embedding_centroid") or []
    cur_cent = current_stats.get("embedding_centroid") or []
    if len(base_cent) == len(cur_cent) and base_cent:
        l2 = math.sqrt(sum((a - b) ** 2 for a, b in zip(base_cent, cur_cent)))
        l2_max = float(thresholds.get("centroid_l2_max", 0.05))
        if l2 > l2_max:
            reasons.append(
                f"embedding_centroid L2 distance {l2:.4f} > threshold {l2_max:.4f}"
            )

    return (len(reasons) > 0, reasons)


def _load_supabase_stats() -> dict[str, Any]:
    """Pull current corpus stats from Supabase.

    The legacy implementation read a flat ``public.chunks`` table
    (source_type + float[] embedding) that was purged with DB v2 (table
    dropped; v2 stores embeddings as opaque ``halfvec`` and source_type on
    the parent zettel, with no client-side centroid path). The Supabase
    input is unavailable until the v2 eval-driver rebuild ships a corpus-
    stats RPC; use ``--current-json`` with precomputed stats instead.
    """
    raise NotImplementedError(
        "check_corpus_drift._load_supabase_stats: v2 eval-driver rebuild "
        "pending — legacy slug-keyed public.chunks path purged; see "
        "rag_eval_v2 (Phase E). Use --current-json instead."
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", default="models/calibration_baseline.json")
    p.add_argument("--current-from-supabase", action="store_true",
                   help="Pull current stats from Supabase (default: read from --current-json)")
    p.add_argument("--current-json", help="Path to JSON file with current stats (alternative to Supabase)")
    p.add_argument("--report-out", help="Optional path to write drift report JSON")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    baseline_path = Path(args.baseline)
    if not baseline_path.exists():
        logger.error("baseline missing: %s", baseline_path)
        return 2

    if args.current_from_supabase:
        current = _load_supabase_stats()
    elif args.current_json:
        current = json.loads(Path(args.current_json).read_text(encoding="utf-8"))
    else:
        logger.error("must pass --current-from-supabase OR --current-json")
        return 2

    drifted, reasons = detect_drift(baseline_path=baseline_path, current_stats=current)
    report = {"drifted": drifted, "reasons": reasons, "current_stats": current}
    if args.report_out:
        Path(args.report_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    if drifted:
        logger.warning("DRIFT DETECTED")
        for r in reasons:
            logger.warning("  - %s", r)
        return 1
    logger.info("no drift")
    return 0


if __name__ == "__main__":
    sys.exit(main())
