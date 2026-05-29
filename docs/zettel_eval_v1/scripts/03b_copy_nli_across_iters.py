"""03b_copy_nli_across_iters.py — copy the `nli` block of every per_zettel
JSON from a source iter to one or more destination iters.

WIRED 2026-05-29. Motivation: the NLI signal is iter-independent — it depends
only on summary.json and source_text.md (both frozen by the manifest), not on
which LLM judge produced the rubric/g_eval block. Running the heavy
MiniCheck-DeBERTa pass once for iter-003 and propagating to iter-004 /
iter-005 saves ~3 hours of CPU work and produces *exactly* the same NLI
scores (byte-identical) in every iter.

Usage:
    python docs/zettel_eval_v1/scripts/03b_copy_nli_across_iters.py \\
        --from iter-003-nli --to iter-004-jury iter-005-extract-swap

Per zettel:
  - Read source iter per_zettel JSON, extract `nli` block.
  - For each destination iter, find the same wz_uuid per_zettel JSON,
    inject the nli block (overwriting any existing), write to disk
    (both _overall and source-type subdirs).
  - Skip silently if the source has no nli block (real-NLI not yet computed).
  - Fail loud if the destination iter dir doesn't exist (operator typo).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
EVAL = REPO_ROOT / "docs" / "zettel_eval_v1"
RUNS = EVAL / "runs"


def _iter_per_zettel(run_dir: Path):
    """Yield (wz_id, _overall_path, per_source_path_or_None) for every zettel
    in an iter's run dir. _overall and per-source files are mirrors except
    when one writer ran before the other; the script syncs both."""
    overall_dir = run_dir / "_overall" / "per_zettel"
    if not overall_dir.exists():
        raise SystemExit(f"missing per_zettel dir: {overall_dir}")
    for f in sorted(overall_dir.glob("*.json")):
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  WARN  cannot parse {f.name}: {exc}")
            continue
        wz_id = f.stem
        src_type = (payload.get("_meta") or {}).get("source_type", "")
        per_source = None
        if src_type:
            cand = run_dir / src_type / "per_zettel" / f.name
            if cand.exists():
                per_source = cand
        yield wz_id, f, per_source, payload


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="src_iter", required=True,
                    help="source iter_id (must already have real NLI populated)")
    ap.add_argument("--to", dest="dst_iters", required=True, nargs="+",
                    help="one or more destination iter_ids to copy NLI into")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be copied but don't write")
    args = ap.parse_args()

    src_dir = RUNS / args.src_iter
    if not (src_dir / "_overall" / "per_zettel").exists():
        raise SystemExit(f"source iter not found: {src_dir}")

    # Build source nli map: wz_id -> nli block (None if missing)
    src_nli: dict[str, dict] = {}
    missing_in_src = 0
    for wz_id, _overall, _per_src, payload in _iter_per_zettel(src_dir):
        nli = payload.get("nli")
        if isinstance(nli, dict) and "per_claim" in nli:
            src_nli[wz_id] = nli
        else:
            missing_in_src += 1
    print(f"[03b] source {args.src_iter}: {len(src_nli)} with nli, "
          f"{missing_in_src} missing")
    if not src_nli:
        raise SystemExit(f"source iter has zero nli blocks — refusing to copy nothing.")

    total_copied = 0
    for dst_iter_id in args.dst_iters:
        dst_dir = RUNS / dst_iter_id
        if not (dst_dir / "_overall" / "per_zettel").exists():
            print(f"[03b] SKIP {dst_iter_id}: per_zettel dir missing "
                  f"(run 02_run_judge first)")
            continue
        copied = 0; matched_no_overwrite = 0; orphans = 0
        for wz_id, overall_path, per_src_path, payload in _iter_per_zettel(dst_dir):
            nli = src_nli.get(wz_id)
            if nli is None:
                orphans += 1
                continue
            # Inject — replaces any existing nli (including fake stubs from earlier tests)
            payload["nli"] = nli
            if not args.dry_run:
                overall_path.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                if per_src_path is not None:
                    # Sync to per-source mirror too
                    try:
                        side_payload = json.loads(per_src_path.read_text(encoding="utf-8"))
                        side_payload["nli"] = nli
                        per_src_path.write_text(
                            json.dumps(side_payload, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8",
                        )
                    except Exception as exc:
                        print(f"  WARN  side-mirror write failed for {wz_id}: {exc}")
            copied += 1
        print(f"[03b] {dst_iter_id}: copied {copied}, "
              f"orphans (dst has no matching src) {orphans}"
              + (" [DRY-RUN]" if args.dry_run else ""))
        total_copied += copied

    print(f"\n[03b] total nli blocks copied: {total_copied}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
